from pathlib import Path
from typing import Annotated

import typer

from converters.clmltomarkdown import render_document_markdown, write_document_markdown
from fetchers.legislationdotgovdotuk import (
    DEFAULT_OUTPUT_ROOT,
    create_client,
    fetch_document_xml,
    fetch_year_feed,
    parse_year_feed,
    write_document_xml,
)

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
        feed = fetch_year_feed(client, legislation_type=legislation_type, year=year)

    for document in parse_year_feed(feed):
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
        feed = fetch_year_feed(client, legislation_type=legislation_type, year=year)
        documents = parse_year_feed(feed)

        for document in documents:
            content = fetch_document_xml(
                client,
                legislation_type=document.legislation_type,
                year=document.year,
                number=document.number,
                as_enacted=as_enacted,
                at=at,
            )
            path = write_document_xml(
                content,
                legislation_type=document.legislation_type,
                year=document.year,
                number=document.number,
                as_enacted=as_enacted,
                at=at,
                output_root=output_root,
            )
            typer.echo(path)
