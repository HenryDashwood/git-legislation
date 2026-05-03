from pathlib import Path
from typing import Annotated

import typer

from converters.clmltomarkdown import render_document_markdown, write_document_markdown
from fetchers.legislationdotgovdotuk import (
    DEFAULT_OUTPUT_ROOT,
    create_client,
    fetch_document_xml,
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
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    with create_client() as client:
        content = fetch_document_xml(client, legislation_type=legislation_type, year=year, number=number)

    path = write_document_xml(
        content, legislation_type=legislation_type, year=year, number=number, output_root=output_root
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
