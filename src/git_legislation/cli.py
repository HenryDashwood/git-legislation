from datetime import date
from pathlib import Path
from typing import Annotated

import click
import typer

from converters.clmltomarkdown import (
    ConversionReport,
    convert_document_markdown,
    convert_xml_tree,
    write_conversion_report,
)
from coverage_audit import (
    audit_point_in_time_coverage,
    clean_point_in_time_xml,
    render_cleanup_result,
    render_coverage_audit,
    render_point_in_time_failure_details,
)
from fetchers.legislationdotgovdotuk import (
    DEFAULT_OUTPUT_ROOT,
    FetchReport,
    create_client,
    document_ref_from_source_path,
    fetch_document_ref_xml,
    fetch_document_xml,
    fetch_enacted_corpus,
    fetch_point_in_time_corpus,
    fetch_year_document_refs,
    fetch_year_documents,
    probe_fetch_report_failures,
    read_fetch_report,
    write_document_xml,
    write_fetch_report,
    write_source_document_xml,
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
    with create_client(log=typer.echo) as client:
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


@app.command("fetch-source-xml")
def fetch_source_xml(
    source_path: str,
    as_enacted: Annotated[bool, typer.Option("--as-enacted", help="Fetch /enacted/data.xml.")] = False,
    at: Annotated[str | None, typer.Option("--at", help="Fetch point-in-time /YYYY-MM-DD/data.xml.")] = None,
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    document = document_ref_from_source_path(source_path)
    with create_client(log=typer.echo) as client:
        content = fetch_document_ref_xml(
            client,
            document=document,
            as_enacted=as_enacted,
            at=at,
        )

    path = write_source_document_xml(
        content,
        source_path=document.path,
        as_enacted=as_enacted,
        at=at,
        output_root=output_root,
    )
    typer.echo(path)


@app.command("convert-xml")
def convert_xml(
    xml_path: Path,
    output_root: Annotated[Path, typer.Option(help="Root folder for converter output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    path = convert_document_markdown(xml_path, output_root=output_root)
    typer.echo(path)


@app.command("convert-enacted-corpus")
def convert_enacted_corpus(
    legislation_type: str,
    output_root: Annotated[
        Path, typer.Option(help="Root folder for converter input and output.")
    ] = DEFAULT_OUTPUT_ROOT,
) -> None:
    report = ConversionReport.enacted(legislation_type=legislation_type)
    paths = convert_xml_tree(
        output_root / "xml" / "enacted" / legislation_type,
        output_root=output_root,
        report=report,
        log=typer.echo,
    )
    typer.echo(f"Converted enacted {legislation_type}: {len(paths)} documents, {len(report.failures)} failures")
    typer.echo(write_conversion_report(report, output_root=output_root))


@app.command("convert-point-in-time-corpus")
def convert_point_in_time_corpus(
    at: Annotated[str, typer.Option("--at", help="Snapshot date to convert as YYYY-MM-DD.")],
    legislation_type: Annotated[str, typer.Option(help="Legislation type to convert.")] = "ukpga",
    output_root: Annotated[
        Path, typer.Option(help="Root folder for converter input and output.")
    ] = DEFAULT_OUTPUT_ROOT,
) -> None:
    report = ConversionReport.point_in_time(legislation_type=legislation_type, at=at)
    paths = convert_xml_tree(
        output_root / "xml" / "point-in-time" / at / legislation_type,
        output_root=output_root,
        report=report,
        log=typer.echo,
    )
    typer.echo(
        f"Converted point-in-time {legislation_type} at {at}: {len(paths)} documents, {len(report.failures)} failures"
    )
    typer.echo(write_conversion_report(report, output_root=output_root))


@app.command("audit-point-in-time-coverage")
def audit_point_in_time_coverage_command(
    at: Annotated[str, typer.Option("--at", help="Snapshot date to audit as YYYY-MM-DD.")],
    legislation_type: Annotated[str, typer.Option(help="Legislation type to audit.")] = "ukpga",
    output_root: Annotated[Path, typer.Option(help="Root folder for audit input.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    audit = audit_point_in_time_coverage(at=at, legislation_type=legislation_type, output_root=output_root)
    typer.echo(render_coverage_audit(audit))


@app.command("point-in-time-failures")
def point_in_time_failures_command(
    at: Annotated[str, typer.Option("--at", help="Snapshot date to inspect as YYYY-MM-DD.")],
    legislation_type: Annotated[str, typer.Option(help="Legislation type to inspect.")] = "ukpga",
    output_root: Annotated[Path, typer.Option(help="Root folder for report input.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    typer.echo(
        render_point_in_time_failure_details(at=at, legislation_type=legislation_type, output_root=output_root)
    )


@app.command("clean-point-in-time-xml")
def clean_point_in_time_xml_command(
    at: Annotated[str, typer.Option("--at", help="Snapshot date to clean as YYYY-MM-DD.")],
    legislation_type: Annotated[str, typer.Option(help="Legislation type to clean.")] = "ukpga",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List files that would be removed without deleting them."),
    ] = False,
    output_root: Annotated[Path, typer.Option(help="Root folder for cleanup input.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    result = clean_point_in_time_xml(
        at=at,
        legislation_type=legislation_type,
        output_root=output_root,
        dry_run=dry_run,
    )
    typer.echo(render_cleanup_result(result))


@app.command("list-year")
def list_year(legislation_type: str, year: int) -> None:
    with create_client(log=typer.echo) as client:
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
    with create_client(log=typer.echo) as client:
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
    with create_client(log=typer.echo) as client:
        fetch_enacted_corpus(
            client,
            legislation_type=legislation_type,
            start_year=start_year,
            end_year=end_year or date.today().year,
            output_root=output_root,
            report=report,
            log=typer.echo,
        )

    typer.echo(write_fetch_report(report, output_root=output_root))


@app.command("fetch-point-in-time-corpus")
def fetch_point_in_time_corpus_command(
    at: Annotated[
        str | None,
        typer.Option("--at", help="Snapshot date to fetch as YYYY-MM-DD. Defaults to today's latest/current XML."),
    ] = None,
    legislation_types: Annotated[
        list[str] | None,
        typer.Option(
            "--legislation-type",
            help="Legislation type to fetch. Repeat to fetch more than one. Defaults to every supported type.",
        ),
    ] = None,
    output_root: Annotated[Path, typer.Option(help="Root folder for fetcher output.")] = DEFAULT_OUTPUT_ROOT,
) -> None:
    snapshot_date = at or date.today().isoformat()
    report = FetchReport.point_in_time_corpus(at=snapshot_date)
    with create_client(log=typer.echo) as client:
        fetch_point_in_time_corpus(
            client,
            at=at,
            legislation_types=legislation_types,
            output_root=output_root,
            report=report,
            log=typer.echo,
        )

    typer.echo(write_fetch_report(report, output_root=output_root))


@app.command("probe-fetch-failures")
def probe_fetch_failures(
    report_path: Path,
    limit: Annotated[
        int | None,
        typer.Option(help="Maximum number of unprobed failures to probe."),
    ] = None,
) -> None:
    report = read_fetch_report(report_path)
    with create_client(log=typer.echo) as client:
        probed = probe_fetch_report_failures(
            client,
            report,
            limit=limit,
            log=typer.echo,
        )

    typer.echo(f"Probed {probed} failures")
    typer.echo(write_fetch_report(report, output_root=report_path.parents[3]))


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
