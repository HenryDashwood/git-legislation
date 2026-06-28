"""HTTP client for the read API consumed by the HTMX app."""

from collections.abc import Iterator
from typing import Any

import httpx


class ReadApiClient:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def list_documents(
        self,
        *,
        legislation_type: str | None = None,
        year: int | None = None,
        number: str | None = None,
        status: str | None = None,
        extent: str | None = None,
        metadata_only: bool | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = _without_none(
            {
                "legislation_type": legislation_type,
                "year": year,
                "number": number,
                "status": status,
                "extent": extent,
                "metadata_only": metadata_only,
                "q": q,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._get_json("/documents", params=params)

    def get_document(self, document_path: str) -> dict[str, Any]:
        return self._get_json(f"/documents/{document_path}")

    def list_versions(self, document_path: str) -> dict[str, Any]:
        return self._get_json(f"/documents/{document_path}/versions")

    def list_provisions(self, version_id: str) -> dict[str, Any]:
        return self._get_json(f"/versions/{version_id}/provisions")

    def list_files(self, version_id: str) -> dict[str, Any]:
        return self._get_json(f"/versions/{version_id}/files")

    def get_content(self, version_id: str) -> str:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.get(f"/versions/{version_id}/content")
            response.raise_for_status()
            return response.text

    def get_preferred_markdown(self, version_id: str) -> tuple[str, str]:
        files = self.list_files(version_id).get("items", [])
        for prefix, label in (
            ("markdown/marker/", "PDF-derived Marker text"),
            ("markdown/liteparse/", "PDF-derived LiteParse text"),
        ):
            markdown_file = next(
                (
                    file
                    for file in files
                    if file.get("file_kind") == "markdown" and str(file.get("object_key") or "").startswith(prefix)
                ),
                None,
            )
            if markdown_file is not None:
                return self._get_text(f"/files/{markdown_file['id']}/content"), label
        return self.get_content(version_id), "Canonical CLML text"

    def get_pdf_source_url(self, version_id: str) -> str:
        files = self.list_files(version_id).get("items", [])
        pdf_file = next((file for file in files if file.get("file_kind") == "pdf" and file.get("source_url")), None)
        if pdf_file is None:
            raise FileNotFoundError(f"No PDF source URL found for {version_id}")
        return str(pdf_file["source_url"])

    def get_pdf_content_path(self, version_id: str) -> str | None:
        files = self.list_files(version_id).get("items", [])
        pdf_file = next((file for file in files if file.get("file_kind") == "pdf" and file.get("object_key")), None)
        if pdf_file is None:
            return None
        return f"/files/{pdf_file['id']}/content"

    def iter_pdf_source(self, source_url: str) -> Iterator[bytes]:
        if source_url.startswith("/"):
            url = f"{self.base_url}{source_url}"
        else:
            url = source_url
        timeout = httpx.Timeout(120.0, connect=10.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                yield from response.iter_bytes()

    def _get_json(self, path: str, params: dict[str, str | int | bool] | None = None) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def _get_text(self, path: str) -> str:
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.get(path)
            response.raise_for_status()
            return response.text


def _without_none(params: dict[str, str | int | bool | None]) -> dict[str, str | int | bool]:
    return {key: value for key, value in params.items() if value is not None and value != ""}
