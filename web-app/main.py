"""HTMX web frontend for browsing the legislation corpus."""

from pathlib import Path
from typing import Any

import markdown
import uvicorn
from api_client import ReadApiClient
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from settings import WebSettings, load_settings

from git_legislation_api.types import LEGISLATION_TYPE_LABELS, LegislationTypeCode

APP_ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=APP_ROOT / "templates")


def create_app(api_client: Any | None = None, settings: WebSettings | None = None) -> FastAPI:
    web_settings = settings or load_settings()
    app = FastAPI(title="git-legislation web", version="0.1.0")
    app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")
    app.state.api_client = api_client or ReadApiClient(web_settings.api_base_url)

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
        )
        return templates.TemplateResponse(
            request,
            "documents/index.html",
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
    def version_pdf(request: Request, version_id: str) -> StreamingResponse:
        content_path = request.app.state.api_client.get_pdf_content_path(version_id)
        if content_path is not None:
            source_url = content_path
        else:
            try:
                source_url = request.app.state.api_client.get_pdf_source_url(version_id)
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="PDF source not found") from exc
        return StreamingResponse(
            request.app.state.api_client.iter_pdf_source(source_url),
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
        return {
            "documents": response.get("items", []),
            "limit": response.get("limit", limit),
            "offset": response.get("offset", offset),
            "error": None,
        }
    except Exception as exc:
        return {"documents": [], "limit": limit, "offset": offset, "error": str(exc)}


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
