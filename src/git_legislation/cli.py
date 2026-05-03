from datetime import date
from pathlib import Path
from typing import Annotated

import click
import typer

from converters.clmltomarkdown import render_document_markdown, write_document_markdown
from fetchers.legislationdotgovdotuk import (
    DEFAULT_OUTPUT_ROOT,
    FetchReport,
    create_client,
    fetch_document_xml,
    fetch_enacted_corpus,
    fetch_point_in_time_corpus,
    fetch_year_document_refs,
    fetch_year_documents,
    write_document_xml,
    write_fetch_report,
)
from seeding import BulkArchiveDownloadError, download_bulk_archive, seed_enacted_xml_from_archive

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Fetch and transform legislation data."""


@app.command("fetch-xml")
def fetch_xml(
    legislation_type: str,
    year: int,
    number: int,
    as_enacted: Annotated[bool, typer.Option("--as-enacted", help="Fetch /enacted/data.xml.")] = False,
    at: Annotated[str | None, typer.Option("--at", help="Fetch point-in-time /YYYY-MM-DD/data.xml.")] = None,
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    with create_client() as client:
        content = fetch_document_xml(
            client,
            legislation_type=legislation_type,
            year=year,
            number=number,
            as_enacted=as_enacted,
            at=at,
        )

    path = write_document_xml(
        content,
        legislation_type=legislation_type,
        year=year,
        number=number,
        as_enacted=as_enacted,
        at=at,
        output_root=output_root,
    )
    typer.echo(path)


@app.command("convert-xml")
def convert_xml(
    xml_path: Path,
    legislation_type: str,
    year: int,
    number: int,
    output_root: Annotated[Path, typer.Option(help="Root folder for converter output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    markdown = render_document_markdown(xml_path)
    path = write_document_markdown(
        markdown,
        legislation_type=legislation_type,
        year=year,
        number=number,
        output_root=output_root,
    )
    typer.echo(path)


@app.command("list-year")
def list_year(legislation_type: str, year: int) -> None:
    with create_client() as client:
        documents = fetch_year_document_refs(client, legislation_type=legislation_type, year=year)

    for document in documents:
        typer.echo(f"{document.legislation_type}/{document.year}/{document.number}  {document.title}")


@app.command("fetch-year")
def fetch_year(
    legislation_type: str,
    year: int,
    as_enacted: Annotated[bool, typer.Option("--as-enacted", help="Fetch /enacted/data.xml.")] = False,
    at: Annotated[str | None, typer.Option("--at", help="Fetch point-in-time /YYYY-MM-DD/data.xml.")] = None,
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    with create_client() as client:
        paths = fetch_year_documents(
            client,
            legislation_type=legislation_type,
            year=year,
            as_enacted=as_enacted,
            at=at,
            output_root=output_root,
        )

    for path in paths:
        typer.echo(path)


@app.command("fetch-enacted-corpus")
def fetch_enacted_corpus_command(
    legislation_type: str,
    start_year: int,
    end_year: Annotated[
        int | None,
        typer.Option(help="Last year to fetch. Defaults to the current year."),
    ] = None,
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    report = FetchReport.enacted_corpus(
        legislation_type=legislation_type,
        start_year=start_year,
        end_year=end_year or date.today().year,
    )
    with create_client() as client:
        paths = fetch_enacted_corpus(
            client,
            legislation_type=legislation_type,
            start_year=start_year,
            end_year=end_year or date.today().year,
            output_root=output_root,
            report=report,
            log=typer.echo,
        )

    for path in paths:
        typer.echo(path)
    typer.echo(write_fetch_report(report, output_root=output_root))


@app.command("fetch-point-in-time-corpus")
def fetch_point_in_time_corpus_command(
    at: Annotated[str, typer.Option("--at", help="Snapshot date to fetch as YYYY-MM-DD.")],
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    report = FetchReport.point_in_time_corpus(at=at)
    with create_client() as client:
        paths = fetch_point_in_time_corpus(
            client,
            at=at,
            output_root=output_root,
            report=report,
            log=typer.echo,
        )

    for path in paths:
        typer.echo(path)
    typer.echo(write_fetch_report(report, output_root=output_root))


@app.command("download-bulk-enacted-xml")
def download_bulk_enacted_xml(
    output_root: Annotated[Path, typer.Option(help="Root folder for seeding output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    try:
        path = download_bulk_archive(dataset="enacted-epublished", data_format="xml", output_root=output_root)
    except BulkArchiveDownloadError as error:
        raise click.ClickException(str(error)) from error

    typer.echo(path)


@app.command("seed-enacted-xml")
def seed_enacted_xml(
    archive_path: Path,
    output_root: Annotated[Path, typer.Option(help="Root folder for seeded XML output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    paths = seed_enacted_xml_from_archive(archive_path=archive_path, output_root=output_root)

    for path in paths:
        typer.echo(path)
