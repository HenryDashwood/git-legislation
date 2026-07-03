"""HTMX web frontend for browsing the legislation corpus."""

import threading
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import markdown
import uvicorn
from api_client import ReadApiClient
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from settings import WebSettings, load_settings

from fetchers.legislationdotgovdotuk import SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES
from git_legislation_api.types import LEGISLATION_TYPE_LABELS, LegislationTypeCode

APP_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_ROOT / "templates")

# Ordered chronologically for the corpus timeline; slugs pick jurisdiction colours.
LEGISLATION_TYPE_GROUPS: list[tuple[str, str, list[LegislationTypeCode]]] = [
    (
        "Historical parliaments",
        "historic",
        [
            LegislationTypeCode.AEP,
            LegislationTypeCode.AOSP,
            LegislationTypeCode.AIP,
            LegislationTypeCode.APGB,
            LegislationTypeCode.GBPPA,
            LegislationTypeCode.GBLA,
        ],
    ),
    (
        "UK Parliament",
        "uk",
        [
            LegislationTypeCode.UKPGA,
            LegislationTypeCode.UKLA,
            LegislationTypeCode.UKPPA,
            LegislationTypeCode.UKSI,
            LegislationTypeCode.UKMO,
            LegislationTypeCode.UKCM,
            LegislationTypeCode.UKCI,
        ],
    ),
    (
        "Scotland",
        "scotland",
        [LegislationTypeCode.ASP, LegislationTypeCode.SSI],
    ),
    (
        "Wales",
        "wales",
        [
            LegislationTypeCode.ASC,
            LegislationTypeCode.ANAW,
            LegislationTypeCode.MWA,
            LegislationTypeCode.WSI,
        ],
    ),
    (
        "Northern Ireland",
        "ni",
        [
            LegislationTypeCode.NIA,
            LegislationTypeCode.NISR,
            LegislationTypeCode.NISI,
            LegislationTypeCode.APNI,
            LegislationTypeCode.MNIA,
            LegislationTypeCode.NISRO,
        ],
    ),
]

TYPE_LABELS_BY_CODE = {code.value: label for code, label in LEGISLATION_TYPE_LABELS.items()}

PDF_CACHE_MAX_ENTRIES = 8
PDF_CACHE_MAX_ITEM_BYTES = 32 * 1024 * 1024

# Acts are cited by chapter ("c. 14"); instruments, rules, and measures by number ("No. 14").
CHAPTER_CITED_TYPES = {
    code.value for code, label in LEGISLATION_TYPE_LABELS.items() if "Act" in label or "Personal" in label
}


def create_app(api_client: Any | None = None, settings: WebSettings | None = None) -> FastAPI:
    web_settings = settings or load_settings()
    app = FastAPI(title="git-legislation web", version="0.1.0")
    app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
    app.state.api_client = api_client or ReadApiClient(web_settings.api_base_url)
    app.state.pdf_cache = OrderedDict()
    app.state.pdf_cache_lock = threading.Lock()

    @app.middleware("http")
    async def drop_empty_query_params(request: Request, call_next: Any) -> Any:
        # HTML forms submit every field, so a blank year arrives as "year=" and
        # fails int/enum validation. Treat empty values as not provided.
        if request.url.query:
            filtered = [(key, value) for key, value in request.query_params.multi_items() if value != ""]
            request.scope["query_string"] = urlencode(filtered).encode()
        return await call_next(request)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse("/documents")

    @app.get("/documents")
    def documents_page(
        request: Request,
        legislation_type: LegislationTypeCode | None = None,
        year: int | None = None,
        number: str | None = None,
        status: str | None = None,
        extent: str | None = None,
        metadata_only: bool | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> Any:
        searched = any(
            value is not None and value != ""
            for value in (legislation_type, year, number, status, extent, metadata_only, q)
        )
        if not searched:
            try:
                summary_items = request.app.state.api_client.get_corpus_summary().get("items", [])
            except Exception:
                summary_items = None
            return templates.TemplateResponse(
                request,
                "documents/index.html",
                {
                    "timeline": _timeline(summary_items),
                    "legislation_types": [
                        {"code": code.value, "label": LEGISLATION_TYPE_LABELS[code]} for code in LegislationTypeCode
                    ],
                },
            )
        result = _list_documents(
            request,
            legislation_type=legislation_type,
            year=year,
            number=number,
            status=status,
            extent=extent,
            metadata_only=metadata_only,
            q=q,
            limit=limit,
            offset=offset,
        )
        return templates.TemplateResponse(
            request,
            "documents/search.html",
            {
                **result,
                **_filter_context(
                    legislation_type=legislation_type,
                    year=year,
                    number=number,
                    status=status,
                    extent=extent,
                    metadata_only=metadata_only,
                    q=q,
                ),
            },
        )

    @app.get("/documents/results")
    def document_results(
        request: Request,
        legislation_type: LegislationTypeCode | None = None,
        year: int | None = None,
        number: str | None = None,
        status: str | None = None,
        extent: str | None = None,
        metadata_only: bool | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
    ) -> Any:
        result = _list_documents(
            request,
            legislation_type=legislation_type,
            year=year,
            number=number,
            status=status,
            extent=extent,
            metadata_only=metadata_only,
            q=q,
            limit=limit,
            offset=offset,
        )
        return templates.TemplateResponse(request, "documents/_results.html", result)

    @app.get("/documents/{document_path:path}")
    def document_detail(request: Request, document_path: str) -> Any:
        try:
            document = request.app.state.api_client.get_document(document_path)
            versions = request.app.state.api_client.list_versions(document_path).get("items", [])
            latest = document.get("latest_version") if document else None
            latest_id = latest.get("id") if latest else None
            files = request.app.state.api_client.list_files(str(latest_id)).get("items", []) if latest_id else []
            markdown_content, content_label = (
                request.app.state.api_client.get_preferred_markdown(str(latest_id))
                if latest_id
                else ("", "No parsed text")
            )
            rendered_content = _render_markdown(markdown_content) if markdown_content else Markup("")
            pdf_file = _first_file(files, "pdf")
            error = None
        except Exception as exc:
            document = None
            versions = []
            files = []
            rendered_content = Markup("")
            content_label = "No parsed text"
            pdf_file = None
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "documents/detail.html",
            {
                "document": document,
                "type_label": TYPE_LABELS_BY_CODE.get(document.get("legislation_type", "")) if document else None,
                "chapter_cited": document.get("legislation_type") in CHAPTER_CITED_TYPES if document else False,
                "versions": versions,
                "files": files,
                "rendered_content": rendered_content,
                "content_label": content_label,
                "pdf_file": pdf_file,
                "error": error,
            },
        )

    @app.get("/versions/{version_id:path}/provisions")
    def version_provisions(request: Request, version_id: str) -> Any:
        try:
            provisions = request.app.state.api_client.list_provisions(version_id).get("items", [])
            error = None
        except Exception as exc:
            provisions = []
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "versions/_provisions.html",
            {"version_id": version_id, "provisions": provisions, "error": error},
        )

    @app.get("/versions/{version_id:path}/files")
    def version_files(request: Request, version_id: str) -> Any:
        try:
            files = request.app.state.api_client.list_files(version_id).get("items", [])
            error = None
        except Exception as exc:
            files = []
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "versions/_files.html",
            {"version_id": version_id, "files": files, "error": error},
        )

    @app.get("/versions/{version_id:path}/content")
    def version_content(request: Request, version_id: str) -> Any:
        try:
            content = request.app.state.api_client.get_content(version_id)
            error = None
        except Exception as exc:
            content = ""
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "versions/_content.html",
            {"version_id": version_id, "content": content, "error": error},
        )

    @app.get("/versions/{version_id:path}/pdf")
    def version_pdf(request: Request, version_id: str) -> Response:
        # The browser's PDF viewer requests this URL twice (a sniff, then the
        # real load), and legislation.gov.uk generates PDFs on demand, slowly.
        # Buffer the whole file and keep recent ones so only the first request
        # for a document pays the upstream cost.
        cache: OrderedDict[str, bytes] = request.app.state.pdf_cache
        lock: threading.Lock = request.app.state.pdf_cache_lock
        with lock:
            content = cache.get(version_id)
            if content is not None:
                cache.move_to_end(version_id)
        if content is None:
            content_path = request.app.state.api_client.get_pdf_content_path(version_id)
            if content_path is not None:
                source_url = content_path
            else:
                try:
                    source_url = request.app.state.api_client.get_pdf_source_url(version_id)
                except FileNotFoundError as exc:
                    raise HTTPException(status_code=404, detail="PDF source not found") from exc
            content = b"".join(request.app.state.api_client.iter_pdf_source(source_url))
            if len(content) <= PDF_CACHE_MAX_ITEM_BYTES:
                with lock:
                    cache[version_id] = content
                    cache.move_to_end(version_id)
                    while len(cache) > PDF_CACHE_MAX_ENTRIES:
                        cache.popitem(last=False)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="source.pdf"'},
        )

    return app


def _list_documents(
    request: Request,
    *,
    legislation_type: LegislationTypeCode | None,
    year: int | None,
    number: str | None,
    status: str | None,
    extent: str | None,
    metadata_only: bool | None,
    q: str | None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    base_context = {
        "type_labels": TYPE_LABELS_BY_CODE,
        "chapter_cited_types": CHAPTER_CITED_TYPES,
        "prev_url": None,
        "next_url": None,
    }
    try:
        response = request.app.state.api_client.list_documents(
            legislation_type=legislation_type.value if legislation_type is not None else None,
            year=year,
            number=number,
            status=status,
            extent=extent,
            metadata_only=metadata_only,
            q=q,
            limit=limit,
            offset=offset,
        )
        documents = response.get("items", [])
        return {
            **base_context,
            "documents": documents,
            "limit": response.get("limit", limit),
            "offset": response.get("offset", offset),
            "error": None,
            "prev_url": _page_url(
                legislation_type=legislation_type,
                year=year,
                number=number,
                status=status,
                extent=extent,
                metadata_only=metadata_only,
                q=q,
                limit=limit,
                offset=max(offset - limit, 0),
            )
            if offset > 0
            else None,
            "next_url": _page_url(
                legislation_type=legislation_type,
                year=year,
                number=number,
                status=status,
                extent=extent,
                metadata_only=metadata_only,
                q=q,
                limit=limit,
                offset=offset + limit,
            )
            if len(documents) == limit
            else None,
        }
    except Exception as exc:
        return {**base_context, "documents": [], "limit": limit, "offset": offset, "error": str(exc)}


def _page_url(
    *,
    legislation_type: LegislationTypeCode | None,
    year: int | None,
    number: str | None,
    status: str | None,
    extent: str | None,
    metadata_only: bool | None,
    q: str | None,
    limit: int,
    offset: int,
) -> str:
    params: dict[str, str | int] = {}
    if legislation_type is not None:
        params["legislation_type"] = legislation_type.value
    if year is not None:
        params["year"] = year
    for key, value in (("number", number), ("status", status), ("extent", extent), ("q", q)):
        if value:
            params[key] = value
    if metadata_only is not None:
        params["metadata_only"] = "true" if metadata_only else "false"
    if limit != 50:
        params["limit"] = limit
    if offset > 0:
        params["offset"] = offset
    return f"/documents?{urlencode(params)}"


def _timeline(summary_items: list[dict[str, Any]] | None) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in summary_items or []:
        code = item.get("legislation_type")
        count = item.get("document_count")
        if isinstance(code, str) and isinstance(count, int):
            counts[code] = count

    spans = SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES
    start_year = min(span.start_year for span in spans.values())
    end_year = date.today().year
    total_years = end_year - start_year

    total_documents = 0
    groups: list[dict[str, Any]] = []
    for title, slug, codes in LEGISLATION_TYPE_GROUPS:
        rows: list[dict[str, Any]] = []
        for code in sorted(codes, key=lambda item: spans[item.value].start_year):
            span = spans[code.value]
            first = span.start_year
            last = span.end_year or end_year
            count = counts.get(code.value)
            total_documents += count or 0
            rows.append(
                {
                    "code": code.value,
                    "label": LEGISLATION_TYPE_LABELS[code],
                    "first_year": first,
                    "last_label": str(span.end_year) if span.end_year is not None else "present",
                    "count_label": f"{count:,}" if count else None,
                    "left_pct": round((first - start_year) / total_years * 100, 2),
                    "width_pct": round(max((last - first) / total_years * 100, 0.6), 2),
                }
            )
        groups.append({"title": title, "slug": slug, "rows": rows})

    ticks = [
        {"year": tick_year, "left_pct": round((tick_year - start_year) / total_years * 100, 2)}
        for tick_year in range(1300, end_year, 100)
    ]
    return {
        "groups": groups,
        "ticks": ticks,
        "start_year": start_year,
        "end_year": end_year,
        "total_label": f"{total_documents:,}" if total_documents else None,
    }


def _filter_context(
    *,
    legislation_type: LegislationTypeCode | None,
    year: int | None,
    number: str | None,
    status: str | None,
    extent: str | None,
    metadata_only: bool | None,
    q: str | None,
) -> dict[str, Any]:
    return {
        "legislation_types": [
            {"code": legislation_type.value, "label": LEGISLATION_TYPE_LABELS[legislation_type]}
            for legislation_type in LegislationTypeCode
        ],
        "status_options": ["Prospective", "Revoked", "Repealed", "Current", "Unknown"],
        "metadata_options": [
            {"value": "", "label": "All records"},
            {"value": "false", "label": "Full parsed text"},
            {"value": "true", "label": "Metadata/PDF-backed only"},
        ],
        "filters": {
            "legislation_type": legislation_type.value if legislation_type is not None else "",
            "year": year or "",
            "number": number or "",
            "status": status or "",
            "extent": extent or "",
            "metadata_only": _metadata_filter_value(metadata_only),
            "q": q or "",
        },
    }


def _metadata_filter_value(metadata_only: bool | None) -> str:
    if metadata_only is None:
        return ""
    return "true" if metadata_only else "false"


def _first_file(files: list[dict[str, Any]], file_kind: str) -> dict[str, Any] | None:
    return next((file for file in files if file.get("file_kind") == file_kind), None)


def _render_markdown(content: str) -> Markup:
    rendered = markdown.markdown(_strip_frontmatter(content), extensions=["extra", "sane_lists"])
    return Markup(rendered)


def _strip_frontmatter(content: str) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return content
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip()
    return content


app = create_app()


def run() -> None:
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True, app_dir=str(APP_ROOT))
