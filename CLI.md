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

### `fetch-source-xml`

Fetch XML for one legislation.gov.uk source path. Use this for older regnal-year paths discovered in feeds or reports, such as `ukpga/Geo3/44/42`.

Fetch the latest XML:

```bash
uv run git-legislation fetch-source-xml ukpga/Geo3/44/42
```

Output:

```text
output/xml/latest/ukpga/Geo3/44/42/data.xml
```

Fetch enacted XML:

```bash
uv run git-legislation fetch-source-xml ukpga/Geo3/44/42 --as-enacted
```

Output:

```text
output/xml/enacted/ukpga/Geo3/44/42/data.xml
```

Fetch point-in-time XML:

```bash
uv run git-legislation fetch-source-xml ukpga/Geo3/44/42 --at 2026-05-03
```

Output:

```text
output/xml/point-in-time/2026-05-03/ukpga/Geo3/44/42/data.xml
```

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

Older legislation can use regnal-year source paths rather than calendar-year paths. Those are mirrored from legislation.gov.uk:

```text
output/xml/enacted/ukpga/Vict/1-2/42/data.xml
```

Fetch report:

```text
output/reports/fetch/enacted/{type}/{start-year}-{end-year}.json
```

The report records fetched file paths and failures such as missing year feeds or unavailable XML.

The command logs years where documents are found, failures, and occasional checkpoints for long empty ranges.

If a year-level feed is too broad and legislation.gov.uk returns HTTP `436`, the fetcher automatically retries that year as number-range feeds such as:

```text
https://www.legislation.gov.uk/ukla/1803/1-100/data.feed
https://www.legislation.gov.uk/ukla/1803/101-200/data.feed
```

For large or paginated years, the command also logs feed progress while it is still inside a year, including split range totals and every additional feed page read.

If legislation.gov.uk returns HTTP `429` rate-limit responses, the client backs off and retries before treating the request as failed. It honors `Retry-After` when the server provides it, otherwise it uses exponential backoff.

### `fetch-point-in-time-corpus`

Fetch latest/current XML for every supported corpus type and store it under today's snapshot date.

```bash
uv run git-legislation fetch-point-in-time-corpus
```

The command uses current `/data.xml` document URLs and writes them under:

```text
output/xml/point-in-time/YYYY-MM-DD/{type}/{year}/{number}/data.xml
```

This is the main path for building a corpus of legislation as it currently stands.

Fetch just one legislation type with:

```bash
uv run git-legislation fetch-point-in-time-corpus --legislation-type ukla
```

Fetch more than one type by repeating the option:

```bash
uv run git-legislation fetch-point-in-time-corpus \
  --legislation-type ukpga \
  --legislation-type ukla \
  --legislation-type uksi
```

The fetcher is idempotent at the document XML level. Reruns still request the year feeds so they can discover the document list, but they skip document XML URLs whose target `data.xml` file already exists in the output tree.

You can still request an explicit historical date while exploring source coverage:

```bash
uv run git-legislation fetch-point-in-time-corpus --at 2026-05-03
```

With `--at`, the command uses dated `/YYYY-MM-DD/data.xml` document URLs.

Supported point-in-time corpus types currently include the official non-draft legislation.gov.uk type codes in scope for the project:

```text
aep    Acts of the English Parliament
aosp   Acts of the Old Scottish Parliament
aip    Acts of the Old Irish Parliament
apgb   Acts of the Parliament of Great Britain
gbppa  Private and Personal Acts of the Parliament of Great Britain
gbla   Local Acts of the Parliament of Great Britain
ukpga  UK Public General Acts
ukla   UK Local Acts
ukppa  UK Private and Personal Acts
apni   Acts of the Northern Ireland Parliament
ukcm   UK Church Measures
nisro  Northern Ireland Statutory Rules and Orders
uksi   UK Statutory Instruments
nisi   Northern Ireland Orders in Council
mnia   Measures of the Northern Ireland Assembly
nisr   Northern Ireland Statutory Rules
asp    Acts of the Scottish Parliament
ssi    Scottish Statutory Instruments
wsi    Wales Statutory Instruments
nia    Acts of the Northern Ireland Assembly
mwa    Measures of the Welsh Assembly
anaw   Acts of the Welsh Assembly
ukci   UK Church Instruments
asc    Acts of Senedd Cymru
ukmo   UK Ministerial Orders
```

Draft legislation types are intentionally not included in the default corpus because they are not enacted or made law. Each supported type has its own configured crawl start year, and closed historical series such as `aep`, `aip`, `apgb`, `gbla`, `gbppa`, `aosp`, `apni`, and `mnia` also have configured end years.

If no `--legislation-type` is passed, the command fetches every supported type.

This command is for targeted API fetching while we explore the source. The initial full corpus import should use Research Legislation bulk downloads.

Output XML:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}/data.xml
```

Older legislation can use regnal-year source paths rather than calendar-year paths. Those are mirrored from legislation.gov.uk:

```text
output/xml/point-in-time/{yyyy-mm-dd}/ukpga/Vict/1-2/42/data.xml
```

Fetch report:

```text
output/reports/fetch/point-in-time/{yyyy-mm-dd}.json
```

The report records fetched or already-present file paths and failures such as missing year feeds or unavailable dated XML.

The command logs years where documents are found, failures, and occasional checkpoints for long empty ranges.

### `probe-fetch-failures`

Probe fallback URLs for failures in a fetch report and write the probe results back into the report.

```bash
uv run git-legislation probe-fetch-failures \
  output/reports/fetch/point-in-time/2026-05-03.json \
  --limit 20
```

Use `--limit` while exploring so we do not multiply requests across thousands of historical failures.

For each unprobed document failure, this checks:

```text
{document}/data.xml
{document}/enacted/data.xml
{document}/resources/data.xml
```

The report records each probe's label, URL, HTTP status, error if one occurred, any PDF alternative URLs found in `resources/data.xml`, and a `classification` for the failure.

Current classifications include:

```text
dated_xml_unavailable_latest_xml_available
dated_xml_unavailable_latest_xml_available_pdf_available
dated_xml_unavailable_enacted_xml_available
dated_xml_unavailable_enacted_xml_available_pdf_available
dated_xml_unavailable_pdf_available
dated_xml_unavailable_metadata_available
dated_xml_unavailable_no_fallback_found
```

This lets us distinguish fixable fetcher gaps from source limitations such as PDF-only historical legislation.

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
  output/xml/point-in-time/2026-05-03/ukpga/2026/14/data.xml
```

The command infers the Markdown destination from the fetched XML path.

Point-in-time output:

```text
output/markdown/point-in-time/2026-05-03/ukpga/2026/14.md
```

Enacted input:

```bash
uv run git-legislation convert-xml \
  output/xml/enacted/ukpga/2026/14/data.xml
```

Enacted output:

```text
output/markdown/enacted/ukpga/2026/14.md
```

The converter is still early and currently renders a subset of CLML into a single Markdown file.

### `convert-enacted-corpus`

Convert all fetched enacted XML for one legislation type.

```bash
uv run git-legislation convert-enacted-corpus ukpga
```

Input XML:

```text
output/xml/enacted/{type}/**/data.xml
```

Output Markdown:

```text
output/markdown/enacted/{type}/**/*.md
```

Conversion report:

```text
output/reports/convert/enacted/{type}/report.json
```

Older legislation keeps its source path:

```text
output/xml/enacted/ukpga/Vict/1-2/42/data.xml
output/markdown/enacted/ukpga/Vict/1-2/42.md
```

### `convert-point-in-time-corpus`

Convert all fetched point-in-time XML for one snapshot date.

```bash
uv run git-legislation convert-point-in-time-corpus --at 2026-05-03
```

If no `--legislation-type` is passed, the command converts every legislation type directory found under:

```text
output/xml/point-in-time/{yyyy-mm-dd}/
```

Limit conversion to one type with:

```bash
uv run git-legislation convert-point-in-time-corpus --at 2026-05-03 --legislation-type ukla
```

Convert more than one type by repeating the option:

```bash
uv run git-legislation convert-point-in-time-corpus \
  --at 2026-05-03 \
  --legislation-type ukpga \
  --legislation-type uksi
```

Input XML:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/**/data.xml
```

Output Markdown:

```text
output/markdown/point-in-time/{yyyy-mm-dd}/{type}/**/*.md
```

Conversion report:

```text
output/reports/convert/point-in-time/{yyyy-mm-dd}/{type}.json
```

The corpus converters are idempotent: they render deterministic Markdown and overwrite each type's conversion report, so rerunning the command is safe. They log periodic checkpoints, continue after malformed or unsupported XML files, and write failures to the conversion report with the input path, inferred source path, and error message.

### `audit-point-in-time-coverage`

Summarize fetch, XML, Markdown, and conversion coverage for one snapshot date.

```bash
uv run git-legislation audit-point-in-time-coverage --at 2026-05-04
```

The legislation type defaults to `ukpga`. Override it with:

```bash
uv run git-legislation audit-point-in-time-coverage --at 2026-05-04 --legislation-type ukla
```

The audit reads:

```text
output/reports/fetch/point-in-time/{yyyy-mm-dd}.json
output/reports/convert/point-in-time/{yyyy-mm-dd}/{type}.json
output/xml/point-in-time/{yyyy-mm-dd}/{type}/**/data.xml
output/markdown/point-in-time/{yyyy-mm-dd}/{type}/**/*.md
```

It reports expected documents from the fetch report, valid legislation XML, full-text XML, metadata-only XML, PDF-linked XML, local XML problems, Markdown file counts, conversion failures, and grouped failure categories.

### `audit-all-point-in-time-coverage`

Summarize fetch, XML, Markdown, and conversion coverage across every legislation type fetched for one snapshot date.

```bash
uv run git-legislation audit-all-point-in-time-coverage --at 2026-05-05
```

This discovers legislation types from:

```text
output/xml/point-in-time/{yyyy-mm-dd}/{type}/
```

It logs progress as it audits each type, then prints a table with expected documents, valid XML, full-text XML, metadata-only XML, Markdown files, fetch failures, conversion failures, local XML problems, and Markdown gaps for each type. It also prints totals across all discovered types.

Use `audit-point-in-time-coverage --legislation-type {type}` when you need the more detailed breakdown for a single type.

### `point-in-time-failures`

Print the exact fetch and conversion failures for one snapshot date.

```bash
uv run git-legislation point-in-time-failures --at 2026-05-04
```

The legislation type defaults to `ukpga`. Override it with:

```bash
uv run git-legislation point-in-time-failures --at 2026-05-04 --legislation-type ukla
```

This reads the same fetch and conversion reports as `audit-point-in-time-coverage`, but expands the individual failed documents with their year/number, source path, URL, input path, and error message where available.

### `clean-point-in-time-xml`

Remove bad local XML files from one snapshot date. This only targets local `data.xml` files that are empty, malformed, or not legislation XML.

Check what would be removed:

```bash
uv run git-legislation clean-point-in-time-xml --at 2026-05-04 --dry-run
```

Remove the bad local files:

```bash
uv run git-legislation clean-point-in-time-xml --at 2026-05-04
```

After cleanup, rerun the fetcher to retry those documents:

```bash
uv run git-legislation fetch-point-in-time-corpus
```

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

Conversion reports:

```text
output/reports/convert/enacted/{type}/report.json
output/reports/convert/point-in-time/{yyyy-mm-dd}/{type}.json
```

Markdown:

```text
output/markdown/enacted/{type}/{year}/{number}.md
output/markdown/point-in-time/{yyyy-mm-dd}/{type}/{year}/{number}.md
```

## Current Caveats

- The first complete path is focused on `ukpga`.
- `fetch-year` and `seed-enacted-xml` print paths for files they write.
- `fetch-enacted-corpus` and `fetch-point-in-time-corpus` print progress summaries and the report path, but not every written XML path.
- Markdown conversion is still a prototype and does not yet handle the full CLML surface.
