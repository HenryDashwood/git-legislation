import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any

import click
import psycopg
import typer

from converters.clmltomarkdown import render_document_markdown_from_xml
from fetchers.legislationdotgovdotuk import (
    POINT_IN_TIME_CORPUS_END_YEARS,
    POINT_IN_TIME_CORPUS_START_YEARS,
    create_client,
    document_ref_from_source_path,
    document_ref_xml_url,
    fetch_document_ref_xml,
    fetch_year_document_refs,
)
from object_store import DEFAULT_OBJECT_STORE_ROOT, LocalObjectStore
from pdf_parsing import (
    cache_document_marker_markdown,
    cache_document_pdf,
    normalize_liteparse_markdown_sample,
    parse_pdf_sample,
    render_liteparse_markdown_report,
    render_pdf_parse_sample_report,
)
from publishing import (
    PublishReport,
    create_publish_run,
    finish_publish_run,
    publish_document_text,
    publish_document_text_to_postgres,
    record_publish_observation,
    render_publish_report,
)

app = typer.Typer(no_args_is_help=True)
COUNT_TABLES = (
    "documents",
    "document_versions",
    "provisions",
    "storage_objects",
    "document_files",
    "fetch_runs",
    "fetch_observations",
)


@dataclass(frozen=True)
class CorpusCounts:
    database_counts: dict[str, int]
    object_count: int
    object_bytes: int


@app.callback()
def main() -> None:
    """Ingest, transform, and publish legislation data."""


@app.command("list-year")
def list_year(legislation_type: str, year: int) -> None:
    with create_client(log=typer.echo) as client:
        documents = fetch_year_document_refs(client, legislation_type=legislation_type, year=year)

    for document in documents:
        typer.echo(f"{document.legislation_type}/{document.year}/{document.number}  {document.title}")


@app.command("ingest-document")
def ingest_document(
    source_path: Annotated[str, typer.Argument(help="Legislation source path, e.g. ukpga/2026/14.")],
    at: Annotated[str | None, typer.Option("--at", help="Point-in-time snapshot date as YYYY-MM-DD.")] = None,
    as_enacted: Annotated[bool, typer.Option("--as-enacted", help="Fetch /enacted/data.xml.")] = False,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    if as_enacted and at is not None:
        raise click.ClickException("--as-enacted cannot be combined with --at.")
    if not as_enacted and at is None:
        raise click.ClickException("--at is required unless --as-enacted is used.")
    if database_url is None:
        database_url = os.environ.get("DB_URL")
    if database_url is None:
        raise click.ClickException("Set DB_URL or pass --database-url.")

    document = document_ref_from_source_path(source_path)
    source_url = document_ref_xml_url(document=document, as_enacted=as_enacted, at=at)
    with create_client(log=typer.echo) as client:
        xml_content = fetch_document_ref_xml(client, document=document, as_enacted=as_enacted, at=at)
    markdown = render_document_markdown_from_xml(xml_content)
    published_version = publish_document_text_to_postgres(
        database_url=database_url,
        source_path=document.path,
        xml_content=xml_content,
        markdown=markdown,
        collection="enacted" if as_enacted else "point-in-time",
        snapshot_date=None if as_enacted else at,
        object_store_root=object_store_root,
        object_store_bucket=object_store_bucket,
    )
    action = "created" if published_version.created else "reused"
    typer.echo(f"Ingested {source_url}")
    typer.echo(f"{action} document version {published_version.version_id}")


@app.command("ingest-point-in-time-year")
def ingest_point_in_time_year(
    legislation_type: Annotated[str, typer.Argument(help="Legislation type to ingest, e.g. ukpga.")],
    year: Annotated[int, typer.Argument(help="Year to ingest.")],
    at: Annotated[str, typer.Option("--at", help="Point-in-time snapshot date as YYYY-MM-DD.")],
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)

    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        report = _ingest_point_in_time_year(
            connection,
            client=client,
            object_store=object_store,
            legislation_type=legislation_type,
            year=year,
            at=at,
            log=typer.echo,
        )
        connection.commit()

    typer.echo(render_publish_report(report))


@app.command("ingest-point-in-time-corpus")
def ingest_point_in_time_corpus(
    at: Annotated[
        str | None,
        typer.Option("--at", help="Snapshot date to ingest as YYYY-MM-DD. Defaults to today's latest/current XML."),
    ] = None,
    legislation_types: Annotated[
        list[str] | None,
        typer.Option(
            "--legislation-type",
            help="Legislation type to ingest. Repeat to ingest more than one. Defaults to every supported type.",
        ),
    ] = None,
    start_legislation_type: Annotated[
        str | None,
        typer.Option(
            "--start-legislation-type",
            help="Resume at this legislation type, skipping earlier supported types.",
        ),
    ] = None,
    start_year: Annotated[
        int | None,
        typer.Option("--start-year", help="Resume at this year for the starting legislation type."),
    ] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    snapshot_date = at or date.today().isoformat()
    snapshot_year = date.fromisoformat(snapshot_date).year
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    report = PublishReport(collection="point-in-time", snapshot_date=snapshot_date, database_path="Postgres")

    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        for legislation_type in _point_in_time_corpus_types(
            legislation_types,
            start_legislation_type=start_legislation_type,
        ):
            corpus_start_year = POINT_IN_TIME_CORPUS_START_YEARS[legislation_type]
            end_year = min(snapshot_year, POINT_IN_TIME_CORPUS_END_YEARS.get(legislation_type, snapshot_year))
            first_year = _first_corpus_year(
                legislation_type=legislation_type,
                start_legislation_type=start_legislation_type,
                resume_year=start_year,
                corpus_start_year=corpus_start_year,
            )
            for year in range(first_year, end_year + 1):
                year_report = _ingest_point_in_time_year(
                    connection,
                    client=client,
                    object_store=object_store,
                    legislation_type=legislation_type,
                    year=year,
                    at=snapshot_date,
                    log=typer.echo,
                )
                _merge_publish_report(report, year_report)
                connection.commit()
                typer.echo(
                    f"Ingested point-in-time {legislation_type} {year} at {snapshot_date}: "
                    f"{year_report.published} published, {len(year_report.failures)} failures"
                )

    typer.echo(render_publish_report(report))


@app.command("corpus-counts")
def corpus_counts(
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    database_url = _database_url_or_raise(database_url)
    bucket_root = object_store_root / object_store_bucket
    with psycopg.connect(database_url) as connection:
        counts = CorpusCounts(
            database_counts=_database_counts(connection),
            object_count=_object_count(bucket_root),
            object_bytes=_object_bytes(bucket_root),
        )
    typer.echo(render_corpus_counts(counts))


@app.command("cache-pdf")
def cache_pdf_command(
    source_path: Annotated[str, typer.Argument(help="Legislation source path, e.g. aosp/1469/12.")],
    at: Annotated[str | None, typer.Option("--at", help="Point-in-time snapshot date as YYYY-MM-DD.")] = None,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    document = document_ref_from_source_path(source_path)
    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        pdf_object = cache_document_pdf(
            connection,
            client=client,
            object_store=object_store,
            source_path=document.path,
            at=at,
        )
        connection.commit()
    typer.echo(f"Cached PDF {pdf_object.key}")


@app.command("parse-pdf-marker")
def parse_pdf_marker_command(
    source_path: Annotated[str, typer.Argument(help="Legislation source path, e.g. aosp/1469/12.")],
    at: Annotated[str | None, typer.Option("--at", help="Point-in-time snapshot date as YYYY-MM-DD.")] = None,
    marker_executable: Annotated[
        str,
        typer.Option("--marker-executable", help="Marker CLI executable."),
    ] = "marker_single",
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    document = document_ref_from_source_path(source_path)
    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        markdown_object = cache_document_marker_markdown(
            connection,
            client=client,
            object_store=object_store,
            source_path=document.path,
            at=at,
            marker_executable=marker_executable,
        )
        connection.commit()
    typer.echo(f"Created Marker Markdown {markdown_object.key}")


@app.command("parse-pdf-sample")
def parse_pdf_sample_command(
    at: Annotated[str | None, typer.Option("--at", help="Limit to a point-in-time snapshot date.")] = None,
    legislation_type: Annotated[
        str | None,
        typer.Option("--legislation-type", help="Limit to one legislation type, e.g. ukpga."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Maximum PDF-backed records to parse.")] = 10,
    include_full_text: Annotated[
        bool,
        typer.Option("--include-full-text", help="Include records whose XML already has full text."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Parse records even when extracted text already exists."),
    ] = False,
    no_ocr: Annotated[bool, typer.Option("--no-ocr", help="Disable LiteParse OCR.")] = False,
    target_pages: Annotated[
        str | None,
        typer.Option("--target-pages", help='LiteParse page selection, e.g. "1-5,10".'),
    ] = None,
    lit_executable: Annotated[str, typer.Option("--lit-executable", help="LiteParse CLI executable.")] = "lit",
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        report = parse_pdf_sample(
            connection,
            client=client,
            object_store=object_store,
            at=at,
            legislation_type=legislation_type,
            limit=limit,
            only_metadata=not include_full_text,
            force=force,
            lit_executable=lit_executable,
            no_ocr=no_ocr,
            target_pages=target_pages,
        )
        connection.commit()
    typer.echo(render_pdf_parse_sample_report(report))


@app.command("normalize-liteparse-markdown-sample")
def normalize_liteparse_markdown_sample_command(
    at: Annotated[str | None, typer.Option("--at", help="Limit to a point-in-time snapshot date.")] = None,
    legislation_type: Annotated[
        str | None,
        typer.Option("--legislation-type", help="Limit to one legislation type, e.g. ukpga."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Maximum LiteParse reports to normalize.")] = 10,
    force: Annotated[
        bool,
        typer.Option("--force", help="Normalize records even when LiteParse Markdown already exists."),
    ] = False,
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", envvar="DB_URL", help="Postgres connection URL. Defaults to DB_URL."),
    ] = None,
    object_store_root: Annotated[
        Path,
        typer.Option(
            "--object-store-root",
            help="Local filesystem object store root. Defaults to var/object-store.",
        ),
    ] = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: Annotated[
        str,
        typer.Option("--object-store-bucket", help="Object store bucket name."),
    ] = "legislation",
) -> None:
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    with psycopg.connect(database_url) as connection:
        report = normalize_liteparse_markdown_sample(
            connection,
            object_store=object_store,
            at=at,
            legislation_type=legislation_type,
            limit=limit,
            force=force,
        )
        connection.commit()
    typer.echo(render_liteparse_markdown_report(report))


def _ingest_point_in_time_year(
    connection: psycopg.Connection[Any],
    client: Any,
    object_store: LocalObjectStore,
    legislation_type: str,
    year: int,
    at: str,
    log: Callable[[str], None] | None,
) -> PublishReport:
    report = PublishReport(collection="point-in-time", snapshot_date=at, database_path="Postgres")
    try:
        documents = fetch_year_document_refs(client, legislation_type=legislation_type, year=year, log=log)
    except Exception as error:
        report.failures.append(f"{legislation_type} {year} feed: {error}")
        if log is not None:
            log(f"Failed to list {legislation_type} {year} documents: {error}")
        return report
    publish_run_id = create_publish_run(
        connection,
        collection="point-in-time",
        snapshot_date=at,
        legislation_types={legislation_type},
    )
    for index, document in enumerate(documents, start=1):
        report.scanned += 1
        source_url = document_ref_xml_url(document=document, at=at)
        try:
            xml_content = fetch_document_ref_xml(client, document=document, at=at)
            markdown = render_document_markdown_from_xml(xml_content)
            published_version = publish_document_text(
                connection,
                source_path=document.path,
                xml_content=xml_content,
                markdown=markdown,
                collection="point-in-time",
                snapshot_date=at,
                object_store=object_store,
            )
            record_publish_observation(connection, publish_run_id, published_version)
        except Exception as error:
            report.failures.append(f"{source_url}: {error}")
            continue

        report.published += 1
        if published_version.created:
            report.created_versions += 1
        else:
            report.reused_versions += 1
        if index % 500 == 0:
            typer.echo(
                f"Ingested {index} of {len(documents)} {legislation_type} {year} documents: "
                f"{report.published} published, {len(report.failures)} failures"
            )

    finish_publish_run(connection, publish_run_id)
    return report


def _point_in_time_corpus_types(
    legislation_types: list[str] | None,
    start_legislation_type: str | None = None,
) -> tuple[str, ...]:
    selected_types = tuple(POINT_IN_TIME_CORPUS_START_YEARS) if legislation_types is None else tuple(legislation_types)
    requested_types = set(selected_types)
    if start_legislation_type is not None:
        requested_types.add(start_legislation_type)
    unknown_types = sorted(requested_types - set(POINT_IN_TIME_CORPUS_START_YEARS))
    if unknown_types:
        raise click.ClickException(f"Unsupported point-in-time corpus legislation type(s): {', '.join(unknown_types)}")
    if start_legislation_type is None:
        return selected_types
    if start_legislation_type not in selected_types:
        raise click.ClickException("--start-legislation-type must also be selected by --legislation-type.")
    start_index = selected_types.index(start_legislation_type)
    return selected_types[start_index:]


def _first_corpus_year(
    legislation_type: str,
    start_legislation_type: str | None,
    resume_year: int | None,
    corpus_start_year: int,
) -> int:
    if resume_year is None or (start_legislation_type is not None and legislation_type != start_legislation_type):
        return corpus_start_year
    return max(corpus_start_year, resume_year)


def _merge_publish_report(total: PublishReport, partial: PublishReport) -> None:
    total.scanned += partial.scanned
    total.published += partial.published
    total.created_versions += partial.created_versions
    total.reused_versions += partial.reused_versions
    total.failures.extend(partial.failures)


def _database_counts(connection: psycopg.Connection[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in COUNT_TABLES:
        row = connection.execute(f"select count(*) from {table}").fetchone()
        counts[table] = int(row[0]) if row is not None else 0
    return counts


def _object_count(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file())


def _object_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def render_corpus_counts(counts: CorpusCounts) -> str:
    lines = ["Corpus counts:"]
    lines.extend(f"- {table}: {counts.database_counts.get(table, 0)}" for table in COUNT_TABLES)
    lines.append(f"- object_store_files: {counts.object_count}")
    lines.append(f"- object_store_bytes: {counts.object_bytes}")
    return "\n".join(lines)


def _database_url_or_raise(database_url: str | None) -> str:
    if database_url is None:
        database_url = os.environ.get("DB_URL")
    if database_url is None:
        raise click.ClickException("Set DB_URL or pass --database-url.")
    return database_url
