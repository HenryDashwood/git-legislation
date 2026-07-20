import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Any

import click
import psycopg
import typer

from converters.clmltomarkdown import render_document_markdown_from_xml
from fetchers.legislationdotgovdotuk import (
    POINT_IN_TIME_CORPUS_END_YEARS,
    POINT_IN_TIME_CORPUS_START_YEARS,
    SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES,
    create_client,
    document_ref_from_source_path,
    document_ref_xml_url,
    fetch_document_ref_xml,
    fetch_publication_day_events,
    fetch_year_document_refs,
    parse_document_version_dates,
)
from object_store import DEFAULT_OBJECT_STORE_ROOT, LocalObjectStore
from pdf_parsing import (
    cache_document_marker_markdown,
    cache_document_pdf,
    cache_dynamic_only_pdfs,
    normalize_liteparse_markdown_sample,
    parse_pdf_sample,
    render_liteparse_markdown_report,
    render_pdf_parse_sample_report,
)
from publishing import (
    PublishReport,
    RerenderReport,
    VersionHashNormalizationReport,
    backfill_canonical_hashes,
    create_publish_run,
    finish_publish_run,
    merge_duplicate_version_rows,
    publish_document_text,
    publish_document_text_to_postgres,
    record_publish_observation,
    render_publish_report,
    render_rerender_report,
    render_version_hash_normalization_report,
    rerender_document_versions,
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


@app.command("rerender-markdown")
def rerender_markdown_command(
    at: Annotated[
        str | None,
        typer.Option("--at", help="Limit to a point-in-time snapshot date as YYYY-MM-DD."),
    ] = None,
    legislation_type: Annotated[
        str | None,
        typer.Option("--legislation-type", help="Limit to one legislation type code."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Process at most this many documents."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Count recoverable documents without publishing."),
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
    """Re-render metadata-only documents from stored XML with the current converter."""
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    metadata_marker = "Source XML contains metadata only"
    scanned = recovered = still_metadata = missing_xml = render_failures = 0

    filters = ["dv.is_metadata_only", "dv.version_kind in ('point_in_time', 'enacted')"]
    params: list[Any] = []
    if at is not None:
        filters.append("dv.snapshot_date = %s")
        params.append(at)
    if legislation_type is not None:
        filters.append("d.legislation_type = %s")
        params.append(legislation_type)
    limit_clause = ""
    if limit is not None:
        limit_clause = "limit %s"
        params.append(limit)

    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            f"""
            select d.id, d.source_path, dv.version_kind, dv.snapshot_date, f.object_key
            from documents d
            join document_versions dv on dv.id = d.latest_version_id
            join document_files f
              on f.version_id = dv.id and f.file_kind = 'clml_xml' and f.object_key is not null
            where {" and ".join(filters)}
            order by d.id
            {limit_clause}
            """,  # noqa: S608 - filters are fixed SQL fragments; values are bound parameters
            params,
        ).fetchall()
        typer.echo(f"Found {len(rows)} metadata-only documents with stored XML")

        publish_runs: dict[tuple[str, str | None], int] = {}
        for document_id, source_path, version_kind, snapshot_date, object_key in rows:
            scanned += 1
            xml_path = object_store.path_for_key(object_key)
            if not xml_path.exists():
                missing_xml += 1
                continue
            xml_content = xml_path.read_bytes()
            try:
                markdown = render_document_markdown_from_xml(xml_content)
            except Exception as error:
                render_failures += 1
                typer.echo(f"Failed to render {document_id}: {error}")
                continue
            if metadata_marker in markdown:
                still_metadata += 1
                continue
            recovered += 1
            if dry_run:
                continue

            collection = "point-in-time" if version_kind == "point_in_time" else "enacted"
            snapshot = snapshot_date.isoformat() if snapshot_date is not None else None
            run_key = (collection, snapshot)
            if run_key not in publish_runs:
                publish_runs[run_key] = create_publish_run(
                    connection,
                    collection=collection,
                    snapshot_date=snapshot,
                    legislation_types=set(),
                )
            published_version = publish_document_text(
                connection,
                source_path=tuple(source_path),
                xml_content=xml_content,
                markdown=markdown,
                collection=collection,
                snapshot_date=snapshot,
                object_store=object_store,
            )
            record_publish_observation(connection, publish_runs[run_key], published_version)
            if recovered % 500 == 0:
                connection.commit()
                typer.echo(f"Re-rendered {recovered} documents ({scanned} of {len(rows)} scanned)")

        for run_id in publish_runs.values():
            finish_publish_run(connection, run_id)
        connection.commit()

    action = "recoverable" if dry_run else "recovered"
    typer.echo(
        f"Scanned {scanned}: {recovered} {action}, {still_metadata} still metadata-only, "
        f"{missing_xml} missing XML, {render_failures} render failures"
    )


@app.command("backfill-document-versions")
def backfill_document_versions_command(
    source_paths: Annotated[
        list[str] | None,
        typer.Argument(help="Legislation source paths, e.g. ukpga/1971/77. Repeatable."),
    ] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="File of source paths, one per line ('#' comments allowed)."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report available/missing version dates without fetching them."),
    ] = False,
    max_versions: Annotated[
        int | None,
        typer.Option("--max-versions", min=1, help="Fetch at most this many missing versions per document."),
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
    """Backfill every advertised point-in-time expression of the given documents.

    Reads the dct:hasVersion list from each document's current CLML and ingests
    each dated expression with snapshot_date set to its validity-start date, so
    document_versions becomes the document's revision timeline. Dates already
    present are skipped; identical consecutive expressions dedupe via the
    canonical content hash.
    """
    paths = list(source_paths or [])
    if from_file is not None:
        for line in from_file.read_text().splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                paths.append(stripped)
    if not paths:
        raise click.ClickException("Pass source paths or --from-file.")

    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    report = PublishReport(collection="point-in-time", database_path="Postgres")
    total_available = total_missing = 0

    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        publish_run_id = None
        for source_path in paths:
            document = document_ref_from_source_path(source_path)
            try:
                current_xml = fetch_document_ref_xml(client, document=document)
                version_dates = parse_document_version_dates(current_xml)
            except Exception as error:
                report.failures.append(f"{source_path}: version list: {error}")
                typer.echo(f"{source_path}: failed to read version list: {error}")
                continue

            existing = {
                row[0].isoformat()
                for row in connection.execute(
                    """
                    select snapshot_date from document_versions
                    where document_id = %s and version_kind = 'point_in_time' and snapshot_date is not null
                    """,
                    ("/".join(document.path),),
                ).fetchall()
            }
            missing = [version_date for version_date in version_dates if version_date not in existing]
            total_available += len(version_dates)
            total_missing += len(missing)
            typer.echo(f"{source_path}: {len(version_dates)} versions advertised, {len(missing)} missing")
            if dry_run:
                continue
            if max_versions is not None:
                missing = missing[:max_versions]

            if publish_run_id is None:
                publish_run_id = create_publish_run(
                    connection,
                    collection="point-in-time",
                    snapshot_date=None,
                    legislation_types={document.legislation_type},
                )
            for index, version_date in enumerate(missing, start=1):
                report.scanned += 1
                try:
                    xml_content = fetch_document_ref_xml(client, document=document, at=version_date)
                    markdown = render_document_markdown_from_xml(xml_content)
                    published_version = publish_document_text(
                        connection,
                        source_path=document.path,
                        xml_content=xml_content,
                        markdown=markdown,
                        collection="point-in-time",
                        snapshot_date=version_date,
                        object_store=object_store,
                    )
                    record_publish_observation(connection, publish_run_id, published_version)
                except Exception as error:
                    report.failures.append(f"{source_path}@{version_date}: {error}")
                    continue
                report.published += 1
                if published_version.created:
                    report.created_versions += 1
                else:
                    report.reused_versions += 1
                if index % 25 == 0:
                    connection.commit()
                    typer.echo(f"{source_path}: {index} of {len(missing)} versions ingested")
            connection.commit()
            typer.echo(
                f"{source_path}: done ({report.created_versions} created, "
                f"{report.reused_versions} reused so far)"
            )
        if publish_run_id is not None:
            finish_publish_run(connection, publish_run_id)
        connection.commit()

    if dry_run:
        typer.echo(
            f"Dry run: {total_available} versions advertised, {total_missing} missing across {len(paths)} documents"
        )
        return
    typer.echo(render_publish_report(report))


@app.command("rerender-document-versions")
def rerender_document_versions_command(
    source_paths: Annotated[
        list[str] | None,
        typer.Argument(help="Legislation source paths, e.g. ukpga/1971/77. Repeatable."),
    ] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="File of source paths, one per line ('#' comments allowed)."),
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
    """Re-render every stored version of the given documents with the current converter, in place.

    Use after converter changes so all versions of a document are rendered by
    the same converter and diffs compare like with like. Follow with
    normalize-version-hashes to merge versions whose text became identical.
    """
    paths = list(source_paths or [])
    if from_file is not None:
        for line in from_file.read_text().splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                paths.append(stripped)
    if not paths:
        raise click.ClickException("Pass source paths or --from-file.")

    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    report = RerenderReport()
    with psycopg.connect(database_url) as connection:
        for source_path in paths:
            document = document_ref_from_source_path(source_path)
            rerender_document_versions(
                connection,
                object_store=object_store,
                document_id="/".join(document.path),
                report=report,
                render=render_document_markdown_from_xml,
                log=typer.echo,
            )
            connection.commit()
            typer.echo(f"{source_path}: {report.rerendered} re-rendered so far ({report.scanned} scanned)")
    typer.echo(render_rerender_report(report))


@app.command("poll-publication-log")
def poll_publication_log_command(
    since: Annotated[
        str | None,
        typer.Option("--since", help="First date to poll as YYYY-MM-DD. Defaults to the stored cursor."),
    ] = None,
    until: Annotated[
        str | None,
        typer.Option("--until", help="Last date to poll as YYYY-MM-DD. Defaults to today."),
    ] = None,
    max_documents: Annotated[
        int | None,
        typer.Option("--max-documents", min=1, help="Ingest at most this many documents; excess is reported."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="List what would be ingested without fetching XML or writing."),
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
    """Ingest legislation published since the last poll, via the Publication Log.

    Reads the last-polled date from publication_log_cursor, walks each day's
    XML legislation publication events, and re-ingests every affected document
    at today's snapshot date. Content-addressed version identity makes re-runs
    and overlapping polls free ("reused" instead of new versions). The cursor
    lives in whichever database is targeted, so the command is location-agnostic.
    """
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    today = date.today().isoformat()
    until = until or today

    with psycopg.connect(database_url) as connection:
        if since is None:
            row = connection.execute("select last_polled_date from publication_log_cursor where id = 1").fetchone()
            if row is None:
                raise click.ClickException(
                    "No stored cursor yet: pass --since YYYY-MM-DD for the first poll "
                    "(events before it will not be picked up)."
                )
            since = row[0].isoformat()
        if since > until:
            raise click.ClickException(f"--since {since} is after --until {until}.")

        poll_dates = _date_range(since, until)
        documents: dict[str, Any] = {}
        events_seen = 0
        with create_client(log=typer.echo) as client:
            for poll_date in poll_dates:
                events = fetch_publication_day_events(client, poll_date, log=typer.echo)
                events_seen += len(events)
                for event in events:
                    ref = event.document
                    if ref.legislation_type not in SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES:
                        continue
                    documents.setdefault("/".join(ref.path), ref)
                typer.echo(f"Publication Log {poll_date}: {len(events)} events, {len(documents)} documents so far")

            skipped = 0
            if max_documents is not None and len(documents) > max_documents:
                skipped = len(documents) - max_documents
                documents = dict(list(documents.items())[:max_documents])

            if dry_run:
                for source_path in documents:
                    typer.echo(source_path)
                typer.echo(
                    f"Dry run over {since}..{until}: {events_seen} events, "
                    f"{len(documents)} documents would be ingested, {skipped} over --max-documents"
                )
                return

            report = PublishReport(collection="point-in-time", snapshot_date=today, database_path="Postgres")
            publish_run_id = create_publish_run(
                connection,
                collection="point-in-time",
                snapshot_date=today,
                legislation_types={ref.legislation_type for ref in documents.values()},
            )
            for index, (source_path, ref) in enumerate(documents.items(), start=1):
                report.scanned += 1
                try:
                    xml_content = fetch_document_ref_xml(client, document=ref, at=today, fallback_to_latest=True)
                    markdown = render_document_markdown_from_xml(xml_content)
                    published_version = publish_document_text(
                        connection,
                        source_path=ref.path,
                        xml_content=xml_content,
                        markdown=markdown,
                        collection="point-in-time",
                        snapshot_date=today,
                        object_store=object_store,
                    )
                    record_publish_observation(connection, publish_run_id, published_version)
                except Exception as error:
                    report.failures.append(f"{source_path}: {error}")
                    continue
                report.published += 1
                if published_version.created:
                    report.created_versions += 1
                else:
                    report.reused_versions += 1
                if index % 100 == 0:
                    connection.commit()
                    typer.echo(
                        f"Ingested {index} of {len(documents)}: {report.created_versions} created, "
                        f"{report.reused_versions} reused, {len(report.failures)} failures"
                    )
            finish_publish_run(connection, publish_run_id)

            # Advancing the cursor past a capped run would silently drop the
            # skipped documents, so it only moves when the run covered everything.
            if skipped == 0:
                connection.execute(
                    """
                    insert into publication_log_cursor (id, last_polled_date, updated_at)
                    values (1, %s, now())
                    on conflict (id) do update set last_polled_date = excluded.last_polled_date, updated_at = now()
                    """,
                    (until,),
                )
            connection.commit()

    if skipped:
        typer.echo(
            f"Skipped {skipped} documents over --max-documents; cursor NOT advanced - "
            "re-run to continue (already-ingested documents dedupe to 'reused')."
        )
    else:
        typer.echo(f"Cursor advanced to {until}")
    typer.echo(render_publish_report(report))


def _date_range(since: str, until: str) -> list[str]:
    first = date.fromisoformat(since)
    last = date.fromisoformat(until)
    return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]


@app.command("normalize-version-hashes")
def normalize_version_hashes_command(
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Report what would change without writing."),
    ] = False,
    skip_merge: Annotated[
        bool,
        typer.Option("--skip-merge", help="Backfill canonical hashes without merging duplicate versions."),
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
    """Backfill date-invariant canonical hashes, then merge duplicate versions.

    Point-in-time CLML embeds the request date in its URIs, so historical
    catch-up runs created a new version per fetch even when nothing changed.
    This stamps canonical_sha256 on existing versions from stored Markdown and
    collapses versions of a document with identical canonical content into the
    earliest row.
    """
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    report = VersionHashNormalizationReport(dry_run=dry_run)
    with psycopg.connect(database_url) as connection:
        backfill_canonical_hashes(connection, object_store=object_store, report=report, log=typer.echo)
        if not skip_merge:
            merge_duplicate_version_rows(connection, report=report, log=typer.echo)
    typer.echo(render_version_hash_normalization_report(report))


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


@app.command("extract-legal-dates")
def extract_legal_dates_command(
    limit: Annotated[int | None, typer.Option("--limit", help="Process at most this many documents.")] = None,
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
    """Backfill documents.legal_date from stored CLML XML.

    Instruments carry <ukm:Made Date=...>, Acts carry <ukm:EnactmentDate Date=...>.
    Idempotent: re-run after ingestion to date newly published documents.
    """
    import re

    database_url = _database_url_or_raise(database_url)
    bucket_root = object_store_root / object_store_bucket
    date_pattern = re.compile(rb'<ukm:(Made|EnactmentDate)[^>]*\sDate="(\d{4}-\d{2}-\d{2})"')

    scanned = dated = missing_xml = no_date = implausible = 0
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            f"""
            select d.id, d.calendar_year, df.object_key
            from documents d
            join document_files df on df.version_id = d.latest_version_id and df.file_kind = 'clml_xml'
            where d.legal_date is null and df.object_key is not null
            order by d.id
            {"limit %s" if limit is not None else ""}
            """,
            (limit,) if limit is not None else (),
        ).fetchall()
        typer.echo(f"Found {len(rows)} undated documents with stored XML")
        for document_id, calendar_year, object_key in rows:
            scanned += 1
            xml_path = bucket_root / object_key
            if not xml_path.exists():
                missing_xml += 1
                continue
            match = date_pattern.search(xml_path.read_bytes())
            if match is None:
                no_date += 1
                continue
            legal_date = match.group(2).decode()
            # Source CLML contains occasional OCR/data-entry errors ("2950");
            # a legal date should sit within a couple of years of the series year.
            if calendar_year is not None and abs(int(legal_date[:4]) - calendar_year) > 2:
                implausible += 1
                continue
            kind = "made" if match.group(1) == b"Made" else "enacted"
            connection.execute(
                "update documents set legal_date = %s, legal_date_kind = %s where id = %s",
                (legal_date, kind, document_id),
            )
            dated += 1
            if dated % 20000 == 0:
                connection.commit()
                typer.echo(f"Dated {dated} of {scanned} scanned...")
        connection.commit()
        typer.echo(
            f"XML pass - scanned {scanned}: dated {dated}, no date in XML {no_date}, "
            f"implausible {implausible}, missing XML {missing_xml}"
        )

        # Second pass: PDF-backed instruments print their made date in the
        # preamble ("Made - - 28th April 2026"); recover it from LiteParse
        # text. OCR often clips the left margin, so tolerate a missing "M".
        text_pattern = re.compile(
            r"\b[Mm]?ade\b[\s.\-–—]{0,30}(\d{1,2})(?:st|nd|rd|th)?\s+"
            r"(January|February|March|April|May|June|July|August|September|October|November|December),?\s+(\d{4})"
        )
        months = {
            month: index + 1
            for index, month in enumerate(
                "January February March April May June July August September October November December".split()
            )
        }
        text_rows = connection.execute(
            f"""
            select d.id, d.calendar_year, df.object_key
            from documents d
            join document_files df on df.version_id = d.latest_version_id and df.file_kind = 'markdown'
            where d.legal_date is null and df.object_key like 'markdown/liteparse/%%'
            order by d.id
            {"limit %s" if limit is not None else ""}
            """,
            (limit,) if limit is not None else (),
        ).fetchall()
        text_dated = text_scanned = 0
        for document_id, calendar_year, object_key in text_rows:
            text_scanned += 1
            markdown_path = bucket_root / object_key
            if not markdown_path.exists():
                continue
            match = text_pattern.search(markdown_path.read_text(errors="replace")[:6000])
            if match is None:
                continue
            year_value = int(match.group(3))
            if calendar_year is not None and abs(year_value - calendar_year) > 2:
                continue
            try:
                legal_date = date(year_value, months[match.group(2)], int(match.group(1))).isoformat()
            except ValueError:
                continue
            connection.execute(
                "update documents set legal_date = %s, legal_date_kind = 'made' where id = %s",
                (legal_date, document_id),
            )
            text_dated += 1
        connection.commit()
    typer.echo(f"PDF-text pass - scanned {text_scanned}: dated {text_dated}")


@app.command("cache-dynamic-pdfs")
def cache_dynamic_pdfs_command(
    legislation_type: Annotated[
        str | None,
        typer.Option("--legislation-type", help="Limit to one legislation type code."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, help="Maximum PDFs to cache.")] = 100,
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.0, help="Pause between downloads."),
    ] = 0.5,
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
    """Cache PDFs that only exist behind legislation.gov.uk's on-demand generator.

    These cannot be proxied by the production Workers (the generator refuses
    Cloudflare egress), so they must be fetched from local egress into the
    object store, from where the drain ships them to R2.
    """
    database_url = _database_url_or_raise(database_url)
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    with create_client(log=typer.echo) as client, psycopg.connect(database_url) as connection:
        report = cache_dynamic_only_pdfs(
            connection,
            client=client,
            object_store=object_store,
            legislation_type=legislation_type,
            limit=limit,
            delay_seconds=delay_seconds,
        )
        connection.commit()
    typer.echo(f"Scanned {report.scanned} dynamic-only PDFs; cached {report.cached}, {len(report.failures)} failures")
    for failure in report.failures[:20]:
        typer.echo(f"  {failure}")


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
    delay_seconds: Annotated[
        float,
        typer.Option("--delay-seconds", min=0.0, help="Pause between source PDF downloads."),
    ] = 0.0,
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
            delay_seconds=delay_seconds,
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
