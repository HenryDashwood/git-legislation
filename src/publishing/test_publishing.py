import sqlite3
from pathlib import Path

from publishing import (
    default_sqlite_database_path,
    markdown_ref_from_path,
    parse_markdown_document,
    publish_markdown_to_sqlite,
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


def test_publish_markdown_to_sqlite_inserts_documents_versions_provisions_and_search(tmp_path: Path) -> None:
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-05"
    markdown_path = markdown_root / "ukpga" / "2026" / "14.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)
    database_path = default_sqlite_database_path(tmp_path)

    report = publish_markdown_to_sqlite(
        markdown_root=markdown_root,
        database_path=database_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    assert report.scanned == 1
    assert report.published == 1
    assert report.failures == []

    with sqlite3.connect(database_path) as connection:
        document = connection.execute("select id, title, legislation_type, calendar_year from documents").fetchone()
        version = connection.execute(
            "select id, document_id, collection, snapshot_date, word_count from versions"
        ).fetchone()
        provisions = connection.execute("select heading from provisions order by ordinal").fetchall()
        search = connection.execute(
            """
            select provision_id
            from provision_search
            where provision_search match 'overseas'
            """
        ).fetchall()

    assert document == (
        "ukpga/2026/14",
        "Industry and Exports (Financial Assistance) Act 2026",
        "ukpga",
        2026,
    )
    assert version[1:4] == ("ukpga/2026/14", "point-in-time", "2026-05-05")
    assert version[4] > 0
    assert provisions == [
        ("1 Limit on selective financial assistance for industry",),
        ("2 Financial assistance for exports and overseas investment: commitment limits",),
    ]
    assert len(search) == 1


def test_publish_markdown_to_sqlite_is_idempotent_for_a_version(tmp_path: Path) -> None:
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-05"
    markdown_path = markdown_root / "ukpga" / "2026" / "14.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(MARKDOWN)
    database_path = default_sqlite_database_path(tmp_path)

    publish_markdown_to_sqlite(
        markdown_root=markdown_root,
        database_path=database_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )
    publish_markdown_to_sqlite(
        markdown_root=markdown_root,
        database_path=database_path,
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
    )

    with sqlite3.connect(database_path) as connection:
        provision_count = connection.execute("select count(*) from provisions").fetchone()[0]
        search_count = connection.execute("select count(*) from provision_search").fetchone()[0]

    assert provision_count == 2
    assert search_count == 2


def test_publish_markdown_to_sqlite_scans_only_selected_type_roots(tmp_path: Path) -> None:
    markdown_root = tmp_path / "markdown" / "point-in-time" / "2026-05-05"
    ukpga_path = markdown_root / "ukpga" / "2026" / "14.md"
    uksi_path = markdown_root / "uksi" / "2026" / "1.md"
    ukpga_path.parent.mkdir(parents=True)
    uksi_path.parent.mkdir(parents=True)
    ukpga_path.write_text(MARKDOWN)
    uksi_path.write_text(MARKDOWN.replace("ukpga/2026/14", "uksi/2026/1"))

    report = publish_markdown_to_sqlite(
        markdown_root=markdown_root,
        database_path=default_sqlite_database_path(tmp_path),
        output_root=tmp_path,
        collection="point-in-time",
        snapshot_date="2026-05-05",
        legislation_types=["ukpga"],
    )

    assert report.scanned == 1
    assert report.published == 1
