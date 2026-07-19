from pathlib import Path
from typing import Any

import publishing
from publishing import (
    canonical_markdown_sha256,
    canonicalize_dated_uris,
    markdown_object_key,
    markdown_ref_from_path,
    normalize_markdown_text,
    parse_markdown_document,
    publish_document_text_to_postgres,
    publish_markdown_to_postgres,
    source_xml_object_key,
    source_xml_path_for_markdown_ref,
    split_frontmatter,
)

MARKDOWN = """---
title: "Industry and Exports (Financial Assistance) Act 2026"
document_uri: "http://www.legislation.gov.uk/ukpga/2026/14"
status: "Prospective"
extent: "E+W+S+N.I."
pdf_alternatives:
  - "http://www.legislation.gov.uk/ukpga/2026/14/data.pdf"
---

# Industry and Exports (Financial Assistance) Act 2026

2026 Chapter 14

## 1 Limit on selective financial assistance for industry

In section 8 of the Industrial Development Act 1982, in subsection (5), substitute £20 billion.

## 2 Financial assistance for exports and overseas investment: commitment limits

In section 6 of the Export and Investment Guarantees Act 1991, substitute £160 billion.
"""


def test_split_frontmatter_returns_metadata_and_body() -> None:
    metadata, body = split_frontmatter(MARKDOWN)

    assert metadata["title"] == "Industry and Exports (Financial Assistance) Act 2026"
    assert metadata["pdf_alternatives"] == ["http://www.legislation.gov.uk/ukpga/2026/14/data.pdf"]
    assert body.startswith("\n# Industry and Exports")


def test_normalize_markdown_text_replaces_windows_1252_punctuation() -> None:
    markdown = '---\ntitle: "Disabled Persons\x92 Vehicles \x96 Example"\n---\n'

    assert normalize_markdown_text(markdown) == '---\ntitle: "Disabled Persons\' Vehicles - Example"\n---\n'


def test_canonicalize_dated_uris_strips_point_in_time_date_segments() -> None:
    markdown = "\n".join(
        [
            'document_uri: "http://www.legislation.gov.uk/nia/2026/5/2026-07-18"',
            '  - "http://www.legislation.gov.uk/nia/2026/5/2026-07-18/data.pdf"',
            '  - "http://www.legislation.gov.uk/nia/2026/5/pdfs/nia_20260005_en.pdf"',
            "See https://www.legislation.gov.uk/ukpga/1971/77/2026-05-05 for details.",
        ]
    )

    assert canonicalize_dated_uris(markdown) == "\n".join(
        [
            'document_uri: "http://www.legislation.gov.uk/nia/2026/5"',
            '  - "http://www.legislation.gov.uk/nia/2026/5/data.pdf"',
            '  - "http://www.legislation.gov.uk/nia/2026/5/pdfs/nia_20260005_en.pdf"',
            "See https://www.legislation.gov.uk/ukpga/1971/77 for details.",
        ]
    )


def test_canonicalize_dated_uris_leaves_non_legislation_urls_and_plain_dates_alone() -> None:
    markdown = "Made on 2026-07-18. See https://example.com/2026-07-18/report and s. 2 of the Act."

    assert canonicalize_dated_uris(markdown) == markdown


def test_canonical_markdown_sha256_is_invariant_across_snapshot_dates() -> None:
    at_first_date = MARKDOWN.replace("ukpga/2026/14", "ukpga/2026/14/2026-05-05")
    at_second_date = MARKDOWN.replace("ukpga/2026/14", "ukpga/2026/14/2026-07-18")

    assert at_first_date != at_second_date
    assert canonical_markdown_sha256(at_first_date) == canonical_markdown_sha256(at_second_date)
    assert canonical_markdown_sha256(at_first_date) == canonical_markdown_sha256(MARKDOWN)


def test_markdown_ref_from_point_in_time_path(tmp_path: Path) -> None:
    markdown_path = tmp_path / "markdown" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)

    ref = markdown_ref_from_path(
        markdown_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    assert ref.collection == "point-in-time"
    assert ref.snapshot_date == "2026-05-05"
    assert ref.source_path == ("ukpga", "2026", "14")
    assert ref.document_id == "ukpga/2026/14"
    assert ref.version_id == "point-in-time:2026-05-05:ukpga/2026/14"


def test_parse_markdown_document_splits_section_provisions(tmp_path: Path) -> None:
    markdown_path = tmp_path / "markdown" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)
    ref = markdown_ref_from_path(
        markdown_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    document = parse_markdown_document(ref)

    assert document.title == "Industry and Exports (Financial Assistance) Act 2026"
    assert len(document.provisions) == 2
    assert document.provisions[0].number == "1"
    assert document.provisions[0].anchor == "1-limit-on-selective-financial-assistance-for-industry"
    assert "Industrial Development Act 1982" in document.provisions[0].text


def test_parse_markdown_document_normalizes_frontmatter_before_yaml_parsing(tmp_path: Path) -> None:
    markdown = MARKDOWN.replace(
        "Industry and Exports (Financial Assistance)",
        "Disabled Persons\x92 Vehicles",
    )
    markdown_path = tmp_path / "markdown" / "point-in-time" / "2026-05-05" / "nisr" / "2011" / "307.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(markdown)
    ref = markdown_ref_from_path(
        markdown_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    document = parse_markdown_document(ref)

    assert document.title == "Disabled Persons' Vehicles Act 2026"


def test_publish_markdown_to_postgres_scans_only_selected_type_roots(tmp_path: Path, monkeypatch: Any) -> None:
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-05"
    ukpga_path = markdown_root / "ukpga" / "2026" / "14.md"
    uksi_path = markdown_root / "uksi" / "2026" / "1.md"
    ukpga_path.parent.mkdir(parents=True)
    uksi_path.parent.mkdir(parents=True)
    ukpga_path.write_text(MARKDOWN)
    uksi_path.write_text(MARKDOWN.replace("ukpga/2026/14", "uksi/2026/1"))
    connection = RecordingConnection()
    monkeypatch.setattr(publishing.psycopg, "connect", lambda _: connection)

    report = publish_markdown_to_postgres(
        markdown_root=markdown_root,
        database_url="postgres://example",
        output_root=tmp_path,
        object_store_root=tmp_path / "objects",
        collection="point-in-time",
        snapshot_date="2026-05-05",
        legislation_types=["ukpga"],
    )

    assert report.scanned == 1
    assert report.published == 1
    stored_markdown_path = (
        tmp_path / "objects" / "legislation" / "markdown" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14.md"
    )
    assert stored_markdown_path.exists()


def test_source_xml_path_for_markdown_ref_returns_matching_point_in_time_xml_path(tmp_path: Path) -> None:
    markdown_path = tmp_path / "markdown" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)
    ref = markdown_ref_from_path(
        markdown_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    assert source_xml_path_for_markdown_ref(ref, output_root=tmp_path) == (
        tmp_path / "xml" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14" / "data.xml"
    )


def test_object_keys_match_existing_output_layout() -> None:
    assert source_xml_object_key("point-in-time", ("ukpga", "2026", "14"), "2026-05-05") == (
        "xml/point-in-time/2026-05-05/ukpga/2026/14/data.xml"
    )
    assert markdown_object_key("point-in-time", ("ukpga", "2026", "14"), "2026-05-05") == (
        "markdown/point-in-time/2026-05-05/ukpga/2026/14.md"
    )


def test_publish_markdown_to_postgres_inserts_core_document_rows(tmp_path: Path, monkeypatch: Any) -> None:
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-05"
    markdown_path = markdown_root / "ukpga" / "2026" / "14.md"
    xml_path = tmp_path / "xml" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14" / "data.xml"
    markdown_path.parent.mkdir(parents=True)
    xml_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)
    xml_path.write_text("<Legislation DocumentURI='http://www.legislation.gov.uk/ukpga/2026/14' />")
    connection = RecordingConnection()
    monkeypatch.setattr(publishing.psycopg, "connect", lambda _: connection)

    report = publish_markdown_to_postgres(
        markdown_root=markdown_root,
        database_url="postgres://example",
        output_root=tmp_path,
        object_store_root=tmp_path / "objects",
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    assert report.scanned == 1
    assert report.published == 1
    assert report.created_versions == 1
    assert report.reused_versions == 0
    assert report.failures == []
    assert connection.committed
    assert any("insert into fetch_runs" in sql for sql, _ in connection.executed)
    assert any("insert into documents" in sql for sql, _ in connection.executed)
    assert any("insert into document_versions" in sql for sql, _ in connection.executed)
    assert any("insert into fetch_observations" in sql for sql, _ in connection.executed)
    assert any("insert into provisions" in sql for sql, _ in connection.executed)
    version_params = next(params for sql, params in connection.executed if "insert into document_versions" in sql)
    assert version_params[0] == "point-in-time:2026-05-05:ukpga/2026/14"
    assert version_params[2] == "point_in_time"
    assert version_params[5] == "xml/point-in-time/2026-05-05/ukpga/2026/14/data.xml"
    assert version_params[6] == "markdown/point-in-time/2026-05-05/ukpga/2026/14.md"
    assert version_params[9] == canonical_markdown_sha256(MARKDOWN)
    stored_markdown_path = (
        tmp_path / "objects" / "legislation" / "markdown" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14.md"
    )
    stored_xml_path = (
        tmp_path
        / "objects"
        / "legislation"
        / "xml"
        / "point-in-time"
        / "2026-05-05"
        / "ukpga"
        / "2026"
        / "14"
        / "data.xml"
    )
    assert stored_markdown_path.read_text() == MARKDOWN
    assert stored_xml_path.exists()
    observation_params = next(params for sql, params in connection.executed if "insert into fetch_observations" in sql)
    assert observation_params[2] == "point-in-time:2026-05-05:ukpga/2026/14"
    assert observation_params[4] == "fetched"


def test_publish_document_text_to_postgres_writes_objects_without_output_staging(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    connection = RecordingConnection()
    monkeypatch.setattr(publishing.psycopg, "connect", lambda _: connection)

    published_version = publish_document_text_to_postgres(
        database_url="postgres://example",
        source_path=("ukpga", "2026", "14"),
        xml_content=b"<Legislation />",
        markdown=MARKDOWN,
        collection="point-in-time",
        snapshot_date="2026-05-05",
        object_store_root=tmp_path / "objects",
    )

    assert published_version.version_id == "point-in-time:2026-05-05:ukpga/2026/14"
    assert published_version.created
    xml_path = (
        tmp_path
        / "objects"
        / "legislation"
        / "xml"
        / "point-in-time"
        / "2026-05-05"
        / "ukpga"
        / "2026"
        / "14"
        / "data.xml"
    )
    markdown_path = (
        tmp_path / "objects" / "legislation" / "markdown" / "point-in-time" / "2026-05-05" / "ukpga" / "2026" / "14.md"
    )
    assert xml_path.read_bytes() == b"<Legislation />"
    assert markdown_path.read_text() == MARKDOWN
    assert any("insert into fetch_runs" in sql for sql, _ in connection.executed)
    assert any("insert into fetch_observations" in sql for sql, _ in connection.executed)


def test_publish_markdown_to_postgres_reuses_existing_content_version(tmp_path: Path, monkeypatch: Any) -> None:
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-06"
    markdown_path = markdown_root / "ukpga" / "2026" / "14.md"
    xml_path = tmp_path / "xml" / "point-in-time" / "2026-05-06" / "ukpga" / "2026" / "14" / "data.xml"
    markdown_path.parent.mkdir(parents=True)
    xml_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)
    xml_path.write_text("<Legislation DocumentURI='http://www.legislation.gov.uk/ukpga/2026/14' />")
    connection = RecordingConnection(existing_content_version_id="point-in-time:2026-05-05:ukpga/2026/14")
    monkeypatch.setattr(publishing.psycopg, "connect", lambda _: connection)

    report = publish_markdown_to_postgres(
        markdown_root=markdown_root,
        database_url="postgres://example",
        output_root=tmp_path,
        object_store_root=tmp_path / "objects",
        collection="point-in-time",
        snapshot_date="2026-05-06",
    )

    assert report.scanned == 1
    assert report.published == 1
    assert report.created_versions == 0
    assert report.reused_versions == 1
    assert not any("insert into document_versions" in sql for sql, _ in connection.executed)
    lookup_sql, lookup_params = next(
        (sql, params) for sql, params in connection.executed if "from document_versions where document_id" in sql
    )
    assert "canonical_sha256" in lookup_sql
    assert lookup_params[2] == canonical_markdown_sha256(MARKDOWN)
    assert any(sql.startswith("update document_versions set canonical_sha256") for sql, _ in connection.executed)
    update_latest_params = next(params for sql, params in connection.executed if sql.startswith("update documents"))
    assert update_latest_params[0] == "point-in-time:2026-05-05:ukpga/2026/14"
    observation_params = next(params for sql, params in connection.executed if "insert into fetch_observations" in sql)
    assert observation_params[2] == "point-in-time:2026-05-05:ukpga/2026/14"
    assert observation_params[4] == "not_modified"


class RecordingConnection:
    def __init__(self, existing_content_version_id: str | None = None) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.committed = False
        self.existing_content_version_id = existing_content_version_id

    def __enter__(self) -> "RecordingConnection":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> "RecordingCursor":
        normalized_sql = " ".join(sql.split())
        self.executed.append((normalized_sql, params))
        if "insert into fetch_runs" in normalized_sql:
            return RecordingCursor((1,))
        if "from document_versions where document_id" in normalized_sql and self.existing_content_version_id:
            return RecordingCursor((self.existing_content_version_id,))
        return RecordingCursor(None)

    def commit(self) -> None:
        self.committed = True


class RecordingCursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row
