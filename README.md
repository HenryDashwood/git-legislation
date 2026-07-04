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

## Serving (Cloudflare Workers)

Python builds the corpus; TypeScript serves it. The two serving apps live under `workers/` and are deployed
on Cloudflare Workers:

- `workers/read-api` — read-only JSON API. PlanetScale Postgres via Hyperdrive, content objects from the R2
  bucket binding. Deployed at https://git-legislation-read-api.british-legislation.workers.dev
- `workers/web-app` — HTMX web frontend rendered with Hono JSX, calling the read API over a service binding.
  Deployed at https://git-legislation-web-app.british-legislation.workers.dev

Each has its own README covering local dev (`npm run dev` runs both Workers against local Postgres and a
simulated R2 bucket), tests, and deployment.

Endpoints served by the read API:

- `GET /healthz`
- `GET /corpus/summary`
- `GET /documents?legislation_type=ukpga&year=2026&number=14&status=Prospective&metadata_only=false&limit=50&offset=0`
- `GET /documents/ukpga/2026/14` (+ `/versions`, `/versions/latest`)
- `GET /versions/{version_id}/provisions`, `/files`, `/content?kind=markdown|clml_xml`
- `GET /files/{id}/content`

## Cloud Backends

Local remains the build environment; PlanetScale Postgres and Cloudflare R2 are the serving copies.

Database schema is managed with the same goose migrations:

```bash
goose -dir db/migrations postgres "$PSCALE_URL" up
```

Populate from local (uses the docker container's PG client tools; no DDL rights needed on the target):

```bash
zsh scripts/load-planetscale.sh
```

Objects: sync the local object store to R2 with rclone (idempotent; re-run to pick up deltas):

```bash
rclone sync var/object-store/legislation r2:british-legislation --transfers 16 --progress
```

`scripts/sync.sh` and `scripts/drain.sh` wrap this for bulk mirroring and for continuously moving
write-once artifacts (PDFs, parse reports) to R2 while deleting verified local copies.

To cache the PDF for a specific document into the object store:

```bash
uv run git-legislation cache-pdf aosp/1469/12 --at 2026-05-05
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
