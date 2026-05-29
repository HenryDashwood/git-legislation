# git-legislation

Represent UK legislation as structured, reproducible data.

The project currently fetches legislation.gov.uk XML, converts it into deterministic Markdown, and publishes the generated corpus into a local Postgres database plus a filesystem-backed object store. The longer-term goal is to make changes to law inspectable with ordinary software tools: stable source data, readable text diffs, reviewable imports, and a backend that can serve the corpus through an API.

## Current State

The working pipeline is:

```text
legislation.gov.uk
  -> output/xml/...
  -> output/markdown/...
  -> Postgres metadata/search tables
  -> var/object-store/... Markdown/XML objects
```

Implemented pieces:

- Python CLI for fetching, converting, auditing, seeding, and publishing legislation data.
- Local Postgres via Docker Compose.
- Goose migrations under `db/migrations`.
- Schema dump under `db/schema.sql`.
- Local filesystem object store under `var/object-store`.
- Postgres publishing for documents, versions, provisions, file metadata, and object metadata.
- Markdown publishing normalization for legacy CP-1252 punctuation found in some source metadata.

The current broad snapshot has been fetched and converted for configured non-draft legislation types. Some records are full-text CLML-derived Markdown; many older or metadata-only records are Markdown stubs pointing to PDF alternatives.

## Local Setup

Start Postgres:

```bash
docker compose up -d
```

The local database connection is expected in `.env` as `DB_URL`, for example:

```bash
DB_URL=postgres://postgres:postgres@localhost:5432/british_legislation?sslmode=disable
```

Run migrations:

```bash
make migrate-up
```

Check migration status:

```bash
make migrate-status
```

Dump the current schema:

```bash
make db-dump
```

## Main Workflow

Fetch a point-in-time corpus:

```bash
uv run git-legislation fetch-point-in-time-corpus --at 2026-05-05
```

Limit to one or more legislation types:

```bash
uv run git-legislation fetch-point-in-time-corpus --at 2026-05-05 --legislation-type ukpga
```

Convert fetched XML to Markdown:

```bash
uv run git-legislation convert-point-in-time-corpus --at 2026-05-05
```

Publish converted Markdown/XML into Postgres and the local object store:

```bash
set -a; . ./.env; set +a
uv run git-legislation publish-markdown-postgres --at 2026-05-05
```

The publisher writes:

```text
var/object-store/legislation/markdown/point-in-time/{date}/{type}/...
var/object-store/legislation/xml/point-in-time/{date}/{type}/...
```

and upserts rows into:

- `documents`
- `document_versions`
- `provisions`
- `storage_objects`
- `document_files`

You can publish one type at a time:

```bash
uv run git-legislation publish-markdown-postgres --at 2026-05-05 --legislation-type uksi
```

## Data Model

The core distinction is:

- `documents`: stable abstract legislation identities, such as `ukpga/2026/14`.
- `document_versions`: concrete textual states, such as enacted or point-in-time versions.
- `provisions`: extracted browse/search units from generated Markdown.
- `storage_objects`: object-store entries for Markdown, XML, and later PDFs or extracted text.
- `document_files`: links between documents, versions, source URLs, and stored objects.

The object store is currently local filesystem storage. It is intended to mirror the shape of a future Cloudflare R2 bucket, so the application can later swap the storage backend without changing the database model.

## Source Data

Useful legislation.gov.uk resources:

- Data reuse docs: https://legislation.github.io/data-documentation/
- API overview: https://legislation.github.io/data-documentation/api/overview.html
- Formats: https://legislation.github.io/data-documentation/formats/overview.html
- Search, lists, and feeds: https://legislation.github.io/data-documentation/api/search.html
- Publication Log: https://legislation.github.io/data-documentation/api/publication-log.html
- URI scheme and type codes: https://legislation.github.io/data-documentation/model/uris.html
- Research bulk downloads: https://research.legislation.gov.uk/data

Key assumptions:

- CLML XML is the canonical source where available.
- PDF-only or metadata-only records are valid coverage gaps, not pipeline failures.
- Official revised CLML should be the source of truth for v1 text updates.
- Effects feeds should be stored as audit metadata later, not used alone to rewrite text.

## Roadmap

### 1. Stabilize Publishing

- Make ingestion and publishing idempotent:
  - record fetch/publish runs explicitly;
  - track observations separately from document versions;
  - use content hashes to avoid creating duplicate versions when a new run sees unchanged source content.
- Move toward object-store-native ingestion:
  - fetch XML directly into the object store;
  - convert XML bytes/text in memory instead of requiring an intermediate file;
  - write generated Markdown directly into the object store;
  - upsert Postgres metadata, file links, versions, and provisions as the catalog/index.
- Make `output/` optional rather than central:
  - keep it as a local debug/export cache;
  - add an explicit flag or command for writing filesystem artifacts when needed;
  - avoid requiring `output/xml` and `output/markdown` as the normal pipeline boundary.
- Add a command that reports corpus counts across source observations, document versions, provisions, and object storage.
- Add better progress reporting for large publish runs.
- Decide whether normalized Markdown should be persisted as a stored object only, written back to debug exports, or both.

### 2. Improve Markdown Quality

- Add a Markdown quality audit command.
- Compare XML structure against Markdown output for full-text CLML records.
- Flag missing schedules, weak headings, table-heavy documents, empty bodies, and metadata-only stubs.
- Add representative snapshot tests across legislation types and eras.
- Improve handling of schedules, tables, forms, images, commentary, repeals, and prospective text.

### 3. Handle PDF-Backed Records

- Download/cache PDF alternatives into the object store.
- Extract richer metadata from metadata-only XML.
- Evaluate PDF text extraction quality on a sample set.
- Decide how PDF-derived text should be marked, reviewed, and served.

### 4. Build A Read API

- Add a Cloudflare Worker or other lightweight backend for read-only access.
- Start with routes for document lookup, latest version, version files, and provisions.
- Use Postgres for metadata/provisions and object storage for Markdown/XML/PDF content.
- Add `sqlc` or another query-generation layer once the API query surface is stable.

### 5. Incremental Updates

- Poll the Publication Log.
- Track the last processed publication event.
- Fetch and publish new or republished XML.
- Create reviewable generated changes for newly updated legislation.

### 6. Later: Git Review Model

- Generate a review-friendly statute repository from the canonical database/object-store corpus.
- Experiment with provision-level files rather than one Markdown file per document.
- Open generated branches/PRs for newly published or revised legislation.
- Link generated diffs back to source URIs, publication events, and effects metadata.

## Open Questions

- Should v1 privilege latest revised law, as-enacted law, or both?
- How should extent-specific versions be represented when jurisdictions diverge?
- Should annotations and editorial notes be inline, sidecar metadata, or both?
- Which EU-origin, devolved, and historical types should count as the v1 corpus?
- How much normalized/generated text should live in Git versus Postgres/object storage?
