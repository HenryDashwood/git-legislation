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

It also writes a manifest:

```text
output/manifests/enacted/{type}/{start_year}-{end_year}.json
```

The manifest records fetched documents and expected missing or failed resources. This matters for historical corpus runs because not every discovered item is guaranteed to have fetchable CLML XML.

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

Fetch manifests:

```text
output/manifests/{corpus}/{type}/{start_year}-{end_year}.json
```

Markdown:

```text
output/markdown/enacted/{type}/{year}/{number}.md
```

## Current Caveats

- The first complete path is focused on `ukpga`.
- `fetch-year` prints paths but does not currently write a manifest.
- `fetch-enacted-corpus` writes a manifest.
- Manifest paths are currently absolute local paths; for exportable generated repos, these should become paths relative to `output_root`.
- Markdown conversion is still a prototype and does not yet handle the full CLML surface.
