# git-legislation

Represent UK legislation as structured, reproducible data.

The project currently ingests legislation.gov.uk XML into deterministic Markdown, stores XML and Markdown objects in a filesystem-backed object store, and catalogs the corpus in local Postgres. The longer-term goal is to make changes to law inspectable with ordinary software tools: stable source data, readable text diffs, reviewable imports, and a backend that can serve the corpus through an API.

## Current State

The working pipeline is:

```text
legislation.gov.uk
  -> var/object-store/... Markdown/XML/PDF/extracted-text objects  (local build side)
  -> local Postgres metadata/search tables
  -> rclone sync/drain to Cloudflare R2 + data load to PlanetScale  (serving side)
  -> Cloudflare Workers (read API + web app)
```

Implemented pieces:

- Python CLI for object-store-native ingestion, corpus inspection, PDF caching/parsing, and
  legislation.gov.uk discovery. Python builds the corpus; TypeScript Workers serve it.
- Local Postgres via Docker Compose; PlanetScale Postgres as the serving database.
- Goose migrations under `db/migrations`; schema dump under `db/schema.sql`.
- Filesystem object store under `var/object-store`, mirrored key-for-key to an R2 bucket.
- Postgres publishing for documents, versions, provisions, file metadata, and object metadata.
- LiteParse PDF-to-text extraction for records with no digitised XML, served as
  non-canonical Markdown alongside the source PDF.
- Deployed read API and web app on Cloudflare Workers (see Serving below).

The corpus holds a broad point-in-time snapshot across all configured non-draft legislation types.
Most records carry full text (CLML-derived or PDF-derived); the residue is image-only scans queued
for a future OCR pass.

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

Objects: sync the locally-resident trees (markdown, xml) to R2 (idempotent; re-run to pick up deltas):

```bash
zsh scripts/sync.sh
```

Never run a full-tree `rclone sync` of `var/object-store/legislation`: the drained trees (pdf,
reports, extracted-text) are deleted locally by `scripts/drain.sh` after verified upload, and a
full-tree sync would mirror those deletions into R2. `sync.sh` limits itself to the resident
trees; `drain.sh` moves write-once artifacts to R2 and deletes the verified local copies.

To cache the PDF for a specific document into the object store:

```bash
uv run git-legislation cache-pdf aosp/1469/12 --at 2026-05-05
```

## Data Model

The core distinction is:

- `effects`: amendment records — which instrument changed which provision of which document, its
  type, in-force date, and whether the revised text already reflects it. `effect_provisions` holds
  the per-provision references on each side (affected, affecting, commencing).
- `documents`: stable abstract legislation identities, such as `ukpga/2026/14`.
- `document_versions`: concrete textual states, such as enacted or point-in-time versions.
- `provisions`: extracted browse/search units from generated Markdown.
- `storage_objects`: object-store entries for Markdown, XML, and later PDFs or extracted text.
- `document_files`: links between documents, versions, source URLs, and stored objects.

The local filesystem object store mirrors the Cloudflare R2 bucket key-for-key: local is the build-side working copy, R2 is the serving copy, and rclone moves objects between them without changing the database model.

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
- Effects feeds are first-class metadata (the `effects` table), but must not be used alone to rewrite
  text: they say a provision changed, not what the new words are. Their editorial record includes
  machine-extracted and editor-rejected entries, and some effects carry an empty type (stored as
  `textual_kind = 'UN'`) or reference legislation not published on the site (null
  `affected_document_id`).

## Roadmap

The project has two data axes — **depth** (multiple textual states per document over time, diffable)
and **breadth** (more sources, and the graph of effects and powers linking them) — plus a product
surface (search, browse, API) that rides along every phase rather than competing with them. The
sequencing below follows the dependencies: version identity must be trustworthy before diffs mean
anything, diffs must prove their value on a pilot before a full historical backfill, and the
effects/powers layer is the hinge that turns diffs into a power graph.

### Phase 1 — Live Corpus

Goal: a weekly run produces only real changes. This is the foundation of everything downstream.

- ~~**Normalise dated URIs out of version content hashes**~~ Done: version identity now uses
  `canonical_sha256` (a hash of the Markdown with request-date segments stripped from
  legislation.gov.uk URIs), so re-fetching an unchanged document under a new `--at` reuses the
  existing version. `normalize-version-hashes` backfills the canonical hash from stored Markdown
  and merges historical duplicate versions; run it once per database copy after migrating.
- ~~Poll the Publication Log~~ Done: `poll-publication-log` walks each day's XML legislation
  publication events since the date stored in `publication_log_cursor` (in whichever database
  `DB_URL` targets, so the command can run from any host) and re-ingests every affected document
  at today's snapshot date; canonical-hash identity makes overlapping polls free. `scripts/poll.sh`
  wraps it for the local Mac (poll, extract legal dates, sync R2, delta-sync PlanetScale) and runs
  daily at 07:30 via launchd (`com.henrydashwood.git-legislation.poll`, logs to `var/log/poll.log`).
  `scripts/catch-up.sh` remains as a belt-and-braces full re-enumeration of the current year.
- Finish the text-coverage backlog:
  - Refetch as-made/enacted XML (the shell's `rel="self"` URL) for remaining metadata-only records
    where `NumberOfProvisions > 0` upstream.
  - Run Marker on a GPU machine over the image-only PDF backlog (pre-Victorian acts, NI SR&Os) to
    replace the LiteParse first-pass text; the reader already prefers `markdown/marker/` objects.
  - Extract richer metadata from metadata-only XML.
  - Fold legal-date extraction into the publish pipeline so newly ingested documents are dated
    automatically (today `extract-legal-dates` must be re-run after ingestion; it is idempotent).
  - Decide whether PDF-derived text should feed versions/search or remain display-only.

### Phase 2 — Diff Pilot (decision gate)

Goal: prove the diff experience beats legislation.gov.uk's before paying for a full historical
backfill. Point-in-time versions exist upstream mainly for revised legislation (deep for primary
legislation, thin for most secondary), so historic coverage is patchy by construction — pilot first.

- ~~Backfill all available point-in-time versions for ~30 heavily amended acts~~ Done:
  `backfill-document-versions --from-file scripts/pilot-acts.txt` reads each document's
  `dct:hasVersion` links and ingests every dated expression with `snapshot_date` set to its
  validity-start date. The pilot set holds ~3,800 versions (Town and Country Planning Act 1990: 304).
- ~~Provision-level diff rendering in the web app~~ Done: read API `GET /diff?from=&to=` aligns
  provisions by type + number and classifies each as added/removed/changed/unchanged; the web app
  renders word-level `del`/`ins` marks, with a compare form and per-version "changes from previous"
  links on every document page. Comparison is whitespace-insensitive, because upstream serves the
  same CLML both compact and pretty-printed.
- ~~Attach effects records as annotations~~ Ingestion done: `ingest-effects` reads the Changes to
  Legislation feeds (`/changes/{affected,affecting}/{path}/data.feed`) into `effects` +
  `effect_provisions`, keyed on the upstream `EffectId` and idempotent on re-run. Each record carries
  the effect type, the affecting instrument and provision, in-force date, commencement authority, and
  the `Applied` flag saying whether the revised text already reflects it. `effects-coverage` reports
  how many effects resolve to a local provision. Still to do: surface them on diff cards and build
  the changeset view.
- Changesets, not timelines: render one amending instrument as a single changeset touching many
  documents — the genuinely novel view nobody else offers. `ingest-effects --direction affecting`
  already collects the data for this.
- Markdown quality work, since a noisy converter means noisy diffs:
  - Add a Markdown quality audit command; compare XML structure against Markdown output for
    full-text CLML records; flag missing schedules, weak headings, table-heavy documents, and
    empty bodies.
  - Add representative snapshot tests across legislation types and eras.
  - ~~Improve handling of schedules~~ Done for extraction: CLML keeps schedules in a `Schedules`
    container sibling to `Body`, so the converter previously dropped them entirely — the corpus held
    2.2M `section` provisions and zero `schedule` provisions. `document_sections_from_root` now walks
    both, emitting one provision per schedule (the unit effects reference) with its parts and
    paragraphs as `###` sub-headings. Still to do: tables, forms, images, and sub-paragraph precision
    within a schedule.
  - Improve handling of tables, forms, images, commentary, repeals, and prospective text.
  - After converter improvements, run `rerender-markdown` to re-render metadata-only stubs from
    stored XML.

Gate: if the pilot experience clearly beats legislation.gov.uk, expand the version backfill; if
not, stop having spent weeks, not a re-architecture.

### Contingent on the pilot: Git Repository Rendering

The git repo is a *rendering* generated from the canonical database/object-store corpus, not a
storage strategy.

- Generate a review-friendly statute repository from the canonical corpus.
- Experiment with provision-level files rather than one Markdown file per document.
- Open generated branches/PRs for newly published or revised legislation.
- Link generated diffs back to source URIs, publication events, and effects metadata.

### Phase 3 — Graph and Breadth

An effect record ("SI X amends Act Y s.2(3), commenced date D") is simultaneously the commit
message for a diff and an edge in a power graph; enabling-powers relationships (which parent act an
SI was made under) are the other core edge type. Effects and powers are therefore first-class data,
not audit metadata.

- Store effects and enabling-powers relationships as first-class edges with API resources.
- Join those edges to external government graphs (organisations, ministers, powers) rather than
  ingesting them as new corpora.
- Only then take on genuinely new corpora (local government, regulators' rules) — each one
  multiplies every pipeline problem, and the payoff mostly arrives after the link layer exists.

### Cross-cutting: Product Surface and Operations

- Phase 1: snapshot-scoped browse routes and richer search over titles/provisions.
- Phase 2: version and diff endpoints.
- Phase 3: graph endpoints.
- Add `sqlc`-style typed query generation to the Worker once the query surface is stable.
- Add an `export-sample` command producing a small representative local fixture (rows + objects),
  then prune local trees to the sample.

## Open Questions

- Should v1 privilege latest revised law, as-enacted law, or both?
- How should extent-specific versions be represented when jurisdictions diverge?
- Should annotations and editorial notes be inline, sidecar metadata, or both?
- Which EU-origin, devolved, and historical types should count as the v1 corpus?
- How much normalized/generated text should live in Git versus Postgres/object storage?
