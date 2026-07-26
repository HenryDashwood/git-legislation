/** Read-only SQL repository, ported from src/git_legislation_api/repositories.py. */

import type { Sql } from "postgres";
import type { DocumentListFilters, EffectFilters, Repository, Row } from "./types";

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
      select ordinal, provision_type, number, heading, anchor, markdown
      from provisions
      where version_id = $1
      order by ordinal
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
        id, version_id, document_id, ordinal, provision_type, number, heading,
        anchor, markdown, plain_text
      from provisions
      where version_id = $1 and anchor = $2
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
