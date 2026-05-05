# git-legislation

Represent the UK statute book as a Git repository: legislation text is stored as deterministic Markdown, and newly enacted or amended law appears as readable diffs.

## Goal

The long-term idea is to make legal change inspectable using normal software review tools:

- the current statute book lives on `main`;
- newly enacted legislation is imported on branches;
- the resulting Markdown changes are reviewed as pull requests;
- merging a pull request represents incorporating that enacted change into the repository view of UK law.

For v1, we will start at Royal Assent. Bills, parliamentary amendment papers, and “proposed law” patch generation are deliberately out of scope for the first version.

## What we learnt

legislation.gov.uk is usable as an API, not just a website. The public pages have structured representations behind them, and the official documentation encourages API and bulk use.

Useful sources:

- Data reuse docs: https://legislation.github.io/data-documentation/
- API overview: https://legislation.github.io/data-documentation/api/overview.html
- Formats: https://legislation.github.io/data-documentation/formats/overview.html
- Search, lists, and feeds: https://legislation.github.io/data-documentation/api/search.html
- Publication Log: https://legislation.github.io/data-documentation/api/publication-log.html
- URI scheme and legislation type codes: https://legislation.github.io/data-documentation/model/uris.html
- Research bulk downloads: https://research.legislation.gov.uk/data

Key findings:

- Legislation content is available as CLML XML via `.../data.xml`.
- Alternative formats include Akoma Ntoso XML, HTML, HTML5, PDF, and Atom feeds.
- CLML is the best canonical source for conversion because it contains the richest UK-specific semantic structure.
- Search and list pages are available as Atom feeds by appending `/data.feed`.
- Bulk downloads exist through Research Legislation, including CLML, HTML5, plaintext, AKN, and XHTML datasets.
- The Publication Log at `https://www.legislation.gov.uk/update/data.feed` tracks publication, republication, withdrawal, revised points in time, associated documents, and effects.
- Changes to legislation are exposed as “effects” feeds. These record affected legislation, affecting legislation, provisions, effect type, in-force dates, extent, and whether the effect has been applied.
- The dataset is broad but not literally every UK law ever made. The docs say legislation.gov.uk publishes UK legislation from 1267 onwards and selected EU-origin legislation, while also noting that it does not record or publish all UK legislation.

## Current State

The repository now has a working Python CLI for the first end-to-end corpus path:

1. Discover documents from legislation.gov.uk year feeds.
2. Fetch current `data.xml` resources for configured legislation types into dated snapshot folders.
3. Resume idempotently by skipping valid XML files that already exist.
4. Reject bad successful responses, such as HTML “Multiple Choices” pages saved as `.xml`.
5. Record fetch reports, fetch failures, and fallback probes.
6. Back off and retry HTTP `429` rate-limit responses before carrying on.
7. Convert fetched CLML XML into Markdown.
8. Convert metadata-only XML into Markdown stubs with PDF links, rather than treating those records as total failures.
9. Continue after conversion failures and write conversion reports.

The current working corpus path is:

```bash
uv run git-legislation fetch-point-in-time-corpus
uv run git-legislation convert-point-in-time-corpus --at YYYY-MM-DD
```

If no type is passed, the fetcher now fetches every supported type. Use `--legislation-type` to limit a run to one or more types:

```bash
uv run git-legislation fetch-point-in-time-corpus --legislation-type ukla
uv run git-legislation fetch-point-in-time-corpus --legislation-type ukpga --legislation-type asp --legislation-type uksi
```

Default output is under:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/
output/markdown/point-in-time/{yyyy-mm-dd}/{type}/
output/reports/fetch/point-in-time/{yyyy-mm-dd}.json
output/reports/convert/point-in-time/{yyyy-mm-dd}/{type}.json
```

This is not yet “every UK law in Markdown”. The most validated path is currently the current-date `ukpga` corpus, with full Markdown where CLML body text exists and metadata stubs where the source only exposes metadata and PDF alternatives. The fetcher now knows the official non-draft legislation.gov.uk type codes in scope for the project, but those types still need coverage audits and converter hardening.

## V1 Scope

V1 should answer one practical question:

> When an Act receives Royal Assent and appears on legislation.gov.uk, can we import it and represent the resulting statute-book change as readable Git diffs?

In scope:

- Use legislation.gov.uk and Research Legislation as source data.
- Import enacted legislation after Royal Assent.
- Convert CLML XML into stable Markdown.
- Track current legislation state in Git.
- Use branches and pull requests to review changes before merge.
- Monitor official feeds for newly published or republished legislation.
- Store enough metadata to trace every Markdown file back to its official source URI.

Out of scope for v1:

- Parsing Bills before Royal Assent.
- Generating proposed patches from parliamentary amendment instructions.
- Treating an MP vote as the merge event.
- Guaranteeing coverage of PDF-only historical material.
- Building a legal research UI.

## Repository Model

The current prototype writes generated source XML, Markdown, and reports under `output/`:

```text
output/
  xml/
    point-in-time/
      2026-05-04/
        ukpga/
          2026/
            14/
              data.xml
          Geo3/
            41/
              52/
                data.xml
  markdown/
    point-in-time/
      2026-05-04/
        ukpga/
          2026/
            14.md
          Geo3/
            41/
              52.md
  reports/
    fetch/
    convert/
```

The long-term generated legislation repository may use a more review-friendly provision-level layout:

```text
legislation/
  ukpga/
    2026/
      14/
        metadata.yml
        source/
          point-in-time/
            2026-05-03.xml
        point-in-time/
          2026-05-03/
            introduction.md
            section-1.md
            section-2.md
            schedule-1.md
        enacted/
          introduction.md
          section-1.md
          section-2.md
```

The current converter still emits one Markdown file per document. The likely next design choice is to avoid one giant Markdown file per Act in the committed statute repository. Smaller provision-level files should create much clearer diffs when an amendment inserts, repeals, or substitutes a provision.

Each Markdown file should be deterministic:

- stable heading format;
- stable paragraph wrapping;
- one numbered paragraph or subparagraph per line where possible;
- source URI in frontmatter;
- legislation type, year, number, snapshot date, extent, language, and source timestamp in metadata;
- annotations and editorial notes represented consistently.

Example frontmatter:

```yaml
---
source_uri: "https://www.legislation.gov.uk/ukpga/2026/14/section/1/data.xml"
document_uri: "https://www.legislation.gov.uk/ukpga/2026/14"
type: "ukpga"
year: 2026
number: 14
snapshot_date: "2026-05-03"
extent: null
language: "en"
generated_from: "clml"
---
```

## Import Strategy

Current prototype import:

1. Use legislation.gov.uk year feeds to discover `ukpga` documents.
2. Fetch current `data.xml` resources into a dated point-in-time snapshot.
3. Use CLML XML where available.
4. Record metadata-only/PDF-linked items as Markdown stubs.
5. Record HTML ambiguity pages, empty responses, and source gaps in fetch reports.

Likely production initial import:

1. Use Research Legislation bulk downloads for the first broad corpus import.
2. Use CLML where available.
3. Fall back to plaintext for exploration only, not as the canonical long-term source.
4. Record PDF-only items as metadata stubs until a PDF extraction strategy exists.

Incremental import:

1. Poll the Publication Log.
2. Filter for `ContentType=legislation` and `Format=xml`.
3. Download the published `data.xml` resource.
4. Convert CLML to Markdown.
5. Create a branch named from the publication event or legislation identifier.
6. Commit the generated changes with source metadata.
7. Open a pull request for review.
8. Merge once the generated diff is accepted.

Effects import:

1. Store effects data separately from generated Markdown text.
2. Use effects as audit metadata for why provisions changed.
3. Do not rely on effects alone to rewrite Markdown in v1; use the official revised CLML text as the source of truth.

## Branch And Pull Request Model

For v1:

```text
main
  Current repository view of enacted/revised law.

import/ukpga-2026-14
  Generated changes from a newly published Act or revised XML resource.

PR
  Human-readable review of the Markdown changes, linked back to legislation.gov.uk source URIs.
```

Commit messages should include:

- legislation title;
- type/year/number;
- source `data.xml` URI;
- Publication Log entry URI when available;
- generated converter version.

## Roadmap

See [CLI](CLI.md) for current command usage.

See also [Repo Structure And Tech Stack](docs/repo-structure-and-tech-stack.md) for the proposed Python CLI architecture, generated legislation layout, storage approach, and testing strategy.

### Done: Source Discovery And `ukpga` Prototype

- Fetch targeted documents and year feeds from legislation.gov.uk.
- Fetch current `ukpga` corpus snapshots into dated output folders.
- Preserve regnal-year source paths such as `ukpga/Geo3/41/52`.
- Write fetch reports with successes, failures, probes, and fallback classifications.
- Make corpus fetching idempotent for valid local XML.
- Reject HTML and malformed responses instead of writing them as XML.
- Add timeout/retry behavior for transient network errors.
- Convert a current `ukpga` snapshot to Markdown with conversion reports.
- Convert metadata-only XML into Markdown stubs with PDF links.

### Done: Coverage Audit

- Add a report summary command for fetch and conversion reports.
- Count expected feed entries versus valid XML files versus Markdown files.
- Separate expected source limitations from true tool failures.
- Track metadata-only documents and PDF alternatives as first-class coverage categories.
- Detect empty, malformed, or HTML local files and offer a cleanup command.
- Print detailed fetch and conversion failures for a snapshot.

### In Progress: Expand Beyond `ukpga`

Goal: generalize the corpus pipeline across legislation.gov.uk type codes.

Configured non-draft corpus types:

- pre-UK and historical primary types: `aep`, `aosp`, `aip`, `apgb`, `gbppa`, `gbla`
- UK Parliament primary types: `ukpga`, `ukla`, `ukppa`
- devolved and Northern Ireland primary types: `asp`, `mwa`, `anaw`, `asc`, `apni`, `mnia`, `nia`
- secondary types: `uksi`, `ssi`, `wsi`, `nisr`, `nisro`, `nisi`, `ukcm`, `ukci`, `ukmo`
- draft legislation types remain out of the default corpus because they are not enacted or made law
- closed historical series have configured end years, so the fetcher does not probe irrelevant modern years

Plan:

1. Test representative year feeds for each configured type.
2. Add CLI options to convert, audit, clean, and inspect one type, selected types, or all supported types.
3. Keep per-type conversion reports and decide whether fetch reports should split by type as the corpus widens.
4. Expand output corpus type by type, starting with the highest-value types.

### Next: PDF-Only And Non-CLML Sources

Goal: make records useful when legislation.gov.uk does not expose full CLML body text.

1. Keep metadata stubs for PDF-only or metadata-only records.
2. Extract richer metadata from `ukm:Metadata`, `ukm:PrimaryMetadata`, and `ukm:SecondaryMetadata`, including:
   - document category, main type, and status;
   - year and number;
   - made date, laid date, coming-into-force date, and other lifecycle dates where present;
   - subjects, publisher, modified date, source URI, and original identifier;
   - PDF alternative URL, size, print flag, and alternative date.
3. Store discovered PDF alternative URLs and extracted metadata in reports and Markdown frontmatter.
4. Add a PDF download/cache command.
5. Evaluate PDF text extraction quality on representative historical documents.
6. Decide whether extracted PDF text belongs in generated Markdown, sidecar files, or a separate review queue.
7. Track provenance clearly so generated CLML Markdown, metadata-only stubs, and PDF-extracted Markdown are distinguishable.

### Next: Better CLML To Markdown

Goal: improve Markdown quality and diff readability.

1. Preserve hierarchy: Parts, Chapters, sections, schedules, paragraphs, subparagraphs.
2. Normalize whitespace and line wrapping for stable diffs.
3. Expand handling for schedules, tables, images, forms, attachments, commentary, modifications, repeals, and prospective text.
4. Add snapshot tests using known legislation samples from multiple types and eras.
5. Generate provision-level files rather than whole-document blobs for the committed legislation repository.
6. Make conversion idempotent so unchanged Markdown is not rewritten unnecessarily.

### Next: Bulk Initial Corpus

Goal: import the initial corpus from Research Legislation bulk downloads, using CLML as the canonical source where available.

Output shape:

```text
output/xml/enacted/{type}/{year}/{number}/data.xml
output/xml/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}/data.xml
```

Plan:

1. Identify the relevant Research Legislation bulk datasets.
2. Download a small CLML bulk sample first.
3. Unpack it into the same output layout used by the API fetcher.
4. Preserve enough source metadata to trace files back to the bulk dataset and official legislation URI.
5. Measure runtime, storage size, and directory shape before widening the corpus.
6. Record missing/PDF-only/non-CLML items as expected coverage gaps rather than command failures.

### Next: API Fetching For Updates

Goal: keep the legislation.gov.uk API fetcher for targeted exploration, retries, and incremental update workflows.

Output shape:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}/data.xml
```

Plan:

1. Keep current snapshot fetching as the main current-law API path.
2. Keep explicit historical `--at` fetching as an exploratory path, not a completeness guarantee.
3. Fetch targeted documents from `/{type}/{year}/{number}/data.xml` and source-path URLs.
4. Treat unavailable point-in-time XML as an expected outcome.
5. Reuse this path later when the Publication Log says a document was published or republished.

### Later: Initial Markdown Corpus Import

- Use the fetched XML corpus as canonical source input.
- Convert a bounded corpus first, probably `ukpga` plus `uksi`.
- Commit generated Markdown output.
- Measure repo size, conversion time, and diff readability.
- Decide whether large source XML files belong in Git, Git LFS, or an external cache.

### Later: Incremental Updates

- Poll `https://www.legislation.gov.uk/update/data.feed`.
- Track the last processed Publication Log entry.
- Download newly published or republished XML resources.
- Regenerate affected Markdown files.
- Create import branches and commits automatically.

### Later: Pull Request Workflow

- Generate PR descriptions with:
  - source links;
  - affected legislation;
  - publication event timestamps;
  - summary of files changed;
  - known converter warnings.
- Add CI checks for deterministic regeneration.
- Fail CI when generated Markdown differs from committed Markdown.

### Later: Effects And Audit Trail

- Import changes/effects feeds.
- Store effects as structured metadata.
- Link Markdown diffs to official effect records where possible.
- Show whether an amendment was applied, prospective, repealed, substituted, inserted, or otherwise noted.

### Later Roadmap: Bills As Proposed Pull Requests

Once v1 works for legislation after Royal Assent, we can explore Bills as proposed patches:

- ingest Bill text from Parliament sources;
- parse amendment instructions;
- generate best-effort changes against the current statute tree;
- update the branch as the Bill changes through parliamentary stages;
- reconcile the branch against the official Act after Royal Assent.

This is harder because Bills often describe legal edits procedurally rather than containing the final consolidated statute text.

## Open Questions

- Should `main` mean “latest revised law” or “law as enacted”?
- Should commencement determine when a change lands on `main`, or should Royal Assent be enough for v1?
- Do we store all historical points in time, only current revised text, or both? Current evidence suggests “complete law as it stands today” is much easier than “complete law at arbitrary historical dates”.
- How should extent-specific versions be represented when England, Wales, Scotland, and Northern Ireland diverge?
- Should generated Markdown include editorial annotations inline, in sidecar files, or both?
- How much source XML should be committed versus cached?
- Which legislation types are in scope for “UK law” in v1, especially EU-origin and devolved legislation?
- How should PDF-extracted text be marked, reviewed, and updated?
- Should metadata-only stubs be committed beside full-text Markdown, or separated into a coverage index?

## Current Assumption

For v1, `main` should probably represent the latest official revised text available from legislation.gov.uk, imported only from official post-Royal-Assent sources. That keeps the first version achievable while preserving the Git pull request metaphor for later, richer workflows.
