"""FastAPI application for read-only legislation access."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from object_store import LocalObjectStore

from .db import connection_from_pool, create_pool
from .repositories import PostgresRepository
from .schemas import (
    DocumentDetail,
    DocumentListResponse,
    FileListResponse,
    ProvisionDetail,
    ProvisionListResponse,
    VersionListResponse,
    VersionSummary,
)
from .settings import ApiSettings, load_settings
from .storage import LocalContentStore
from .types import LegislationTypeCode


def create_app(
    *,
    repository: Any | None = None,
    storage: Any | None = None,
    settings: ApiSettings | None = None,
) -> FastAPI:
    api_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = None
        if repository is None:
            if api_settings.database_url is None:
                raise RuntimeError("Set DB_URL to run the API.")
            pool = create_pool(api_settings.database_url)
            pool.open()
            app.state.repository = PostgresRepository(lambda: connection_from_pool(pool))
        else:
            app.state.repository = repository

        if storage is None:
            object_store = LocalObjectStore(
                root=api_settings.object_store_root, bucket=api_settings.object_store_bucket
            )
            app.state.storage = LocalContentStore(object_store)
        else:
            app.state.storage = storage

        try:
            yield
        finally:
            if pool is not None:
                pool.close()

    app = FastAPI(title="git-legislation API", version="0.1.0", lifespan=lifespan)
    if repository is not None:
        app.state.repository = repository
    if storage is not None:
        app.state.storage = storage
    if api_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(api_settings.cors_origins),
            allow_methods=["GET", "OPTIONS"],
            allow_headers=["*"],
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/documents", response_model=DocumentListResponse)
    def list_documents(
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
    ) -> dict[str, Any]:
        items = request.app.state.repository.list_documents(
            legislation_type=str(legislation_type) if legislation_type is not None else None,
            year=year,
            number=number,
            status=status,
            extent=extent,
            metadata_only=metadata_only,
            q=q,
            limit=limit,
            offset=offset,
        )
        return {"items": items, "limit": limit, "offset": offset}

    @app.get("/documents/{document_path:path}/versions", response_model=VersionListResponse)
    def list_versions(request: Request, document_path: str) -> dict[str, Any]:
        return {"items": request.app.state.repository.list_versions(_clean_path_id(document_path))}

    @app.get("/documents/{document_path:path}/versions/latest", response_model=VersionSummary)
    def get_latest_version(request: Request, document_path: str) -> dict[str, Any]:
        document = request.app.state.repository.get_document(_clean_path_id(document_path))
        if document is None or document.get("latest_version") is None:
            raise HTTPException(status_code=404, detail="Latest version not found")
        return document["latest_version"]

    @app.get("/documents/{document_path:path}", response_model=DocumentDetail)
    def get_document(request: Request, document_path: str) -> dict[str, Any]:
        document = request.app.state.repository.get_document(_clean_path_id(document_path))
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return document

    @app.get("/versions/{version_id:path}/provisions", response_model=ProvisionListResponse)
    def list_provisions(request: Request, version_id: str) -> dict[str, Any]:
        return {"items": request.app.state.repository.list_provisions(_clean_path_id(version_id))}

    @app.get("/versions/{version_id:path}/provisions/{anchor}", response_model=ProvisionDetail)
    def get_provision(request: Request, version_id: str, anchor: str) -> dict[str, Any]:
        provision = request.app.state.repository.get_provision(_clean_path_id(version_id), anchor)
        if provision is None:
            raise HTTPException(status_code=404, detail="Provision not found")
        return provision

    @app.get("/versions/{version_id:path}/files", response_model=FileListResponse)
    def list_files(request: Request, version_id: str) -> dict[str, Any]:
        return {"items": request.app.state.repository.list_files(_clean_path_id(version_id))}

    @app.get("/versions/{version_id:path}/content")
    def get_version_content(
        request: Request,
        version_id: str,
        kind: str = Query("markdown", pattern="^(markdown|clml_xml)$"),
    ) -> FileResponse:
        file_record = request.app.state.repository.get_canonical_file(_clean_path_id(version_id), kind)
        if file_record is None or file_record.get("object_key") is None:
            raise HTTPException(status_code=404, detail="Canonical content not found")
        sha256 = str(file_record.get("object_sha256") or file_record.get("sha256") or "")
        content_type = str(file_record.get("content_type") or "application/octet-stream")
        try:
            content = request.app.state.storage.resolve(
                object_key=str(file_record["object_key"]),
                sha256=sha256,
                content_type=content_type,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Content object not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            content.path,
            media_type=content.content_type,
            headers={"ETag": f'"{content.sha256}"'},
        )

    @app.get("/files/{file_id}/content")
    def get_file_content(request: Request, file_id: int) -> FileResponse:
        file_record = request.app.state.repository.get_file(file_id)
        if file_record is None or file_record.get("object_key") is None:
            raise HTTPException(status_code=404, detail="File content not found")
        sha256 = str(file_record.get("object_sha256") or file_record.get("sha256") or "")
        content_type = str(file_record.get("content_type") or "application/octet-stream")
        try:
            content = request.app.state.storage.resolve(
                object_key=str(file_record["object_key"]),
                sha256=sha256,
                content_type=content_type,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Content object not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return FileResponse(
            content.path,
            media_type=content.content_type,
            headers={"ETag": f'"{content.sha256}"'},
        )

    @app.get("/versions/{version_id:path}", response_model=VersionSummary)
    def get_version(request: Request, version_id: str) -> dict[str, Any]:
        version = request.app.state.repository.get_version(_clean_path_id(version_id))
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        return version

    return app


app = create_app()


def run() -> None:
    uvicorn.run("git_legislation_api.main:app", host="127.0.0.1", port=8000, reload=True)


def _clean_path_id(value: str) -> str:
    return value.strip("/")
