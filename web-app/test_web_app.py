from typing import Any

from fastapi.testclient import TestClient
from main import create_app


class FakeApiClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

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
        self.calls.append(
            (
                "list_documents",
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
                },
            )
        )
        return {
            "items": [
                {
                    "id": "ukpga/2026/14",
                    "legislation_type": "ukpga",
                    "year": "2026",
                    "calendar_year": 2026,
                    "number": "14",
                    "title": "Industry and Exports (Financial Assistance) Act 2026",
                    "document_uri": "https://www.legislation.gov.uk/ukpga/2026/14",
                    "status": "Prospective",
                    "extent": "E+W+S+N.I.",
                    "latest_version_id": "point-in-time:2026-05-05:ukpga/2026/14",
                    "created_at": "2026-05-05T12:00:00Z",
                    "updated_at": "2026-05-05T12:00:00Z",
                }
            ],
            "limit": limit,
            "offset": offset,
        }

    def get_corpus_summary(self) -> dict[str, Any]:
        self.calls.append(("get_corpus_summary", {}))
        return {
            "items": [
                {"legislation_type": "ukpga", "document_count": 3600, "first_year": 1801, "last_year": 2026},
                {"legislation_type": "wsi", "document_count": 8123, "first_year": 1999, "last_year": 2026},
            ]
        }

    def get_document(self, document_path: str) -> dict[str, Any]:
        self.calls.append(("get_document", {"document_path": document_path}))
        return {
            "id": "ukpga/2026/14",
            "legislation_type": "ukpga",
            "year": "2026",
            "calendar_year": 2026,
            "number": "14",
            "title": "Industry and Exports (Financial Assistance) Act 2026",
            "document_uri": "https://www.legislation.gov.uk/ukpga/2026/14",
            "status": "Prospective",
            "extent": "E+W+S+N.I.",
            "latest_version_id": "point-in-time:2026-05-05:ukpga/2026/14",
            "created_at": "2026-05-05T12:00:00Z",
            "updated_at": "2026-05-05T12:00:00Z",
            "latest_version": {
                "id": "point-in-time:2026-05-05:ukpga/2026/14",
                "document_id": "ukpga/2026/14",
                "version_kind": "point_in_time",
                "snapshot_date": "2026-05-05",
                "source_uri": "https://www.legislation.gov.uk/ukpga/2026/14/2026-05-05/data.xml",
                "source_object_key": "xml/point-in-time/2026-05-05/ukpga/2026/14/data.xml",
                "markdown_object_key": "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
                "word_count": 1234,
                "is_metadata_only": False,
                "created_at": "2026-05-05T12:00:00Z",
            },
        }

    def list_versions(self, document_path: str) -> dict[str, Any]:
        self.calls.append(("list_versions", {"document_path": document_path}))
        return {"items": [self.get_document(document_path)["latest_version"]]}

    def list_provisions(self, version_id: str) -> dict[str, Any]:
        self.calls.append(("list_provisions", {"version_id": version_id}))
        return {
            "items": [
                {
                    "id": f"{version_id}:provision:1",
                    "version_id": version_id,
                    "document_id": "ukpga/2026/14",
                    "ordinal": 1,
                    "provision_type": "section",
                    "number": "1",
                    "heading": "Limit on selective financial assistance for industry",
                    "anchor": "1-limit-on-selective-financial-assistance-for-industry",
                }
            ]
        }

    def list_files(self, version_id: str) -> dict[str, Any]:
        self.calls.append(("list_files", {"version_id": version_id}))
        return {
            "items": [
                {
                    "id": 1,
                    "document_id": "ukpga/2026/14",
                    "version_id": version_id,
                    "file_kind": "markdown",
                    "source_url": None,
                    "object_key": "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
                    "sha256": "abc123",
                    "is_canonical": True,
                    "bucket": "legislation",
                    "byte_size": 18,
                    "content_type": "text/markdown",
                    "object_sha256": "abc123",
                    "created_at": "2026-05-05T12:00:00Z",
                },
                {
                    "id": 2,
                    "document_id": "ukpga/2026/14",
                    "version_id": version_id,
                    "file_kind": "pdf",
                    "source_url": "https://www.legislation.gov.uk/ukpga/2026/14/data.pdf",
                    "object_key": None,
                    "sha256": None,
                    "is_canonical": False,
                    "bucket": None,
                    "byte_size": None,
                    "content_type": None,
                    "object_sha256": None,
                    "created_at": "2026-05-05T12:00:00Z",
                },
                {
                    "id": 3,
                    "document_id": "ukpga/2026/14",
                    "version_id": version_id,
                    "file_kind": "markdown",
                    "source_url": "https://www.legislation.gov.uk/ukpga/2026/14/data.pdf",
                    "object_key": "markdown/marker/point-in-time/2026-05-05/ukpga/2026/14/data.md",
                    "sha256": "def456",
                    "is_canonical": False,
                    "bucket": "legislation",
                    "byte_size": 36,
                    "content_type": "text/markdown",
                    "object_sha256": "def456",
                    "created_at": "2026-05-05T12:00:00Z",
                },
            ]
        }

    def get_content(self, version_id: str) -> str:
        self.calls.append(("get_content", {"version_id": version_id}))
        return """---
title: "Industry and Exports"
document_uri: "https://www.legislation.gov.uk/ukpga/2026/14"
---

# Industry and Exports

## 1 Limit on selective financial assistance

Example markdown.
"""

    def get_pdf_source_url(self, version_id: str) -> str:
        self.calls.append(("get_pdf_source_url", {"version_id": version_id}))
        return "https://www.legislation.gov.uk/ukpga/2026/14/data.pdf"

    def get_pdf_content_path(self, version_id: str) -> str | None:
        self.calls.append(("get_pdf_content_path", {"version_id": version_id}))
        return None

    def iter_pdf_source(self, source_url: str):
        self.calls.append(("iter_pdf_source", {"source_url": source_url}))
        yield b"%PDF-1.4 example"

    def get_preferred_markdown(self, version_id: str) -> tuple[str, str]:
        self.calls.append(("get_preferred_markdown", {"version_id": version_id}))
        return "# Industry and Exports\n\nMarker extracted main text.", "PDF-derived Marker text"


def test_root_redirects_to_documents() -> None:
    client = TestClient(create_app(api_client=FakeApiClient()))

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/documents"


def test_documents_page_without_filters_renders_landing_with_corpus_map() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    response = client.get("/documents")

    assert response.status_code == 200
    assert "statute book" in response.text
    assert "UK Public General Acts" in response.text
    assert 'href="/documents?legislation_type=ukpga"' in response.text
    assert "3,600" in response.text
    assert "11,723 documents" in response.text
    assert "Industry and Exports" not in response.text
    assert [call[0] for call in fake_api.calls] == ["get_corpus_summary"]


def test_documents_page_landing_survives_summary_api_failure() -> None:
    class NoSummaryApiClient(FakeApiClient):
        def get_corpus_summary(self) -> dict[str, Any]:
            raise RuntimeError("API unavailable")

    client = TestClient(create_app(api_client=NoSummaryApiClient()))

    response = client.get("/documents")

    assert response.status_code == 200
    assert "UK Public General Acts" in response.text
    assert 'href="/documents?legislation_type=ukpga"' in response.text


def test_documents_page_with_filters_renders_search_results() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    response = client.get("/documents?legislation_type=ukpga")

    assert response.status_code == 200
    assert "Search results" in response.text
    assert 'name="legislation_type"' in response.text
    assert "UK Public General Acts" in response.text
    assert "Industry and Exports" in response.text
    assert fake_api.calls[0][0] == "list_documents"


def test_documents_page_treats_empty_form_fields_as_absent() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    response = client.get("/documents?q=exports&legislation_type=&year=&number=&status=&extent=&metadata_only=")

    assert response.status_code == 200
    assert "Industry and Exports" in response.text
    assert fake_api.calls[0] == (
        "list_documents",
        {
            "legislation_type": None,
            "year": None,
            "number": None,
            "status": None,
            "extent": None,
            "metadata_only": None,
            "q": "exports",
            "limit": 50,
            "offset": 0,
        },
    )


def test_documents_page_with_only_empty_form_fields_renders_landing() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    response = client.get("/documents?q=&legislation_type=&year=")

    assert response.status_code == 200
    assert "statute book" in response.text
    assert not any(call[0] == "list_documents" for call in fake_api.calls)


def test_documents_page_paginates_with_prev_and_next_links() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    response = client.get("/documents?legislation_type=ukpga&limit=1&offset=1")

    assert response.status_code == 200
    assert "/documents?legislation_type=ukpga&amp;limit=1" in response.text
    assert "/documents?legislation_type=ukpga&amp;limit=1&amp;offset=2" in response.text
    assert "Previous page" in response.text
    assert "Next page" in response.text


def test_documents_results_partial_passes_filters() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    response = client.get(
        "/documents/results?legislation_type=ukpga&year=2026&number=14&status=Prospective"
        "&extent=E%2BW%2BS%2BN.I.&metadata_only=false&q=exports"
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert "Industry and Exports" in response.text
    assert fake_api.calls[0] == (
        "list_documents",
        {
            "legislation_type": "ukpga",
            "year": 2026,
            "number": "14",
            "status": "Prospective",
            "extent": "E+W+S+N.I.",
            "metadata_only": False,
            "q": "exports",
            "limit": 50,
            "offset": 0,
        },
    )


def test_document_detail_renders_latest_version_and_htmx_controls() -> None:
    client = TestClient(create_app(api_client=FakeApiClient()))

    response = client.get("/documents/ukpga/2026/14")

    assert response.status_code == 200
    assert "Industry and Exports" in response.text
    assert "point-in-time:2026-05-05:ukpga/2026/14" in response.text
    assert "<h1>Industry and Exports</h1>" in response.text
    assert "PDF-derived Marker text" in response.text
    assert "Marker extracted main text." in response.text
    assert "document_uri" not in response.text
    assert 'href="https://www.legislation.gov.uk/ukpga/2026/14"' in response.text
    assert "View on legislation.gov.uk" in response.text
    assert "title:" not in response.text
    assert "Check against source PDF" in response.text
    assert 'id="source-toggle"' in response.text
    assert "Hide PDF" in response.text
    assert "Show PDF" in response.text
    assert "https://www.legislation.gov.uk/ukpga/2026/14/data.pdf" in response.text
    assert 'src="/versions/point-in-time:2026-05-05:ukpga/2026/14/pdf"' in response.text
    assert 'hx-get="/versions/point-in-time:2026-05-05:ukpga/2026/14/provisions"' in response.text
    assert 'hx-get="/versions/point-in-time:2026-05-05:ukpga/2026/14/files"' in response.text
    assert 'hx-get="/versions/point-in-time:2026-05-05:ukpga/2026/14/content"' in response.text


def test_pdf_route_serves_pdf_from_source_url() -> None:
    client = TestClient(create_app(api_client=FakeApiClient()))

    response = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/pdf")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 example"
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == 'inline; filename="source.pdf"'
    assert response.headers["content-length"] == str(len(b"%PDF-1.4 example"))


def test_pdf_route_caches_repeat_requests() -> None:
    fake_api = FakeApiClient()
    client = TestClient(create_app(api_client=fake_api))

    first = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/pdf")
    fetches_after_first = sum(1 for call in fake_api.calls if call[0] == "iter_pdf_source")
    second = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/pdf")
    fetches_after_second = sum(1 for call in fake_api.calls if call[0] == "iter_pdf_source")

    assert first.content == second.content == b"%PDF-1.4 example"
    assert fetches_after_first == 1
    assert fetches_after_second == 1


def test_pdf_route_prefers_cached_pdf_content_path() -> None:
    class CachedPdfApiClient(FakeApiClient):
        def get_pdf_content_path(self, version_id: str) -> str | None:
            self.calls.append(("get_pdf_content_path", {"version_id": version_id}))
            return "/files/2/content"

    api_client = CachedPdfApiClient()
    client = TestClient(create_app(api_client=api_client))

    response = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/pdf")

    assert response.status_code == 200
    assert ("iter_pdf_source", {"source_url": "/files/2/content"}) in api_client.calls
    assert not any(call[0] == "get_pdf_source_url" for call in api_client.calls)


def test_version_partials_render_expected_fragments() -> None:
    client = TestClient(create_app(api_client=FakeApiClient()))
    version_id = "point-in-time:2026-05-05:ukpga/2026/14"

    provisions = client.get(f"/versions/{version_id}/provisions")
    files = client.get(f"/versions/{version_id}/files")
    content = client.get(f"/versions/{version_id}/content")

    assert "Limit on selective financial assistance" in provisions.text
    assert "markdown/point-in-time/2026-05-05/ukpga/2026/14.md" in files.text
    assert "# Industry and Exports" in content.text


def test_api_errors_render_friendly_message() -> None:
    class BrokenApiClient(FakeApiClient):
        def list_documents(self, **kwargs: object) -> dict[str, Any]:
            raise RuntimeError("API unavailable")

    client = TestClient(create_app(api_client=BrokenApiClient()))

    response = client.get("/documents?q=exports")

    assert response.status_code == 200
    assert "API unavailable" in response.text
