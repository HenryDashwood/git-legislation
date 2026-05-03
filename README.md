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

A likely file layout:

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

The important design choice is to avoid one giant Markdown file per Act. Smaller provision-level files should create much clearer diffs when an amendment inserts, repeals, or substitutes a provision.

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

Initial import:

1. Prefer Research Legislation bulk downloads for the first corpus import.
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

### Phase 1: Source Discovery Prototype

- Download a small sample set via Atom feeds.
- Fetch CLML for representative legislation types:
  - UK Public General Act (`ukpga`);
  - UK Statutory Instrument (`uksi`);
  - Scottish Act (`asp`);
  - Welsh legislation (`asc`, `anaw`, `wsi`);
  - Northern Ireland legislation (`nia`, `nisr`).
- Catalogue CLML structures that need Markdown handling.
- Decide which metadata is required in frontmatter.

### Phase 2: CLML To Markdown Converter

- Build a deterministic converter from CLML to Markdown.
- Preserve hierarchy: Parts, Chapters, sections, schedules, paragraphs, subparagraphs.
- Normalize whitespace and line wrapping for stable diffs.
- Add snapshot tests using known legislation samples.
- Generate provision-level files rather than whole-document blobs.

### Phase 3: Corpus Fetching

The next practical milestone is to move from one Act and one year to complete fetchable corpora.

#### Phase 3a: Complete Enacted Corpus

Goal: fetch every enacted law discoverable from legislation.gov.uk up to the present date.

Output shape:

```text
output/xml/enacted/{type}/{year}/{number}/data.xml
```

Plan:

1. Keep `ukpga` as the first complete path.
2. Add a supported legislation type registry from the official URI/type documentation.
3. For each supported type, discover available documents by walking year feeds.
4. Fetch each document from `/{type}/{year}/{number}/enacted/data.xml`.
5. Treat missing XML as an expected outcome, not a crash.
6. Measure runtime, storage size, and retry behaviour before widening the corpus.

#### Phase 3b: Complete Point-In-Time Corpus

Goal: fetch the full revised statute book as it stood on a chosen date.

Output shape:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}/data.xml
```

Plan:

1. Accept an explicit snapshot date.
2. Discover all documents that existed by that date.
3. Fetch each document from `/{type}/{year}/{number}/{yyyy-mm-dd}/data.xml`.
4. Treat unavailable point-in-time XML as an expected outcome.
5. Confirm that fetching today's moving `/data.xml` output and fetching an explicit dated snapshot produce the layout we expect.

### Phase 4: Initial Markdown Corpus Import

- Use the fetched XML corpus as canonical source input.
- Convert a bounded corpus first, probably `ukpga`.
- Commit generated Markdown output.
- Measure repo size, conversion time, and diff readability.
- Decide whether large source XML files belong in Git, Git LFS, or an external cache.

### Phase 5: Incremental Updates

- Poll `https://www.legislation.gov.uk/update/data.feed`.
- Track the last processed Publication Log entry.
- Download newly published or republished XML resources.
- Regenerate affected Markdown files.
- Create import branches and commits automatically.

### Phase 5a: Expand Corpus Scope

The first working path is deliberately focused on UK Public General Acts (`ukpga`). The full corpus needs to expand across legislation.gov.uk type codes.

Likely type codes include:

- `uksi`: UK Statutory Instruments
- `ukla`: UK Local Acts
- `asp`: Acts of the Scottish Parliament
- `ssi`: Scottish Statutory Instruments
- `asc`: Acts of Senedd Cymru
- `anaw`: Acts of the National Assembly for Wales
- `wsi`: Welsh Statutory Instruments
- `nia`: Northern Ireland Acts
- `nisr`: Northern Ireland Statutory Rules
- other legislation.gov.uk types as discovered from the official URI/type documentation

Plan:

1. Finish one complete list/fetch/convert path for `ukpga`.
2. Add a supported-types registry.
3. Test one representative year feed for each type.
4. Add `list-types` and multi-type fetch commands.
5. Expand output corpus type by type.

### Phase 6: Pull Request Workflow

- Generate PR descriptions with:
  - source links;
  - affected legislation;
  - publication event timestamps;
  - summary of files changed;
  - known converter warnings.
- Add CI checks for deterministic regeneration.
- Fail CI when generated Markdown differs from committed Markdown.

### Phase 7: Effects And Audit Trail

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
- Do we store all historical points in time, only current revised text, or both?
- How should extent-specific versions be represented when England, Wales, Scotland, and Northern Ireland diverge?
- Should generated Markdown include editorial annotations inline, in sidecar files, or both?
- How much source XML should be committed versus cached?

## Current Assumption

For v1, `main` should probably represent the latest official revised text available from legislation.gov.uk, imported only from official post-Royal-Assent sources. That keeps the first version achievable while preserving the Git pull request metaphor for later, richer workflows.
