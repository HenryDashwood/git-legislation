from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from git_legislation_api.main import create_app


@dataclass(frozen=True)
class FakeContent:
    path: Path
    content_type: str
    sha256: str


class FakeRepository:
    def __init__(self) -> None:
        self.calls: dict[str, Any] = {}

    def list_documents(
        self,
        *,
        legislation_type: str | None,
        year: int | None,
        q: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        self.calls["list_documents"] = {
            "legislation_type": legislation_type,
            "year": year,
            "q": q,
            "limit": limit,
            "offset": offset,
        }
        return [
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
        ]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        self.calls["get_document"] = document_id
        if document_id != "ukpga/2026/14":
            return None
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

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        self.calls["list_versions"] = document_id
        document = self.get_document(document_id)
        return [document["latest_version"]] if document else []

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        self.calls["get_version"] = version_id
        if version_id != "point-in-time:2026-05-05:ukpga/2026/14":
            return None
        document = self.get_document("ukpga/2026/14")
        return document["latest_version"] if document else None

    def list_provisions(self, version_id: str) -> list[dict[str, Any]]:
        self.calls["list_provisions"] = version_id
        return [
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

    def get_provision(self, version_id: str, anchor: str) -> dict[str, Any] | None:
        self.calls["get_provision"] = (version_id, anchor)
        if anchor != "1-limit-on-selective-financial-assistance-for-industry":
            return None
        provision = self.list_provisions(version_id)[0]
        return provision | {
            "markdown": "## 1 Limit on selective financial assistance for industry\n\nExample markdown.",
            "plain_text": "1 Limit on selective financial assistance for industry\n\nExample markdown.",
        }

    def list_files(self, version_id: str) -> list[dict[str, Any]]:
        self.calls["list_files"] = version_id
        return [
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
            }
        ]

    def get_canonical_file(self, version_id: str, file_kind: str) -> dict[str, Any] | None:
        self.calls["get_canonical_file"] = (version_id, file_kind)
        return self.list_files(version_id)[0] if file_kind == "markdown" else None


class FakeStorage:
    def __init__(self, content_path: Path) -> None:
        self.content_path = content_path
        self.calls: list[dict[str, str]] = []

    def resolve(self, *, object_key: str, sha256: str, content_type: str) -> FakeContent:
        self.calls.append({"object_key": object_key, "sha256": sha256, "content_type": content_type})
        return FakeContent(path=self.content_path, content_type=content_type, sha256=sha256)


def test_healthz_returns_ok(tmp_path: Path) -> None:
    client = TestClient(create_app(repository=FakeRepository(), storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_documents_passes_filters_and_returns_items(tmp_path: Path) -> None:
    repository = FakeRepository()
    client = TestClient(create_app(repository=repository, storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/documents?legislation_type=ukpga&year=2026&q=exports&limit=25&offset=50")

    assert response.status_code == 200
    assert repository.calls["list_documents"] == {
        "legislation_type": "ukpga",
        "year": 2026,
        "q": "exports",
        "limit": 25,
        "offset": 50,
    }
    assert response.json()["items"][0]["id"] == "ukpga/2026/14"
    assert response.json()["limit"] == 25
    assert response.json()["offset"] == 50


def test_list_documents_rejects_unknown_legislation_type(tmp_path: Path) -> None:
    client = TestClient(create_app(repository=FakeRepository(), storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/documents?legislation_type=unknown")

    assert response.status_code == 422


def test_get_document_accepts_slash_separated_document_id(tmp_path: Path) -> None:
    repository = FakeRepository()
    client = TestClient(create_app(repository=repository, storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/documents/ukpga/2026/14")

    assert response.status_code == 200
    assert repository.calls["get_document"] == "ukpga/2026/14"
    body = response.json()
    assert body["id"] == "ukpga/2026/14"
    assert body["latest_version"]["id"] == "point-in-time:2026-05-05:ukpga/2026/14"


def test_missing_document_returns_404(tmp_path: Path) -> None:
    client = TestClient(create_app(repository=FakeRepository(), storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/documents/ukpga/1900/999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


def test_list_provisions_omits_large_text_fields(tmp_path: Path) -> None:
    repository = FakeRepository()
    client = TestClient(create_app(repository=repository, storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/provisions")

    assert response.status_code == 200
    assert repository.calls["list_provisions"] == "point-in-time:2026-05-05:ukpga/2026/14"
    provision = response.json()["items"][0]
    assert provision["anchor"] == "1-limit-on-selective-financial-assistance-for-industry"
    assert "markdown" not in provision
    assert "plain_text" not in provision


def test_get_provision_returns_markdown_and_plain_text(tmp_path: Path) -> None:
    client = TestClient(create_app(repository=FakeRepository(), storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get(
        "/versions/point-in-time:2026-05-05:ukpga/2026/14/provisions/"
        "1-limit-on-selective-financial-assistance-for-industry"
    )

    assert response.status_code == 200
    assert response.json()["markdown"].startswith("## 1 Limit")
    assert "Example markdown" in response.json()["plain_text"]


def test_list_files_includes_object_metadata(tmp_path: Path) -> None:
    client = TestClient(create_app(repository=FakeRepository(), storage=FakeStorage(tmp_path / "missing.md")))

    response = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/files")

    assert response.status_code == 200
    file_record = response.json()["items"][0]
    assert file_record["file_kind"] == "markdown"
    assert file_record["object_key"] == "markdown/point-in-time/2026-05-05/ukpga/2026/14.md"
    assert file_record["content_type"] == "text/markdown"


def test_version_content_serves_canonical_markdown(tmp_path: Path) -> None:
    content_path = tmp_path / "objects" / "legislation" / "markdown" / "example.md"
    content_path.parent.mkdir(parents=True)
    content_path.write_text("# Example\n")
    repository = FakeRepository()
    storage = FakeStorage(content_path)
    client = TestClient(create_app(repository=repository, storage=storage))

    response = client.get("/versions/point-in-time:2026-05-05:ukpga/2026/14/content")

    assert response.status_code == 200
    assert response.text == "# Example\n"
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["etag"] == '"abc123"'
    assert repository.calls["get_canonical_file"] == ("point-in-time:2026-05-05:ukpga/2026/14", "markdown")
    assert storage.calls == [
        {
            "object_key": "markdown/point-in-time/2026-05-05/ukpga/2026/14.md",
            "sha256": "abc123",
            "content_type": "text/markdown",
        }
    ]
