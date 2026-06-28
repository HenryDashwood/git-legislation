# git-legislation

Represent UK legislation as structured, reproducible data.

The project currently ingests legislation.gov.uk XML into deterministic Markdown, stores XML and Markdown objects in a filesystem-backed object store, and catalogs the corpus in local Postgres. The longer-term goal is to make changes to law inspectable with ordinary software tools: stable source data, readable text diffs, reviewable imports, and a backend that can serve the corpus through an API.

## Current State

The working pipeline is:

```text
legislation.gov.uk
  -> var/object-store/... Markdown/XML objects
  -> Postgres metadata/search tables
```

Implemented pieces:

- Python CLI for object-store-native ingestion, corpus inspection, and legislation.gov.uk discovery.
- Local Postgres via Docker Compose.
- Goose migrations under `db/migrations`.
- Schema dump under `db/schema.sql`.
- Local filesystem object store under `var/object-store`.
- Postgres publishing for documents, versions, provisions, file metadata, and object metadata.
- Markdown publishing normalization for legacy CP-1252 punctuation found in some source metadata.

The current broad snapshot can be ingested for configured non-draft legislation types. Some records are full-text CLML-derived Markdown; many older or metadata-only records are Markdown stubs pointing to PDF alternatives.

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

Load `.env`, then ingest a point-in-time corpus into the local object store and Postgres:

```bash
set -a; . ./.env; set +a
uv run git-legislation ingest-point-in-time-corpus --at 2026-05-05
```

Limit to one or more legislation types:

```bash
uv run git-legislation ingest-point-in-time-corpus --at 2026-05-05 --legislation-type ukpga
```

For a smaller run, ingest a single year:

```bash
uv run git-legislation ingest-point-in-time-year ukpga 2026 --at 2026-05-05
```

Or ingest one document:

```bash
uv run git-legislation ingest-document ukpga/2026/14 --at 2026-05-05
```

The native ingestion path writes:

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

Check corpus counts across Postgres and the local object store:

```bash
uv run git-legislation corpus-counts
```

## Read API

Run the read-only FastAPI service against the local Postgres database and object store:

```bash
set -a; . ./.env; set +a
uv run git-legislation-api
```

The service defaults to `http://127.0.0.1:8000`. Set `CORS_ORIGINS` in `.env` to allow a web app origin, for example:

```bash
CORS_ORIGINS=http://localhost:5173
```

Useful v1 endpoints:

- `GET /healthz`
- `GET /documents?legislation_type=ukpga&year=2026&number=14&status=Prospective&metadata_only=false&limit=50&offset=0`
- `GET /documents/ukpga/2026/14`
- `GET /documents/ukpga/2026/14/versions`
- `GET /documents/ukpga/2026/14/versions/latest`
- `GET /versions/point-in-time:2026-05-05:ukpga/2026/14/provisions`
- `GET /versions/point-in-time:2026-05-05:ukpga/2026/14/files`
- `GET /versions/point-in-time:2026-05-05:ukpga/2026/14/content`

Metadata endpoints read from Postgres. Content endpoints resolve canonical Markdown or XML through database file records, then serve bytes from `var/object-store`.

## Web App

The HTMX web app lives in `web-app` and consumes the read API over HTTP. Run the API and web app as two local processes.

Terminal 1:

```bash
set -a; . ./.env; set +a
uv run git-legislation-api
```

Terminal 2:

```bash
API_BASE_URL=http://127.0.0.1:8000 uv run uvicorn main:app --app-dir web-app --reload --port 8001
```

Open `http://127.0.0.1:8001/documents` to browse documents, filter by legislation type, year, number, status, extent, text coverage, and title text. The document page renders parsed Markdown as readable HTML and, where available, shows the source PDF alongside it for comparison.

To cache the PDF for a specific document into the local object store:

```bash
uv run git-legislation cache-pdf aosp/1469/12 --at 2026-05-05
```

Once cached, the web app serves the PDF through the read API instead of depending on the remote source during page view.

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

### Improve Markdown Quality

- Add a Markdown quality audit command.
- Compare XML structure against Markdown output for full-text CLML records.
- Flag missing schedules, weak headings, table-heavy documents, empty bodies, and metadata-only stubs.
- Add representative snapshot tests across legislation types and eras.
- Improve handling of schedules, tables, forms, images, commentary, repeals, and prospective text.

### Handle PDF-Backed Records

- Download/cache PDF alternatives into the object store.
- Extract richer metadata from metadata-only XML.
- Evaluate PDF text extraction quality on a sample set.
- Decide how PDF-derived text should be marked, reviewed, and served.

### Extend The Read API

- Add snapshot-scoped browse routes and richer search over titles/provisions.
- Add a Cloudflare Worker or other lightweight hosted backend for read-only access.
- Add range requests or signed object access for large XML/PDF content.
- Add `sqlc` or another query-generation layer once the API query surface is stable.

### Incremental Updates

- Poll the Publication Log.
- Track the last processed publication event.
- Fetch and publish new or republished XML.
- Create reviewable generated changes for newly updated legislation.

### Later: Git Review Model

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
