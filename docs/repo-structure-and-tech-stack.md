# Repo Structure And Tech Stack

This project has two different kinds of content:

1. source code that imports, normalizes, converts, and checks legislation data;
2. generated legislation output that is reviewed through Git diffs.

The repo should keep those concerns separate. Generated legislation files should be treated like build artifacts with strong provenance, even when they are committed.

## Recommended Tech Stack

### Language

Use Python for v1.

Reasons:

- strong XML support in the standard library and `lxml`;
- mature CLI, testing, and packaging ecosystem;
- good streaming support for large XML inputs;
- easy scripting for bulk import jobs;
- low barrier for future legal/research contributors.

Avoid making v1 a TypeScript app unless we need a web UI early. The core problem is batch ingestion, XML normalization, deterministic text generation, and filesystem output. Python is a better first fit.

### Package And Environment Management

Use `uv`.

Recommended files:

```text
pyproject.toml
uv.lock
.python-version
```

Recommended Python version: `3.13` or newer.

### Core Libraries

- `lxml`: parse CLML XML, preserve namespaces, support XPath.
- `httpx`: API and feed downloads.
- `feedparser` or `lxml`: Atom feed parsing. Prefer `lxml` if the feed handling stays simple.
- `pydantic`: typed metadata models and validation.
- `pyyaml` or `ruamel.yaml`: frontmatter and manifest output.
- `typer`: command-line interface.
- `rich`: readable CLI logging and progress.
- `pytest`: tests.
- `ruff`: linting and formatting.
- `ty`: type checking once models settle.

### Storage Format

Use Markdown for human-readable legislation text and YAML for metadata.

Use XML as the canonical source input, not Markdown. Markdown is the review format. CLML remains the authoritative machine-readable source for regeneration.

For large source XML:

- v1 prototype: commit small sample XML fixtures only.
- full corpus: store source XML in an external cache or object store unless there is a strong reason to put it in Git LFS.
- always commit enough metadata to refetch the official source.

## Proposed Repository Layout

```text
git-legislation/
  README.md
  pyproject.toml
  uv.lock
  .python-version
  .gitignore

  docs/
    repo-structure-and-tech-stack.md
    clml-to-markdown.md
    data-sources.md
    decisions/

  src/
    git_legislation/
      __init__.py
      cli.py

      sources/
        legislation_gov_uk.py
        publication_log.py
        bulk_downloads.py

      clml/
        parser.py
        model.py
        namespaces.py
        traversal.py

      markdown/
        renderer.py
        frontmatter.py
        paths.py
        normalize.py

      pipeline/
        import_document.py
        import_feed.py
        regenerate.py
        diff_summary.py

      effects/
        parser.py
        model.py

      storage/
        manifest.py
        cache.py
        repo.py

  tests/
    fixtures/
      clml/
      feeds/
    snapshot/
    test_clml_parser.py
    test_markdown_renderer.py
    test_paths.py

  legislation/
    README.md
    ukpga/
    uksi/
    asp/
    ssi/
    asc/
    anaw/
    wsi/
    nia/
    nisr/

  data/
    manifests/
    publication-log/
    effects/

  var/
    cache/
    downloads/
```

### What Belongs In Git

Commit:

- source code;
- tests and small fixtures;
- generated Markdown legislation output;
- generated metadata manifests;
- documentation;
- deterministic snapshots used by tests.

Do not commit by default:

- full bulk download archives;
- full source XML corpus;
- temporary extraction directories;
- HTTP cache;
- local run state.

`var/` should usually be ignored.

## Generated Legislation Layout

Use legislation type, year, and number as the stable root:

```text
legislation/
  ukpga/
    2026/
      14/
        document.yml
        versions.yml
        current/
          index.md
          section-1.md
          section-2.md
          schedule-1.md
        enacted/
          index.md
          section-1.md
          section-2.md
```

### `document.yml`

Document-level metadata:

```yaml
source_uri: "https://www.legislation.gov.uk/ukpga/2026/14"
type: "ukpga"
year: 2026
number: 14
title: "Example Act 2026"
language: "en"
canonical_format: "clml"
last_imported_at: "2026-05-02T12:00:00Z"
```

### `versions.yml`

Known versions and points in time:

```yaml
versions:
  enacted:
    source_uri: "https://www.legislation.gov.uk/ukpga/2026/14/enacted/data.xml"
  current:
    source_uri: "https://www.legislation.gov.uk/ukpga/2026/14/data.xml"
  "2026-07-01":
    source_uri: "https://www.legislation.gov.uk/ukpga/2026/14/2026-07-01/data.xml"
```

### Provision Files

Provision files should have frontmatter plus Markdown body:

```markdown
---
source_uri: "https://www.legislation.gov.uk/ukpga/2026/14/section/1/data.xml"
document_uri: "https://www.legislation.gov.uk/ukpga/2026/14"
type: "ukpga"
year: 2026
number: 14
version: "current"
provision: "section-1"
generated_from: "clml"
---

# 1 Title of section

(1) First numbered subsection.

(2) Second numbered subsection.
```

## Deterministic Markdown Rules

The Markdown renderer should be deliberately boring.

Rules:

- one provision per file;
- one numbered paragraph or subparagraph per line where possible;
- no line wrapping based on terminal width;
- stable blank lines between structural blocks;
- stable heading levels based on legislation hierarchy;
- preserve original numbering exactly;
- normalize whitespace but do not rewrite legal text;
- represent repealed or prospective text consistently;
- put annotations in predictable sidecar sections or sidecar files.

Good diffs depend more on determinism than beautiful prose formatting.

## CLI Shape

Use a single CLI entry point:

```text
git-legislation discover
git-legislation fetch-document ukpga 2026 14
git-legislation convert var/cache/ukpga/2026/14/current.xml
git-legislation import-document ukpga 2026 14
git-legislation import-feed --since 2026-05-01
git-legislation regenerate legislation/ukpga/2026/14
git-legislation diff-summary
```

V1 command priorities:

1. `fetch-document`
2. `convert`
3. `import-document`
4. `import-feed`
5. `regenerate`

## Data Flow

```text
legislation.gov.uk / Research Legislation
  -> fetch XML or bulk archive
  -> cache raw input under var/cache
  -> parse CLML
  -> normalize internal document model
  -> render deterministic Markdown
  -> write metadata manifests
  -> commit generated output
  -> open pull request
```

## Testing Strategy

Use snapshot-style tests for generated Markdown.

Test layers:

- parser tests for CLML structures;
- path generation tests;
- renderer tests for small XML fragments;
- full-document snapshot tests for a few stable examples;
- idempotency tests: running the converter twice produces identical files;
- regeneration tests: committed Markdown matches output generated from fixtures.

The most important CI check:

```text
regenerate from known inputs -> git diff must be empty
```

## Git Workflow

For v1, imports should happen on generated branches:

```text
main
import/ukpga-2026-14
import/publication-log-2026-05-02
```

Each generated commit should include:

- title;
- type/year/number;
- source URI;
- publication log entry URI if available;
- converter version;
- warning count.

Example:

```text
Import ukpga/2026/14

Source: https://www.legislation.gov.uk/ukpga/2026/14/data.xml
Publication log: https://www.legislation.gov.uk/update/...
Generated by: git-legislation 0.1.0
```

## Suggested Milestones

### Milestone 1: Skeleton

- Initialize Python project with `uv`.
- Add CLI shell.
- Add docs and test structure.
- Add `.gitignore`.

### Milestone 2: One Document

- Fetch one `ukpga` CLML document.
- Convert a subset of its sections to Markdown.
- Commit generated output.
- Verify diffs are stable after regeneration.

### Milestone 3: Representative Documents

- Add one example for each major legislation family.
- Extend parser to handle schedules and common annotations.
- Document unsupported CLML nodes.

### Milestone 4: Feed Import

- Read Publication Log.
- Fetch new or republished XML.
- Create import branches locally.
- Generate a PR-ready summary.

### Milestone 5: Corpus Scale Test

- Use Research Legislation bulk data for a bounded corpus.
- Measure runtime, storage, and Git performance.
- Decide whether full XML source belongs in object storage, Git LFS, or cache-only.

## Recommendation

Start with a Python CLI and a narrow vertical slice:

1. fetch `ukpga/2026/14/data.xml`;
2. parse CLML;
3. render provision-level Markdown;
4. regenerate deterministically;
5. inspect the Git diff.

That will answer the most important architectural question quickly: whether the Markdown representation is stable and readable enough to make the pull request metaphor work.
