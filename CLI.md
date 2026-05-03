# CLI

This project currently exposes one command-line entry point:

```bash
uv run git-legislation --help
```

The CLI writes generated files under `output/` by default. Use `--output-root` on fetch and convert commands to write somewhere else.

## Commands

### `list-year`

List legislation discovered from a legislation.gov.uk year feed.

```bash
uv run git-legislation list-year ukpga 2026
```

This reads:

```text
https://www.legislation.gov.uk/{type}/{year}/data.feed
```

and prints entries as:

```text
ukpga/2026/14  Industry and Exports (Financial Assistance) Act 2026
```

### `fetch-xml`

Fetch XML for one document.

```bash
uv run git-legislation fetch-xml ukpga 2026 14
```

By default this fetches the moving current endpoint:

```text
https://www.legislation.gov.uk/ukpga/2026/14/data.xml
```

and stores it as today's point-in-time snapshot:

```text
output/xml/point-in-time/YYYY-MM-DD/ukpga/2026/14/data.xml
```

Fetch enacted XML:

```bash
uv run git-legislation fetch-xml ukpga 2026 14 --as-enacted
```

Output:

```text
output/xml/enacted/ukpga/2026/14/data.xml
```

Fetch an explicit point-in-time XML snapshot:

```bash
uv run git-legislation fetch-xml ukpga 2026 14 --at 2026-03-18
```

Output:

```text
output/xml/point-in-time/2026-03-18/ukpga/2026/14/data.xml
```

### `fetch-year`

Fetch every document discovered in one year feed.

```bash
uv run git-legislation fetch-year ukpga 2026
```

Fetch enacted XML for every document in the year:

```bash
uv run git-legislation fetch-year ukpga 2026 --as-enacted
```

Fetch point-in-time XML for every document in the year:

```bash
uv run git-legislation fetch-year ukpga 2026 --at 2026-03-18
```

This command prints each file path it writes.

### `fetch-enacted-corpus`

Fetch enacted XML across a range of years for one legislation type.

```bash
uv run git-legislation fetch-enacted-corpus ukpga 2020 --end-year 2026
```

If `--end-year` is omitted, the command uses the current year.

Output XML:

```text
output/xml/enacted/{type}/{year}/{number}/data.xml
```

Fetch report:

```text
output/reports/fetch/enacted/{type}/{start-year}-{end-year}.json
```

The report records fetched file paths and failures such as missing year feeds or unavailable XML.

The command logs years where documents are found, failures, and occasional checkpoints for long empty ranges.

### `fetch-point-in-time-corpus`

Fetch point-in-time XML for the configured corpus as it stood on one snapshot date.

```bash
uv run git-legislation fetch-point-in-time-corpus --at 2026-05-03
```

The CLI only takes the point-in-time date. The corpus scope is configured in code while we build this out incrementally; at this stage it starts with `ukpga`.

This command is for targeted API fetching while we explore the source. The initial full corpus import should use Research Legislation bulk downloads.

Output XML:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}/data.xml
```

Fetch report:

```text
output/reports/fetch/point-in-time/{yyyy-mm-dd}.json
```

The report records fetched file paths and failures such as missing year feeds or unavailable dated XML.

The command logs years where documents are found, failures, and occasional checkpoints for long empty ranges.

### `download-bulk-enacted-xml`

Download the Research Legislation enacted ePublished CLML archive.

```bash
uv run git-legislation download-bulk-enacted-xml
```

Current download URL:

```text
https://research.legislation.gov.uk/data/downloads/texts/enacted-epublished/xml/enacted-epublished-xml.zip
```

Output archive:

```text
output/bulk/research-legislation/texts/enacted-epublished/xml/enacted-epublished-xml.zip
```

This archive is large, currently listed by Research Legislation as 4.52 GB.

If Research Legislation returns `401 Unauthorized`, the bulk download site is requiring access credentials. In that case, download the ZIP manually if you have access, then pass the local archive path to `seed-enacted-xml`.

### `seed-enacted-xml`

Seed enacted CLML XML from a downloaded Research Legislation archive into the converter input layout.

```bash
uv run git-legislation seed-enacted-xml \
  output/bulk/research-legislation/texts/enacted-epublished/xml/enacted-epublished-xml.zip
```

Output XML:

```text
output/xml/enacted/{type}/{year}/{number}/data.xml
```

### `convert-xml`

Convert one CLML XML file to Markdown.

```bash
uv run git-legislation convert-xml \
  output/xml/enacted/ukpga/2026/14/data.xml \
  ukpga 2026 14
```

Current output:

```text
output/markdown/enacted/ukpga/2026/14.md
```

The converter is still early and currently renders a subset of CLML into a single Markdown file.

## Output Layout

Enacted XML:

```text
output/xml/enacted/{type}/{year}/{number}/data.xml
```

Point-in-time XML:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}/data.xml
```

Fetch reports:

```text
output/reports/fetch/enacted/{type}/{start-year}-{end-year}.json
output/reports/fetch/point-in-time/{yyyy-mm-dd}.json
```

Markdown:

```text
output/markdown/enacted/{type}/{year}/{number}.md
```

## Current Caveats

- The first complete path is focused on `ukpga`.
- `fetch-year`, `fetch-enacted-corpus`, `fetch-point-in-time-corpus`, and `seed-enacted-xml` print paths for files they write.
- Markdown conversion is still a prototype and does not yet handle the full CLML surface.
