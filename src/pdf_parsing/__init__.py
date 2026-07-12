"""Experimental PDF parsing for PDF-backed legislation records."""

import hashlib
import json
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from object_store import LocalObjectStore, StoredObject
from publishing import insert_document_file, upsert_storage_object


@dataclass(frozen=True)
class PdfParseCandidate:
    document_file_id: int
    document_id: str
    version_id: str
    source_url: str
    object_key: str | None
    source_path: tuple[str, ...]
    version_kind: str
    snapshot_date: str | None


@dataclass(frozen=True)
class ParsedPdfArtifacts:
    pdf_object: StoredObject
    text_object: StoredObject
    report_object: StoredObject
    word_count: int
    character_count: int


@dataclass(frozen=True)
class LiteparseMarkdownCandidate:
    document_id: str
    version_id: str
    source_url: str
    report_object_key: str
    source_path: tuple[str, ...]
    version_kind: str
    snapshot_date: str | None


@dataclass
class PdfParseSampleReport:
    scanned: int = 0
    parsed: int = 0
    failures: list[str] = field(default_factory=list)
    artifacts: list[ParsedPdfArtifacts] = field(default_factory=list)


@dataclass
class LiteparseMarkdownReport:
    scanned: int = 0
    normalized: int = 0
    failures: list[str] = field(default_factory=list)
    markdown_object_keys: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReconstructedLine:
    text: str
    role: str
    page: int | None
    x_min: float
    x_max: float
    y: float
    confidence: float


class FetchResponseLike(Protocol):
    status_code: int
    content: bytes

    def raise_for_status(self) -> object: ...


class FetchClient(Protocol):
    def get(self, url: str) -> FetchResponseLike: ...


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

# legislation.gov.uk generates many PDFs on demand and answers 202 while the
# render runs; a few short retries usually collect the finished file.
PDF_GENERATION_RETRIES = 3
PDF_GENERATION_RETRY_DELAY_SECONDS = 5.0


def parse_pdf_sample(
    connection: Any,
    *,
    client: FetchClient,
    object_store: LocalObjectStore,
    at: str | None = None,
    legislation_type: str | None = None,
    limit: int = 10,
    only_metadata: bool = True,
    force: bool = False,
    lit_executable: str = "lit",
    no_ocr: bool = False,
    target_pages: str | None = None,
    delay_seconds: float = 0.0,
    command_runner: CommandRunner | None = None,
) -> PdfParseSampleReport:
    candidates = select_pdf_parse_candidates(
        connection,
        at=at,
        legislation_type=legislation_type,
        limit=limit,
        only_metadata=only_metadata,
        force=force,
    )
    report = PdfParseSampleReport(scanned=len(candidates))
    for index, candidate in enumerate(candidates):
        if delay_seconds > 0 and index > 0:
            time.sleep(delay_seconds)
        try:
            artifacts = parse_pdf_candidate(
                connection,
                candidate,
                client=client,
                object_store=object_store,
                lit_executable=lit_executable,
                no_ocr=no_ocr,
                target_pages=target_pages,
                command_runner=command_runner,
            )
        except Exception as error:
            report.failures.append(f"{candidate.document_id} {candidate.source_url}: {error}")
            if _is_permanent_pdf_failure(error):
                _record_pdf_failure(connection, candidate.document_file_id)
            continue
        report.parsed += 1
        report.artifacts.append(artifacts)
    return report


def _is_permanent_pdf_failure(error: Exception) -> bool:
    """Missing or non-PDF upstream responses never heal; rate limits and
    connection problems do, so those stay retryable."""
    message = str(error)
    return "not a PDF" in message or "status 404" in message


def _ensure_pdf_failures_table(connection: Any) -> None:
    # Operational scratch table (not schema-managed): keeps permanently
    # failing candidates from riding along in every subsequent batch.
    connection.execute(
        """
        create table if not exists pdf_fetch_failures (
            document_file_id bigint primary key,
            attempts integer not null default 0,
            last_attempt timestamptz not null default now()
        )
        """,
        (),
    )


def _record_pdf_failure(connection: Any, document_file_id: int) -> None:
    _ensure_pdf_failures_table(connection)
    connection.execute(
        """
        insert into pdf_fetch_failures (document_file_id, attempts)
        values (%s, 1)
        on conflict (document_file_id) do update
        set attempts = pdf_fetch_failures.attempts + 1, last_attempt = now()
        """,
        (document_file_id,),
    )


def normalize_liteparse_markdown_sample(
    connection: Any,
    *,
    object_store: LocalObjectStore,
    at: str | None = None,
    legislation_type: str | None = None,
    limit: int = 10,
    force: bool = False,
) -> LiteparseMarkdownReport:
    candidates = select_liteparse_markdown_candidates(
        connection,
        at=at,
        legislation_type=legislation_type,
        limit=limit,
        force=force,
    )
    report = LiteparseMarkdownReport(scanned=len(candidates))
    for candidate in candidates:
        try:
            markdown_object = normalize_liteparse_markdown_candidate(
                connection,
                candidate,
                object_store=object_store,
            )
        except Exception as error:
            report.failures.append(f"{candidate.document_id} {candidate.source_url}: {error}")
            continue
        report.normalized += 1
        report.markdown_object_keys.append(markdown_object.key)
    return report


def cache_document_pdf(
    connection: Any,
    *,
    client: FetchClient,
    object_store: LocalObjectStore,
    source_path: tuple[str, ...],
    at: str | None,
) -> StoredObject:
    candidate = select_document_pdf_candidate(connection, source_path=source_path, at=at)
    return ensure_pdf_cached(connection, candidate, client=client, object_store=object_store)


def cache_document_marker_markdown(
    connection: Any,
    *,
    client: FetchClient,
    object_store: LocalObjectStore,
    source_path: tuple[str, ...],
    at: str | None,
    marker_executable: str = "marker_single",
    command_runner: CommandRunner | None = None,
) -> StoredObject:
    candidate = select_document_pdf_candidate(connection, source_path=source_path, at=at)
    pdf_object = ensure_pdf_cached(connection, candidate, client=client, object_store=object_store)
    markdown = run_marker(
        pdf_object.path,
        marker_executable=marker_executable,
        command_runner=command_runner,
    )
    markdown_object = object_store.put_text(
        markdown,
        key=marker_markdown_object_key(candidate, pdf_object),
        content_type="text/markdown",
    )
    upsert_storage_object(connection, markdown_object, source_url=candidate.source_url)
    insert_document_file(
        connection,
        document_id=candidate.document_id,
        version_id=candidate.version_id,
        file_kind="markdown",
        object_key=markdown_object.key,
        sha256=markdown_object.sha256,
        source_url=candidate.source_url,
        is_canonical=False,
    )
    return markdown_object


def select_document_pdf_candidate(
    connection: Any,
    *,
    source_path: tuple[str, ...],
    at: str | None,
) -> PdfParseCandidate:
    clauses = ["df.file_kind = 'pdf'", "df.source_url is not null", "df.version_id is not null", "d.source_path = %s"]
    params: list[Any] = [list(source_path)]
    if at is not None:
        clauses.append("dv.snapshot_date = %s")
        params.append(at)
    rows = connection.execute(
        f"""
        select
            df.id,
            df.document_id,
            df.version_id,
            df.source_url,
            df.object_key,
            d.source_path,
            dv.version_kind,
            dv.snapshot_date::text
        from document_files df
        join documents d on d.id = df.document_id
        join document_versions dv on dv.id = df.version_id
        where {" and ".join(clauses)}
        order by df.is_canonical desc, df.id
        limit 1
        """,
        tuple(params),
    ).fetchall()
    if not rows:
        snapshot_hint = f" at {at}" if at is not None else ""
        raise ValueError(f"No PDF file row found for {'/'.join(source_path)}{snapshot_hint}.")
    row = rows[0]
    return PdfParseCandidate(
        document_file_id=int(row[0]),
        document_id=str(row[1]),
        version_id=str(row[2]),
        source_url=str(row[3]),
        object_key=str(row[4]) if row[4] is not None else None,
        source_path=tuple(str(part) for part in row[5]),
        version_kind=str(row[6]),
        snapshot_date=str(row[7]) if row[7] is not None else None,
    )


def select_pdf_parse_candidates(
    connection: Any,
    *,
    at: str | None,
    legislation_type: str | None,
    limit: int,
    only_metadata: bool,
    force: bool,
) -> tuple[PdfParseCandidate, ...]:
    _ensure_pdf_failures_table(connection)
    clauses = [
        "df.file_kind = 'pdf'",
        "df.source_url is not null",
        "df.version_id is not null",
        # Skip candidates that have permanently failed 3+ times (missing or
        # non-PDF upstream); tracked in the pdf_fetch_failures scratch table.
        """
        not exists (
            select 1 from pdf_fetch_failures pf
            where pf.document_file_id = df.id and pf.attempts >= 3
        )
        """,
    ]
    params: list[Any] = []
    if at is not None:
        clauses.append("dv.snapshot_date = %s")
        params.append(at)
    if legislation_type is not None:
        clauses.append("d.legislation_type = %s")
        params.append(legislation_type)
    if only_metadata:
        clauses.append("dv.is_metadata_only")
    if not force:
        clauses.append(
            """
            not exists (
                select 1
                from document_files parsed
                where parsed.version_id = df.version_id
                  and parsed.file_kind = 'extracted_text'
                  and parsed.source_url = df.source_url
            )
            """
        )
    params.append(limit)
    rows = connection.execute(
        f"""
        select
            df.id,
            df.document_id,
            df.version_id,
            df.source_url,
            df.object_key,
            d.source_path,
            dv.version_kind,
            dv.snapshot_date::text
        from document_files df
        join documents d on d.id = df.document_id
        join document_versions dv on dv.id = df.version_id
        where {" and ".join(clauses)}
        order by dv.is_metadata_only desc, d.calendar_year nulls first, d.id, df.source_url
        limit %s
        """,
        tuple(params),
    ).fetchall()
    return tuple(
        PdfParseCandidate(
            document_file_id=int(row[0]),
            document_id=str(row[1]),
            version_id=str(row[2]),
            source_url=str(row[3]),
            object_key=str(row[4]) if row[4] is not None else None,
            source_path=tuple(str(part) for part in row[5]),
            version_kind=str(row[6]),
            snapshot_date=str(row[7]) if row[7] is not None else None,
        )
        for row in rows
    )


def select_liteparse_markdown_candidates(
    connection: Any,
    *,
    at: str | None,
    legislation_type: str | None,
    limit: int,
    force: bool,
) -> tuple[LiteparseMarkdownCandidate, ...]:
    clauses = [
        "df.file_kind = 'report'",
        "df.object_key is not null",
        "df.object_key like 'reports/liteparse/%%'",
        "df.version_id is not null",
    ]
    params: list[Any] = []
    if at is not None:
        clauses.append("dv.snapshot_date = %s")
        params.append(at)
    if legislation_type is not None:
        clauses.append("d.legislation_type = %s")
        params.append(legislation_type)
    if not force:
        clauses.append(
            """
            not exists (
                select 1
                from document_files markdown
                where markdown.version_id = df.version_id
                  and markdown.file_kind = 'markdown'
                  and markdown.source_url = df.source_url
                  and markdown.object_key like 'markdown/liteparse/%%'
            )
            """
        )
    params.append(limit)
    rows = connection.execute(
        f"""
        select
            df.document_id,
            df.version_id,
            df.source_url,
            df.object_key,
            d.source_path,
            dv.version_kind,
            dv.snapshot_date::text
        from document_files df
        join documents d on d.id = df.document_id
        join document_versions dv on dv.id = df.version_id
        where {" and ".join(clauses)}
        order by dv.is_metadata_only desc, d.calendar_year nulls first, d.id, df.source_url
        limit %s
        """,
        tuple(params),
    ).fetchall()
    return tuple(
        LiteparseMarkdownCandidate(
            document_id=str(row[0]),
            version_id=str(row[1]),
            source_url=str(row[2]),
            report_object_key=str(row[3]),
            source_path=tuple(str(part) for part in row[4]),
            version_kind=str(row[5]),
            snapshot_date=str(row[6]) if row[6] is not None else None,
        )
        for row in rows
    )


def parse_pdf_candidate(
    connection: Any,
    candidate: PdfParseCandidate,
    *,
    client: FetchClient,
    object_store: LocalObjectStore,
    lit_executable: str,
    no_ocr: bool,
    target_pages: str | None,
    command_runner: CommandRunner | None = None,
) -> ParsedPdfArtifacts:
    pdf_object = ensure_pdf_cached(connection, candidate, client=client, object_store=object_store)
    text_content, report_content = run_liteparse(
        pdf_object.path,
        lit_executable=lit_executable,
        no_ocr=no_ocr,
        target_pages=target_pages,
        command_runner=command_runner,
    )
    text_object = object_store.put_text(
        text_content,
        key=liteparse_text_object_key(candidate, pdf_object),
        content_type="text/plain",
    )
    report_object = object_store.put_text(
        report_content,
        key=liteparse_report_object_key(candidate, pdf_object),
        content_type="application/json",
    )
    upsert_storage_object(connection, text_object, source_url=candidate.source_url)
    upsert_storage_object(connection, report_object, source_url=candidate.source_url)
    insert_document_file(
        connection,
        document_id=candidate.document_id,
        version_id=candidate.version_id,
        file_kind="extracted_text",
        object_key=text_object.key,
        sha256=text_object.sha256,
        source_url=candidate.source_url,
        is_canonical=False,
    )
    insert_document_file(
        connection,
        document_id=candidate.document_id,
        version_id=candidate.version_id,
        file_kind="report",
        object_key=report_object.key,
        sha256=report_object.sha256,
        source_url=candidate.source_url,
        is_canonical=False,
    )
    return ParsedPdfArtifacts(
        pdf_object=pdf_object,
        text_object=text_object,
        report_object=report_object,
        word_count=len(re.findall(r"\b\w+\b", text_content)),
        character_count=len(text_content),
    )


def normalize_liteparse_markdown_candidate(
    connection: Any,
    candidate: LiteparseMarkdownCandidate,
    *,
    object_store: LocalObjectStore,
) -> StoredObject:
    report_path = object_store.path_for_key(candidate.report_object_key)
    liteparse_json = json.loads(report_path.read_text())
    markdown = liteparse_json_to_markdown(liteparse_json, title=_fallback_markdown_title(candidate))
    markdown_object = object_store.put_text(
        markdown,
        key=liteparse_markdown_object_key(candidate),
        content_type="text/markdown",
    )
    upsert_storage_object(connection, markdown_object, source_url=candidate.source_url)
    insert_document_file(
        connection,
        document_id=candidate.document_id,
        version_id=candidate.version_id,
        file_kind="markdown",
        object_key=markdown_object.key,
        sha256=markdown_object.sha256,
        source_url=candidate.source_url,
        is_canonical=False,
    )
    return markdown_object


def select_dynamic_only_pdf_candidates(
    connection: Any,
    *,
    legislation_type: str | None,
    limit: int,
) -> tuple[PdfParseCandidate, ...]:
    """Latest-version PDF rows whose document has no print-version (/pdfs/) URL
    and no cached object — the class legislation.gov.uk refuses to serve to
    Cloudflare Workers, so they must be cached from local egress."""
    _ensure_pdf_failures_table(connection)
    clauses = [
        "df.file_kind = 'pdf'",
        "df.source_url is not null",
        "df.object_key is null",
        """
        not exists (
            select 1 from pdf_fetch_failures pf
            where pf.document_file_id = df.id and pf.attempts >= 3
        )
        """,
        """
        not exists (
            select 1 from document_files o
            where o.version_id = df.version_id and o.file_kind = 'pdf'
              and (o.object_key is not null or o.source_url like '%%/pdfs/%%')
        )
        """,
    ]
    params: list[Any] = []
    if legislation_type is not None:
        clauses.append("d.legislation_type = %s")
        params.append(legislation_type)
    params.append(limit)
    rows = connection.execute(
        f"""
        select distinct on (df.version_id)
            df.id, df.document_id, df.version_id, df.source_url, df.object_key,
            d.source_path, dv.version_kind, dv.snapshot_date::text
        from document_files df
        join documents d on d.id = df.document_id and d.latest_version_id = df.version_id
        join document_versions dv on dv.id = df.version_id
        where {" and ".join(clauses)}
        order by df.version_id, df.id
        limit %s
        """,
        tuple(params),
    ).fetchall()
    return tuple(
        PdfParseCandidate(
            document_file_id=int(row[0]),
            document_id=str(row[1]),
            version_id=str(row[2]),
            source_url=str(row[3]),
            object_key=str(row[4]) if row[4] is not None else None,
            source_path=tuple(str(part) for part in row[5]),
            version_kind=str(row[6]),
            snapshot_date=str(row[7]) if row[7] is not None else None,
        )
        for row in rows
    )


@dataclass
class DynamicPdfCacheReport:
    scanned: int = 0
    cached: int = 0
    failures: list[str] = field(default_factory=list)


def cache_dynamic_only_pdfs(
    connection: Any,
    *,
    client: FetchClient,
    object_store: LocalObjectStore,
    legislation_type: str | None = None,
    limit: int = 10,
    delay_seconds: float = 0.0,
) -> DynamicPdfCacheReport:
    candidates = select_dynamic_only_pdf_candidates(
        connection,
        legislation_type=legislation_type,
        limit=limit,
    )
    report = DynamicPdfCacheReport(scanned=len(candidates))
    for index, candidate in enumerate(candidates):
        if delay_seconds > 0 and index > 0:
            time.sleep(delay_seconds)
        try:
            ensure_pdf_cached(connection, candidate, client=client, object_store=object_store)
        except Exception as error:
            report.failures.append(f"{candidate.document_id} {candidate.source_url}: {error}")
            if _is_permanent_pdf_failure(error):
                _record_pdf_failure(connection, candidate.document_file_id)
            continue
        report.cached += 1
    return report


def ensure_pdf_cached(
    connection: Any,
    candidate: PdfParseCandidate,
    *,
    client: FetchClient,
    object_store: LocalObjectStore,
) -> StoredObject:
    key = candidate.object_key or pdf_object_key(candidate)
    pdf_path = object_store.path_for_key(key)
    if pdf_path.exists() and not _looks_like_pdf(pdf_path.read_bytes()):
        # Self-heal cache entries poisoned by upstream HTML error pages.
        pdf_path.unlink()
    if not pdf_path.exists():
        response = client.get(candidate.source_url)
        response.raise_for_status()
        generation_attempts = 0
        while response.status_code == 202 and generation_attempts < PDF_GENERATION_RETRIES:
            generation_attempts += 1
            time.sleep(PDF_GENERATION_RETRY_DELAY_SECONDS)
            response = client.get(candidate.source_url)
            response.raise_for_status()
        if not _looks_like_pdf(response.content):
            raise ValueError(f"Response from {candidate.source_url} is not a PDF")
        content_type = "application/pdf"
        pdf_object = object_store.put_bytes(response.content, key=key, content_type=content_type)
    else:
        pdf_object = StoredObject(
            bucket=object_store.bucket,
            key=key,
            path=pdf_path,
            sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
            byte_size=pdf_path.stat().st_size,
            content_type="application/pdf",
        )
    upsert_storage_object(connection, pdf_object, source_url=candidate.source_url)
    connection.execute(
        """
        update document_files
        set object_key = %s,
            sha256 = %s
        where id = %s
        """,
        (pdf_object.key, pdf_object.sha256, candidate.document_file_id),
    )
    return pdf_object


def liteparse_json_to_markdown(liteparse_json: dict[str, Any], *, title: str | None = None) -> str:
    pages = liteparse_json.get("pages")
    if not isinstance(pages, list):
        raise ValueError("LiteParse JSON does not contain a pages array.")

    markdown_lines: list[str] = []
    if title:
        markdown_lines.extend([f"# {title}", ""])

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_number = page.get("page")
        reconstructed_lines = _page_reconstructed_lines(page)
        if not reconstructed_lines:
            continue
        if markdown_lines:
            markdown_lines.append("")
        markdown_lines.append(f"<!-- Page {page_number} -->")
        markdown_lines.extend(_reconstructed_lines_to_markdown(reconstructed_lines))

    return "\n".join(markdown_lines).strip() + "\n"


def _page_reconstructed_lines(page: dict[str, Any]) -> list[ReconstructedLine]:
    items = [item for item in page.get("text_items", []) if isinstance(item, dict)]
    text = str(page.get("text") or "")
    if not items:
        return [
            ReconstructedLine(
                text=_cleanup_ocr_line(line),
                role="body",
                page=_page_number(page),
                x_min=0,
                x_max=0,
                y=float(index),
                confidence=1.0,
            )
            for index, line in enumerate(text.splitlines())
            if _cleanup_ocr_line(line)
        ]

    grouped_lines = _group_text_items_by_line(items)
    page_number = _page_number(page)
    body_left = _body_left_edge(grouped_lines)
    if text.strip():
        return _layout_text_reconstructed_lines(
            text,
            page_number=page_number,
            crop_marginalia=page_number == 1 and _has_left_marginalia(grouped_lines, body_left=body_left),
        )
    reconstructed: list[ReconstructedLine] = []
    for line_items in grouped_lines:
        role = _line_role(line_items, body_left=body_left, page_number=page_number)
        if role == "noise":
            continue
        selected_items = _line_body_items(line_items, body_left=body_left) if role == "body" else line_items
        line = _cleanup_ocr_line(_items_to_text(selected_items))
        if _looks_like_noise(line):
            continue
        reconstructed.append(
            ReconstructedLine(
                text=line,
                role=role,
                page=page_number,
                x_min=min(_item_float(item, "x") for item in selected_items),
                x_max=max(_item_float(item, "x") + _item_float(item, "width") for item in selected_items),
                y=_line_y(selected_items),
                confidence=sum(_item_float(item, "confidence", 1.0) for item in selected_items) / len(selected_items),
            )
        )
    return _merge_broken_coordinate_lines(reconstructed)


def _layout_text_reconstructed_lines(
    text: str,
    *,
    page_number: int | None,
    crop_marginalia: bool,
) -> list[ReconstructedLine]:
    lines: list[ReconstructedLine] = []
    for index, raw_line in enumerate(text.splitlines()):
        source_line = raw_line[24:] if crop_marginalia and len(raw_line) > 24 else raw_line
        line = _cleanup_ocr_line(source_line)
        if _looks_like_noise(line):
            continue
        role = "body"
        if _looks_like_heading(line) and index <= 3:
            role = "heading"
        elif page_number == 1 and index <= 5 and "HEREAS" not in line:
            role = "title"
        lines.append(
            ReconstructedLine(
                text=line,
                role=role,
                page=page_number,
                x_min=0,
                x_max=0,
                y=float(index),
                confidence=1.0,
            )
        )
    return _merge_layout_title_lines(lines)


def _group_text_items_by_line(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    useful_items = [
        item
        for item in items
        if str(item.get("text", "")).strip()
        and _item_float(item, "confidence", 1.0) >= 0.30
        and _item_float(item, "height", 0.0) > 0
        and not _looks_like_edge_noise(item)
    ]
    useful_items.sort(key=lambda item: (_item_center_y(item), _item_float(item, "x")))
    lines: list[list[dict[str, Any]]] = []
    for item in useful_items:
        y = _item_center_y(item)
        if not lines or abs(_line_center_y(lines[-1]) - y) > max(6.0, _item_float(item, "height", 8.0) * 0.75):
            lines.append([item])
        else:
            lines[-1].append(item)
    return [sorted(line, key=lambda item: _item_float(item, "x")) for line in lines]


def _reconstructed_lines_to_markdown(lines: list[ReconstructedLine]) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line.role in {"heading", "title"}:
            if current:
                paragraphs.extend([" ".join(current), ""])
                current = []
            paragraphs.extend([f"## {_heading_text(line.text)}", ""])
            continue
        if line.role == "marginal":
            if current:
                paragraphs.extend([" ".join(current), ""])
                current = []
            paragraphs.extend([f"> {line.text}", ""])
            continue
        current.append(line.text)
        if line.text.endswith((".", ";", ":")):
            paragraphs.extend([" ".join(current), ""])
            current = []
    if current:
        paragraphs.append(" ".join(current))
    while paragraphs and paragraphs[-1] == "":
        paragraphs.pop()
    return paragraphs


def run_liteparse(
    pdf_path: Path,
    *,
    lit_executable: str,
    no_ocr: bool,
    target_pages: str | None,
    command_runner: CommandRunner | None = None,
) -> tuple[str, str]:
    runner = command_runner or _run_command
    with tempfile.TemporaryDirectory() as temp_dir:
        text_path = Path(temp_dir) / "liteparse.txt"
        report_path = Path(temp_dir) / "liteparse.json"
        base_args = [lit_executable, "parse", "--quiet"]
        if no_ocr:
            base_args.append("--no-ocr")
        if target_pages is not None:
            base_args.extend(["--target-pages", target_pages])
        runner([*base_args, "--format", "text", "-o", str(text_path), str(pdf_path)])
        runner([*base_args, "--format", "json", "-o", str(report_path), str(pdf_path)])
        return text_path.read_text(), report_path.read_text()


def run_marker(
    pdf_path: Path,
    *,
    marker_executable: str,
    command_runner: CommandRunner | None = None,
) -> str:
    runner = command_runner or _run_command
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        runner(
            [
                marker_executable,
                str(pdf_path),
                "--output_format",
                "markdown",
                "--output_dir",
                str(output_dir),
                "--disable_image_extraction",
            ]
        )
        markdown_paths = sorted(output_dir.rglob("*.md"))
        if not markdown_paths:
            raise RuntimeError("Marker did not produce a Markdown file.")
        return markdown_paths[0].read_text()


def _run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise RuntimeError(
            "LiteParse CLI not found. Install it with `uv pip install liteparse` or `pip install liteparse`."
        ) from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or error.stdout.strip() or str(error)
        raise RuntimeError(f"LiteParse failed: {message}") from error


def _looks_like_pdf(content: bytes) -> bool:
    return content.lstrip()[:5].startswith(b"%PDF")


def pdf_object_key(candidate: PdfParseCandidate) -> str:
    collection = _collection_path(candidate)
    source_name = _pdf_source_name(candidate.source_url)
    return (Path("pdf") / collection / Path(*candidate.source_path) / source_name).as_posix()


def liteparse_text_object_key(candidate: PdfParseCandidate, pdf_object: StoredObject) -> str:
    return (
        Path("extracted-text")
        / "liteparse"
        / _collection_path(candidate)
        / Path(*candidate.source_path)
        / _output_stem(pdf_object, ".txt")
    ).as_posix()


def liteparse_report_object_key(candidate: PdfParseCandidate, pdf_object: StoredObject) -> str:
    return (
        Path("reports")
        / "liteparse"
        / _collection_path(candidate)
        / Path(*candidate.source_path)
        / _output_stem(pdf_object, ".json")
    ).as_posix()


def liteparse_markdown_object_key(candidate: LiteparseMarkdownCandidate) -> str:
    return (
        Path("markdown")
        / "liteparse"
        / _collection_path(candidate)
        / Path(*candidate.source_path[:-1])
        / f"{candidate.source_path[-1]}.md"
    ).as_posix()


def marker_markdown_object_key(candidate: PdfParseCandidate, pdf_object: StoredObject) -> str:
    return (
        Path("markdown")
        / "marker"
        / _collection_path(candidate)
        / Path(*candidate.source_path)
        / _output_stem(pdf_object, ".md")
    ).as_posix()


def render_pdf_parse_sample_report(report: PdfParseSampleReport) -> str:
    lines = [
        f"Parsed {report.parsed} PDF-backed documents with LiteParse",
        f"Scanned {report.scanned} candidate PDFs; {len(report.failures)} failures",
    ]
    if report.artifacts:
        total_words = sum(artifact.word_count for artifact in report.artifacts)
        total_chars = sum(artifact.character_count for artifact in report.artifacts)
        lines.append(f"Extracted {total_words} words across {total_chars} characters")
    if report.failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in report.failures[:20])
        if len(report.failures) > 20:
            lines.append(f"- ... {len(report.failures) - 20} more")
    return "\n".join(lines)


def render_liteparse_markdown_report(report: LiteparseMarkdownReport) -> str:
    lines = [
        f"Normalized {report.normalized} LiteParse reports to Markdown",
        f"Scanned {report.scanned} reports; {len(report.failures)} failures",
    ]
    if report.markdown_object_keys:
        lines.append("Markdown objects:")
        lines.extend(f"- {key}" for key in report.markdown_object_keys[:20])
        if len(report.markdown_object_keys) > 20:
            lines.append(f"- ... {len(report.markdown_object_keys) - 20} more")
    if report.failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in report.failures[:20])
        if len(report.failures) > 20:
            lines.append(f"- ... {len(report.failures) - 20} more")
    return "\n".join(lines)


def _collection_path(candidate: PdfParseCandidate | LiteparseMarkdownCandidate) -> Path:
    if candidate.version_kind == "point_in_time":
        if candidate.snapshot_date is None:
            raise ValueError("Point-in-time PDF objects require a snapshot date.")
        return Path("point-in-time") / candidate.snapshot_date
    if candidate.version_kind == "enacted":
        return Path("enacted")
    if candidate.version_kind == "current":
        return Path("current")
    raise ValueError(f"Unknown version kind: {candidate.version_kind}")


def _pdf_source_name(source_url: str) -> str:
    parsed_name = Path(urlparse(source_url).path).name
    suffix = Path(parsed_name).suffix.lower()
    if suffix != ".pdf":
        suffix = ".pdf"
    stem = Path(parsed_name).stem or "source"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "source"
    digest = hashlib.sha256(source_url.encode()).hexdigest()[:12]
    return f"{safe_stem}-{digest}{suffix}"


def _output_stem(pdf_object: StoredObject, suffix: str) -> str:
    return f"{Path(pdf_object.key).stem}{suffix}"


def _page_number(page: dict[str, Any]) -> int | None:
    value = page.get("page")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _body_left_edge(lines: list[list[dict[str, Any]]]) -> float:
    candidates: list[float] = []
    for line in lines:
        if len(line) < 4:
            continue
        x_min = min(_item_float(item, "x") for item in line)
        x_max = max(_item_float(item, "x") + _item_float(item, "width") for item in line)
        if x_max - x_min >= 220:
            candidates.append(x_min)
    if not candidates:
        return 72.0
    candidates.sort()
    return max(72.0, candidates[len(candidates) // 2] - 8.0)


def _has_left_marginalia(lines: list[list[dict[str, Any]]], *, body_left: float) -> bool:
    count = 0
    for line in lines:
        left_text = " ".join(str(item.get("text", "")) for item in line if _item_float(item, "x") < body_left - 8)
        right_text = " ".join(str(item.get("text", "")) for item in line if _item_float(item, "x") >= body_left - 8)
        if left_text.strip() and right_text.strip():
            count += 1
    return count >= 3


def _line_role(line: list[dict[str, Any]], *, body_left: float, page_number: int | None) -> str:
    text = _normalize_markdown_line(_items_to_text(line))
    x_min = min(_item_float(item, "x") for item in line)
    x_max = max(_item_float(item, "x") + _item_float(item, "width") for item in line)
    y = _line_y(line)
    width = x_max - x_min
    if _looks_like_noise(text):
        return "noise"
    if _looks_like_heading(text) and 15 <= y <= 45 and width < 160:
        return "heading"
    if page_number == 1 and y < 78 and width >= 180:
        return "title"
    right_items = [item for item in line if _item_float(item, "x") >= body_left - 6]
    if page_number == 1 and x_min < body_left - 12 and len(right_items) < 2 and y >= 78:
        return "marginal"
    if x_min > 590 and len(text) <= 12:
        return "noise"
    if y > 430 and len(text) <= 20:
        return "noise"
    return "body"


def _line_body_items(line: list[dict[str, Any]], *, body_left: float) -> list[dict[str, Any]]:
    right_items = [item for item in line if _item_float(item, "x") >= body_left - 6]
    return right_items or line


def _items_to_text(items: list[dict[str, Any]]) -> str:
    tokens: list[str] = []
    for item in sorted(items, key=lambda value: _item_float(value, "x")):
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        tokens.append(text)
    return " ".join(tokens)


def _merge_broken_coordinate_lines(lines: list[ReconstructedLine]) -> list[ReconstructedLine]:
    merged: list[ReconstructedLine] = []
    for line in lines:
        if (
            merged
            and line.role == merged[-1].role == "body"
            and abs(line.y - merged[-1].y) < 7
            and line.x_min > merged[-1].x_min
        ):
            previous = merged[-1]
            merged[-1] = ReconstructedLine(
                text=_cleanup_ocr_line(f"{previous.text} {line.text}"),
                role=previous.role,
                page=previous.page,
                x_min=min(previous.x_min, line.x_min),
                x_max=max(previous.x_max, line.x_max),
                y=min(previous.y, line.y),
                confidence=(previous.confidence + line.confidence) / 2,
            )
            continue
        merged.append(line)
    return merged


def _merge_layout_title_lines(lines: list[ReconstructedLine]) -> list[ReconstructedLine]:
    merged: list[ReconstructedLine] = []
    pending_title: ReconstructedLine | None = None
    for line in lines:
        if line.role == "title":
            if pending_title is None:
                pending_title = line
            else:
                pending_title = ReconstructedLine(
                    text=_cleanup_ocr_line(f"{pending_title.text} {line.text}"),
                    role="title",
                    page=pending_title.page,
                    x_min=pending_title.x_min,
                    x_max=pending_title.x_max,
                    y=pending_title.y,
                    confidence=(pending_title.confidence + line.confidence) / 2,
                )
            continue
        if pending_title is not None:
            merged.append(pending_title)
            pending_title = None
        merged.append(line)
    if pending_title is not None:
        merged.append(pending_title)
    return merged


def _heading_text(line: str) -> str:
    cleaned = re.sub(r"\b(?:wy|can)\b", "", line, flags=re.IGNORECASE)
    cleaned = _cleanup_ocr_line(cleaned)
    if cleaned.upper() == "CHAPTER":
        return "Chapter"
    return cleaned.title()


def _line_y(items: list[dict[str, Any]]) -> float:
    return sum(_item_float(item, "y") for item in items) / len(items)


def _line_center_y(items: list[dict[str, Any]]) -> float:
    return sum(_item_center_y(item) for item in items) / len(items)


def _item_center_y(item: dict[str, Any]) -> float:
    return _item_float(item, "y") + (_item_float(item, "height") / 2)


def _item_float(item: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = item.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _looks_like_edge_noise(item: dict[str, Any]) -> bool:
    text = str(item.get("text", "")).strip()
    if not text:
        return True
    x = _item_float(item, "x")
    confidence = _item_float(item, "confidence", 1.0)
    if x > 590 and (len(text) <= 4 or confidence < 0.6):
        return True
    if len(text) <= 2 and confidence < 0.5:
        return True
    return False


def _cleanup_ocr_line(line: str) -> str:
    normalized = _normalize_markdown_line(line)
    replacements = {
        "A%Y HEREAS": "WHEREAS",
        "Y HEREAS": "WHEREAS",
        "Ax Acre": "An Acte",
        "Groundf": "Grounde",
        "pfitable": "profitable",
        "espially": "especially",
        "Inhabitant¢": "Inhabitants",
        "Coast¢": "Coaste",
        "inPrupted": "interrupted",
        "Spiricuall": "Spirituall",
        "pent Parliam’": "present Parliament",
        "Parliam’": "Parliament",
        "ssid": "said",
        "Deven": "Devon",
        "whet": "where",
        "cat by": "cast by",
        "Seamarke": "Seamarke",
        "Bostemen": "Boatemen",
        "Fifie": "Fiftie",
        "contvnue": "continue",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"\bCan\s+(An Acte)\b", r"\1", normalized)
    normalized = re.sub(r"\bwy\b", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_markdown_line(line: str) -> str:
    normalized = re.sub(r"\s+", " ", line).strip()
    normalized = normalized.replace(' w"in ', " within ")
    normalized = normalized.replace(" w* ", " with ")
    normalized = normalized.replace(" wth ", " with ")
    return normalized


def _looks_like_noise(line: str) -> bool:
    if not line:
        return True
    if len(line) <= 3 and not line.isalnum():
        return True
    if re.fullmatch(r"[\W_]+", line):
        return True
    return False


def _looks_like_heading(line: str) -> bool:
    alpha = re.sub(r"[^A-Za-z]", "", line)
    return bool(alpha) and len(line) <= 80 and alpha.isupper()


def _fallback_markdown_title(candidate: LiteparseMarkdownCandidate) -> str:
    return candidate.document_id
