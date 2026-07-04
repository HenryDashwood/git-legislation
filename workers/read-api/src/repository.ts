/** Read-only SQL repository, ported from src/git_legislation_api/repositories.py. */

import type { Sql } from "postgres";
import type { DocumentListFilters, Repository, Row } from "./types";

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
    return await sql.unsafe(
      `
      select ${DOCUMENT_COLUMNS}
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
      order by d.calendar_year nulls last, d.legislation_type, d.number, d.id
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
        status, extent, latest_version_id, created_at, updated_at
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
