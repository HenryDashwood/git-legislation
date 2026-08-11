/** Read-only SQL repository, ported from src/git_legislation_api/repositories.py. */

import type { Sql } from "postgres";
import type {
  DocumentListFilters,
  EffectFilters,
  PowerSearchPlan,
  Repository,
  Row,
} from "./types";

const EFFECT_COLUMNS = `
  e.id,
  e.effect_type,
  e.textual_kind,
  e.applied,
  e.prospective,
  e.in_force_date,
  e.in_force_qualification,
  e.commencement_authority,
  e.commencing_document_id,
  e.affected_document_id,
  e.affected_title,
  e.affected_provisions,
  e.affecting_document_id,
  e.affecting_title,
  e.affecting_provisions
`;

const DOCUMENT_COLUMNS = `
  d.id,
  d.legislation_type,
  d.year,
  d.calendar_year,
  d.number,
  d.title,
  d.document_uri,
  d.status,
  d.extent,
  d.legal_date,
  d.legal_date_kind,
  d.latest_version_id,
  d.created_at,
  d.updated_at
`;

const VERSION_COLUMNS = `
  id,
  document_id,
  version_kind,
  snapshot_date,
  source_uri,
  source_object_key,
  markdown_object_key,
  word_count,
  is_metadata_only,
  created_at
`;

/**
 * Scores a power against a search plan. The weights are deliberately in SQL
 * rather than the caller: ranking depends on columns only the database has
 * (resolved targets, act-scoped class membership), and keeping it here means
 * the web app and any future API consumer rank identically.
 *
 * Weights were tuned against the acceptance question "force NESO to give me
 * information about a blackout", which must return Electricity Act 1989 s.96
 * in the top few. They are hand-set and want a proper eval set.
 */
/**
 * Postgres array literal for a text[] bind. sql.unsafe() passes parameters
 * through untouched, so a JS array arrives as "a,b,c" and Postgres rejects it;
 * the literal form has to be built (and escaped) here.
 */
export function toPgTextArray(values: string[]): string {
  const escaped = values.map((value) => `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`);
  return `{${escaped.join(",")}}`;
}

/**
 * Build a websearch_to_tsquery string from the plan's terms.
 *
 * Each term becomes an AND of its words rather than a quoted phrase, and the
 * terms are OR-ed together. Phrases were too strict to be useful: the term
 * "deprivation of citizenship" did not match "deprive a person of citizenship
 * status" (s.40 British Nationality Act 1981) because the words are not
 * adjacent, even though both stem identically.
 *
 * "or", "and" and a leading "-" are websearch operators, so they are stripped
 * from inside a term - otherwise a term like "peace order and good
 * government" would silently reparse into something else.
 */
export function buildTsquery(terms: string[]): string {
  const cleaned = terms
    .map((term) =>
      term
        .replace(/["()]/g, " ")
        .replace(/(^|\s)-+/g, " ")
        .split(/\s+/)
        .filter((word) => word !== "" && !["or", "and"].includes(word.toLowerCase()))
        .join(" ")
        .trim(),
    )
    .filter((term) => term !== "");
  // An empty query matches nothing; "power" keeps a target-only search working.
  return cleaned.join(" OR ") || "power";
}

const POWER_SEARCH_SQL = `
with target_hits as (
  -- One branch per way a power can be "about" a body, unioned rather than
  -- OR-ed: a three-table OR forces a scan of every target row, while each
  -- branch on its own uses the trigram index.
  select t.duty_id
  from duties.power_targets t
  where t.target_text ilike any ($2::text[])
  union
  select t.duty_id
  from duties.power_targets t
  join orgs.entities e on e.id = t.entity_id
  where e.name ilike any ($2::text[])
  union
  -- ...and powers addressed to a class the body belongs to, but only within
  -- the Act that defines the class: "licence holder" means something
  -- different in every enactment.
  select t.duty_id
  from duties.power_targets t
  join duties.duties dd on dd.id = t.duty_id
  join orgs.entity_class_members m
    on m.class_id = t.entity_id and m.document_id = dd.document_id
  join orgs.entities member on member.id = m.entity_id
  where member.name ilike any ($2::text[])
),
-- Candidates are bounded before scoring. Ranking touches the heap for every
-- match, so a broad term ("report" matches 58,704 powers on its own) would
-- otherwise decide how long the page takes.
matched as (
  select d.id
  from duties.duties d
  where d.action_tsv @@ websearch_to_tsquery('english', $1)
    and ($5::text = 'both' or d.modality = $5::text)
    and ($6::text is null or d.actor ~* $6::text)
  -- Ordered before the cap. An unordered limit silently hid the right answer
  -- more than once (s.77 Town and Country Planning Act 1990, s.40 British
  -- Nationality Act 1981) and cost ~0.02s to fix.
  order by ts_rank(d.action_tsv, websearch_to_tsquery('english', $1)) desc
  limit 4000
),
candidates as (
  select id from matched
  union
  select duty_id as id from target_hits
),
ranked as (
  select
    d.id,
    d.document_id,
    d.enactment_title,
    d.enactment_type,
    d.section_path,
    d.section_uri,
    d.actor,
    d.action,
    d.condition,
    d.modality,
    pe.instrument,
    pe.is_direction_power,
    pe.si_procedure,
    round((
        ts_rank(d.action_tsv, websearch_to_tsquery('english', $1))
      + case when th.duty_id is not null then 0.40 else 0 end
      + case when pe.instrument = any ($3::text[]) then 0.25 else 0 end
      + case when pe.is_direction_power and 'direct' = any ($3::text[]) then 0.30 else 0 end
      + case when $4::text <> '' and d.enactment_title ~* $4::text then 0.25 else 0 end
      + case when $4::text <> '' and d.action ~* $4::text then 0.20 else 0 end
    )::numeric, 4) as score
  from candidates c
  join duties.duties d on d.id = c.id
  join duties.power_enrichments pe on pe.duty_id = d.id
  left join target_hits th on th.duty_id = d.id
  where
    ($5::text = 'both' or d.modality = $5::text)
    and ($6::text is null or d.actor ~* $6::text)
    and ($7::boolean is not true or pe.is_direction_power)
    and ($8::boolean is not true or d.condition is not null)
    and ($9::text = 'all'
         or ($9::text = 'primary' and d.enactment_type in ('ukpga','asp','anaw','asc','apni','aep','apgb','aip','nia','ukla','ukcm','mwa','mnia','aosp','ukppa','gbla'))
         or ($9::text = 'secondary' and d.enactment_type in ('uksi','ssi','wsi','nisr','nisi','nisro','eur','eudn','eudr')))
  order by score desc, d.id
  limit $10
)
-- The per-power target list is looked up only for the rows actually returned;
-- inside the ranked CTE it would run for every candidate before the limit.
select
  ranked.*,
  coalesce(
    (
      select jsonb_agg(distinct pt.target_text)
      from duties.power_targets pt where pt.duty_id = ranked.id
    ),
    '[]'::jsonb
  ) as targets
from ranked
order by score desc, id
`;

export class PostgresRepository implements Repository {
  constructor(private readonly sql: Sql) {}

  async listDocuments(filters: DocumentListFilters): Promise<Row[]> {
    const sql = this.sql;
    // "newest" is legal chronology: made date for instruments, Royal Assent
    // for Acts. Undated documents (metadata-only shells) fall back to the
    // start of their year, then sort by number — numeric, not int: ukmo
    // documents use 13-digit ISBNs as their number.
    const orderBy =
      filters.sort === "newest"
        ? `coalesce(d.legal_date, make_date(d.calendar_year, 1, 1)) desc nulls last,
           case when d.number ~ '^[0-9]+$' then d.number::numeric end desc nulls last,
           d.id desc`
        : "d.calendar_year nulls last, d.legislation_type, d.number, d.id";
    return await sql.unsafe(
      `
      select ${DOCUMENT_COLUMNS},
        latest_dv.word_count as latest_word_count,
        latest_dv.is_metadata_only as latest_is_metadata_only
      from documents d
      left join document_versions latest_dv on latest_dv.id = d.latest_version_id
      where 1 = 1
        and ($1::text is null or d.legislation_type = $1)
        and ($2::int is null or d.calendar_year = $2)
        and ($3::text is null or d.number = $3)
        and ($4::text is null or d.status = $4)
        and ($5::text is null or d.extent = $5)
        and ($6::boolean is null or latest_dv.is_metadata_only = $6)
        and ($7::text is null or d.title ilike '%' || $7 || '%')
      order by ${orderBy}
      limit $8 offset $9
      `,
      [
        filters.legislationType,
        filters.year,
        filters.number,
        filters.status,
        filters.extent,
        filters.metadataOnly,
        filters.q,
        filters.limit,
        filters.offset,
      ],
    );
  }

  async summarizeDocuments(): Promise<Row[]> {
    return await this.sql.unsafe(`
      select
        legislation_type,
        count(*)::int as document_count,
        min(calendar_year) as first_year,
        max(calendar_year) as last_year
      from documents
      group by legislation_type
      order by legislation_type
    `);
  }

  async getDocument(documentId: string): Promise<Row | null> {
    const rows = await this.sql.unsafe(
      `
      select
        id, legislation_type, year, calendar_year, number, title, document_uri,
        status, extent, legal_date, legal_date_kind, latest_version_id, created_at, updated_at
      from documents
      where id = $1
      `,
      [documentId],
    );
    const document = rows[0];
    if (document === undefined) {
      return null;
    }
    const latestVersionId = document["latest_version_id"];
    document["latest_version"] =
      typeof latestVersionId === "string" ? await this.getVersion(latestVersionId) : null;
    return document;
  }

  async listVersions(documentId: string): Promise<Row[]> {
    return await this.sql.unsafe(
      `
      select ${VERSION_COLUMNS}
      from document_versions
      where document_id = $1
      order by version_kind, snapshot_date nulls first, created_at, id
      `,
      [documentId],
    );
  }

  async getVersion(versionId: string): Promise<Row | null> {
    const rows = await this.sql.unsafe(
      `
      select ${VERSION_COLUMNS}
      from document_versions
      where id = $1
      `,
      [versionId],
    );
    return rows[0] ?? null;
  }

  async listProvisions(versionId: string): Promise<Row[]> {
    return await this.sql.unsafe(
      `
      select id, version_id, document_id, ordinal, provision_type, number, heading, anchor
      from provisions
      where version_id = $1
      order by ordinal
      `,
      [versionId],
    );
  }

  async listProvisionTexts(versionId: string): Promise<Row[]> {
    return await this.sql.unsafe(
      `
      select p.ordinal, p.provision_type, p.number, p.extent, p.heading, p.anchor,
             p.text_sha256, t.markdown
      from provisions p
      join provision_texts t on t.sha256 = p.text_sha256
      where p.version_id = $1
      order by p.ordinal
      `,
      [versionId],
    );
  }

  async listEffects(filters: EffectFilters): Promise<Row[]> {
    const column = filters.direction === "affecting" ? "affecting_document_id" : "affected_document_id";
    // affected_section_numbers lets the caller line an effect up with a
    // provision without a second query per effect.
    return await this.sql.unsafe(
      `
      select ${EFFECT_COLUMNS},
        (
          select array_agg(distinct ep.section_number)
          from effect_provisions ep
          where ep.effect_id = e.id and ep.side = 'affected' and ep.section_number is not null
        ) as affected_section_numbers,
        (
          select array_agg(distinct ep.provision_kind)
          from effect_provisions ep
          where ep.effect_id = e.id and ep.side = 'affected' and ep.provision_kind is not null
        ) as affected_provision_kinds
      from effects e
      where e.${column} = $1
        and ($2::date is null or e.in_force_date > $2)
        and ($3::date is null or e.in_force_date <= $3)
        and ($4::boolean is not true or e.textual_kind = 'T')
      order by e.in_force_date desc nulls last, e.id
      limit $5
      `,
      [
        filters.documentId,
        filters.inForceAfter ?? null,
        filters.inForceThrough ?? null,
        filters.textualOnly ?? false,
        filters.limit ?? 500,
      ],
    );
  }

  async summarizeChangeset(affectingDocumentId: string): Promise<Row[]> {
    return await this.sql.unsafe(
      `
      select
        e.affected_document_id,
        coalesce(max(e.affected_title), max(d.title)) as affected_title,
        count(*)::int as effect_count,
        count(*) filter (where e.textual_kind = 'T')::int as textual_count,
        count(*) filter (where e.applied)::int as applied_count,
        count(*) filter (where e.prospective)::int as prospective_count,
        min(e.in_force_date) as first_in_force,
        max(e.in_force_date) as last_in_force,
        (d.id is not null) as in_corpus
      from effects e
      left join documents d on d.id = e.affected_document_id
      where e.affecting_document_id = $1
      group by e.affected_document_id, d.id
      order by effect_count desc, e.affected_document_id
      `,
      [affectingDocumentId],
    );
  }

  async getProvision(versionId: string, anchor: string): Promise<Row | null> {
    const rows = await this.sql.unsafe(
      `
      select
        p.id, p.version_id, p.document_id, p.ordinal, p.provision_type, p.number, p.heading,
        p.anchor, p.extent, t.markdown, t.plain_text
      from provisions p
      join provision_texts t on t.sha256 = p.text_sha256
      where p.version_id = $1 and p.anchor = $2
      `,
      [versionId, anchor],
    );
    return rows[0] ?? null;
  }

  async listFiles(versionId: string): Promise<Row[]> {
    return await this.sql.unsafe(_filesSql("df.version_id = $1"), [versionId]);
  }

  async getCanonicalFile(versionId: string, fileKind: string): Promise<Row | null> {
    const rows = await this.sql.unsafe(
      _filesSql("df.version_id = $1 and df.file_kind = $2 and df.is_canonical"),
      [versionId, fileKind],
    );
    return rows[0] ?? null;
  }

  async getFile(fileId: number): Promise<Row | null> {
    const rows = await this.sql.unsafe(_filesSql("df.id = $1"), [fileId]);
    return rows[0] ?? null;
  }
  async searchPowers(plan: PowerSearchPlan): Promise<Row[]> {
    const targetPatterns = plan.targets.filter((t) => t.trim() !== "").map((t) => `%${t.trim()}%`);
    // Terms only. Targets have their own matching path (target_hits), and
    // feeding them to the text query as well floods it: a target of "person"
    // took one search from 50 candidate rows to 13,536.
    const tsquery = buildTsquery(plan.terms);
    return await this.sql.unsafe(POWER_SEARCH_SQL, [
      tsquery,
      toPgTextArray(targetPatterns),
      toPgTextArray(plan.instruments),
      plan.domain.filter((d) => d.trim() !== "").join("|"),
      plan.modality,
      plan.actor,
      plan.directionOnly,
      plan.withConditionsOnly,
      plan.legislationKind,
      plan.limit,
    ]);
  }
}

function _filesSql(whereClause: string): string {
  return `
    select
      df.id::int as id,
      df.document_id,
      df.version_id,
      df.file_kind,
      df.source_url,
      df.object_key,
      df.sha256,
      df.is_canonical,
      so.bucket,
      so.byte_size::int as byte_size,
      so.content_type,
      so.sha256 as object_sha256,
      df.created_at
    from document_files df
    left join storage_objects so on so.key = df.object_key
    where ${whereClause}
    order by df.is_canonical desc, df.file_kind, df.id
  `;

}
