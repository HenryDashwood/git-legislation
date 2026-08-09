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

The corpus holds a broad point-in-time snapshot across all configured non-draft legislation types
(184,646 documents), plus deep revision histories for heavily amended primary legislation. Most
records carry full text (CLML-derived or PDF-derived); the residue is image-only scans queued for a
future OCR pass.

Beyond the snapshot, the corpus also carries:

- **Revision histories** — every point-in-time expression upstream offers for an act, so consecutive
  versions can be diffed. 30 pilot acts are complete; expansion to 1,591 substantive primary acts is
  in progress.
- **Amendment effects** — legislation.gov.uk's Changes to Legislation register (77,125 records),
  giving each diff an attribution: which instrument changed which provision, and when it commenced.
- **Schedules and extent variants** — schedules live in a container sibling to `Body`, and
  jurisdictionally divergent readings in a `Versions` container; both are walked, so the Scottish
  text of a provision is present and diffable separately from the English one.

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

Endpoints served by the read API (documented for users at `/api` on the web app):

- `GET /healthz`
- `GET /corpus/summary`
- `GET /documents?legislation_type=ukpga&year=2026&number=14&status=Prospective&metadata_only=false&limit=50&offset=0`
- `GET /documents/ukpga/2026/14` (+ `/versions`, `/versions/latest`, `/effects?direction=affected|affecting`)
- `GET /versions/{version_id}/provisions`, `/provisions/{anchor}`, `/files`, `/content?kind=markdown|clml_xml`
- `GET /diff?from={version_id}&to={version_id}` — provision-aligned diff with effect attributions
- `GET /changesets/{document_id}` — everything one amending instrument changed
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

Objects: upload the locally-resident trees (markdown, xml) to R2 (idempotent; re-run to pick up
deltas):

```bash
zsh scripts/sync.sh
```

`sync.sh` only ever copies. Deleting from R2 is a separate, deliberate step:

```bash
zsh scripts/prune-r2.sh            # dry run
zsh scripts/prune-r2.sh --apply    # actually delete
```

That split exists because a mirroring sync is the one command that can take production down. On
2026-07-28 the daily poll ran one just after the object store had been re-keyed to `.gz` locally
but before the serving database knew about it, so every key production was asking for was deleted
and content endpoints 404ed for five hours. `prune-r2.sh` samples keys from the serving database
and refuses to delete if they are missing locally, which is exactly that failure signature.

Never run a full-tree `rclone sync` of `var/object-store/legislation` by hand either: the drained
trees (pdf, reports, extracted-text) are deleted locally by `scripts/drain.sh` after verified
upload, so a full-tree mirror would remove them from R2.

Objects are stored gzipped where they compress (XML, Markdown, JSON), keyed with a `.gz` suffix;
the corpus went from 50.7 GB to 6.0 GB. `storage_objects.sha256` remains the hash of the
*uncompressed* content, so version identity is unaffected by the encoding, and the read API
decompresses on the way out so consumers see plain text.

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

Two data axes: **depth** (many textual states per document, diffable) and **breadth** (more sources,
and the graph of effects and powers linking them). A product surface — search, browse, diff, API —
rides along both rather than competing with them.

Phases 1 and 2 are complete. What follows is what is left.

### Built so far

- **Live corpus.** Trustworthy version identity (`canonical_sha256`, so re-fetching an unchanged
  document is free), Publication Log polling, and a daily launchd job that ingests, dates, uploads
  and delta-syncs.
- **Diffs.** Provision-level alignment by type, number and extent; word-level rendering; a compare
  form and per-version links on every document page.
- **Amendment effects.** 77,125 records from the Changes to Legislation register, attached to diff
  cards confirmation-first — an effect is pinned to a provision only where that provision
  demonstrably changed. `verify-effects` reports 91% confirmed across the pilot acts.
- **Changesets.** One amending instrument across every document it touched.
- **Faithful text.** Schedules (previously absent entirely), extent-divergent readings, and
  exclusion of provisions not in force at a snapshot's date.
- **Efficient storage.** Provision text is content-addressed (6.9 GB → 2.9 GB) and objects are
  gzipped (50.7 GB → 6.0 GB).

### Now — expanding the backfill

The gate passed on 2026-07-28, so the version backfill is expanding from 30 pilot acts to 1,591
substantive primary acts (`scripts/backfill-acts.txt`, ~57,000 versions).

**Throughput is the blocker, and it is network-bound.** Profiled on a large act: fetch 8.5s,
render 0.3s, parse 0.14s, write 1.5s. Measured throughput is ~136 versions/hour sequential, which
puts the full set at ~17 days. Concurrency is therefore the lever that matters:

| | sequential | 4 concurrent | 8 concurrent |
|---|---|---|---|
| 57,000 versions | 17.5 days | 4.4 days | 2.2 days |

- **Parallelise the fetch client**, which is strictly sequential today. Needs care around the
  429/432 rate-limit handling, which has never been tested under load.
- **Prioritise.** Value is concentrated in the first few hundred acts. Sampling the timeline (one
  expression per year) would cut volume 5–10× at the cost of not being able to diff two amendments
  made in the same year.
- ~~Move it off the laptop~~ Provisioned: `scripts/hetzner/` holds cloud-init and a supervised
  systemd service for a small Hetzner box. It writes rows straight to the serving database and
  copies objects to R2 hourly, so there is no local Postgres and no sync step.

### Next — text quality

The pilot found three converter defects by asking why recorded amendments produced no textual
change. That method is not exhausted; each fix moved effect confirmation (77% → 88% → 91%), and
the residual is a queue of known gaps:

- **Sub-provision precision.** An effect on "Sch. 5 para. 3" attaches to the whole of Schedule 5,
  and one on "s. 24(3)" to the whole of section 24. Finer alignment would sharpen attribution.
- **Tables, forms, images.** Rendered poorly or not at all.
- **A Markdown quality audit command** — compare XML structure against Markdown output and flag
  missing schedules, weak headings, table-heavy documents, empty bodies.
- **Snapshot tests** across legislation types and eras, so converter changes have a safety net.
- **Characterise the remaining 9%** of unconfirmed effects. Some is upstream disagreement between
  the register and the revised text (legislation.gov.uk flags these as `UnappliedEffect`); the rest
  is unexplained.

### Next — text coverage

- Refetch as-made/enacted XML for metadata-only records where `NumberOfProvisions > 0` upstream.
- Run Marker on a GPU machine over the image-only PDF backlog (pre-Victorian acts, NI SR&Os); the
  reader already prefers `markdown/marker/` objects.
- Fold legal-date extraction into the publish pipeline, so `extract-legal-dates` need not be
  re-run after ingestion.
- Decide whether PDF-derived text should feed versions and search, or stay display-only.

### Later — graph and breadth

An effect record is simultaneously the commit message for a diff and an edge in a power graph;
enabling-powers relationships (which parent Act an SI was made under) are the other core edge type.

- Expose effects and enabling powers as graph resources, not just annotations.
- Join them to external government graphs (organisations, ministers, powers) rather than ingesting
  those as new corpora.
- Only then take on genuinely new corpora (local government, regulators' rules) — each multiplies
  every pipeline problem, and the payoff mostly arrives after the link layer exists.

### Later — git repository rendering

A git repo is a *rendering* generated from the canonical corpus, not a storage strategy.

- Generate a review-friendly statute repository from the corpus.
- Try provision-level files rather than one Markdown file per document.
- Open generated branches/PRs for newly published or revised legislation.
- Link generated diffs back to source URIs, publication events, and effects.

### Operations

- ~~Run the daily poll off the laptop~~ Provisioned: `.github/workflows/poll.yml` runs it on
  GitHub Actions at 06:30 UTC, writing through `DB_URL` straight to the serving database and
  copying objects to R2. Gated on `.github/workflows/probe-egress.yml` confirming that
  legislation.gov.uk serves a datacentre IP — its dynamic PDF generator refuses Cloudflare egress,
  so this is not a given.
- **Refresh effects incrementally.** `effects_cursor` records each document's last-modified
  watermark, but nothing consumes it yet — effects are only ever fully re-ingested.
- **Compress the drained trees.** `extracted-text/` and `reports/` are compressible but live only
  in R2, so the local compression pass could not reach them.
- **`export-sample`** — a small representative local fixture (rows + objects) so the repo can be
  worked on without the full corpus.
- **Typed query generation** (`sqlc`-style) in the Worker once the query surface settles.

## Open Questions

- Should v1 privilege latest revised law, as-enacted law, or both?
- Should annotations and editorial notes be inline, sidecar metadata, or both?
- Which EU-origin, devolved, and historical types should count as the v1 corpus?
- How much normalized/generated text should live in Git versus Postgres/object storage?
- How deep should revision histories go? Every expression upstream offers is faithful but slow to
  fetch and largely redundant; one per year is far cheaper but cannot separate two amendments made
  in the same year.
- What should happen when the amendment register and the revised text disagree? Today the effect is
  shown but not pinned to any words. It could also be surfaced as a data-quality signal in its own
  right — a list of amendments the official text has not yet caught up with.

Answered along the way:

- ~~How should extent-specific versions be represented when jurisdictions diverge?~~ As separate
  provisions carrying `provisions.extent`, parsed from a marker the converter appends to the
  heading of an alternative reading ("## 33 Prohibition ... (S)"). Diff alignment keys on extent so
  readings never cross-match; effects attach by number and kind, landing on whichever reading
  actually changed.
