from pathlib import Path
from types import SimpleNamespace

import httpx
import typer
from typer.testing import CliRunner

from git_legislation.cli import app
from seeding import BulkArchiveDownloadError


class FixedDate:
    @classmethod
    def today(cls) -> object:
        return SimpleNamespace(isoformat=lambda: "2026-05-03")


def test_fetch_xml_command_fetches_and_writes_xml(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_document_xml(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool,
        at: str | None,
    ) -> bytes:
        calls["client"] = client
        calls["fetch_args"] = (legislation_type, year, number, as_enacted, at)
        return b"<Legislation>example</Legislation>"

    def fake_write_document_xml(
        content: bytes,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool,
        at: str | None,
        output_root: Path,
    ) -> Path:
        calls["write_args"] = (content, legislation_type, year, number, as_enacted, at, output_root)
        return tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"

    monkeypatch.setattr("git_legislation.cli.fetch_document_xml", fake_fetch_document_xml)
    monkeypatch.setattr("git_legislation.cli.write_document_xml", fake_write_document_xml)

    result = CliRunner().invoke(app, ["fetch-xml", "ukpga", "2026", "14", "--output-root", str(tmp_path)])

    assert result.exit_code == 0
    assert calls["fetch_args"] == ("ukpga", 2026, 14, False, None)
    assert calls["write_args"] == (
        b"<Legislation>example</Legislation>",
        "ukpga",
        2026,
        14,
        False,
        None,
        tmp_path,
    )
    assert "xml/point-in-time/2026-05-03/ukpga/2026/14/data.xml" in result.output


def test_fetch_source_xml_command_fetches_and_writes_latest_source_xml(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    document = SimpleNamespace(path=("ukpga", "Geo3", "44", "42"))

    def fake_document_ref_from_source_path(source_path: str) -> object:
        calls["source_path_arg"] = source_path
        return document

    def fake_fetch_document_ref_xml(
        client: httpx.Client,
        document: object,
        as_enacted: bool,
        at: str | None,
    ) -> bytes:
        calls["fetch_args"] = (client, document, as_enacted, at)
        return b"<Legislation>example</Legislation>"

    def fake_write_source_document_xml(
        content: bytes,
        source_path: tuple[str, ...],
        as_enacted: bool,
        at: str | None,
        output_root: Path,
    ) -> Path:
        calls["write_args"] = (content, source_path, as_enacted, at, output_root)
        return output_root / "xml" / "latest" / "ukpga" / "Geo3" / "44" / "42" / "data.xml"

    monkeypatch.setattr("git_legislation.cli.document_ref_from_source_path", fake_document_ref_from_source_path)
    monkeypatch.setattr("git_legislation.cli.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr("git_legislation.cli.write_source_document_xml", fake_write_source_document_xml)

    result = CliRunner().invoke(
        app,
        ["fetch-source-xml", "ukpga/Geo3/44/42", "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert calls["source_path_arg"] == "ukpga/Geo3/44/42"
    client, fetched_document, as_enacted, at = calls["fetch_args"]
    assert isinstance(client, object)
    assert fetched_document is document
    assert as_enacted is False
    assert at is None
    assert calls["write_args"] == (
        b"<Legislation>example</Legislation>",
        ("ukpga", "Geo3", "44", "42"),
        False,
        None,
        tmp_path,
    )
    assert "xml/latest/ukpga/Geo3/44/42/data.xml" in result.output


def test_fetch_source_xml_command_fetches_and_writes_enacted_source_xml(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    document = SimpleNamespace(path=("ukpga", "Geo3", "44", "42"))

    monkeypatch.setattr("git_legislation.cli.document_ref_from_source_path", lambda source_path: document)

    def fake_fetch_document_ref_xml(
        client: httpx.Client,
        document: object,
        as_enacted: bool,
        at: str | None,
    ) -> bytes:
        calls["fetch_args"] = (document, as_enacted, at)
        return b"<Legislation>example</Legislation>"

    def fake_write_source_document_xml(
        content: bytes,
        source_path: tuple[str, ...],
        as_enacted: bool,
        at: str | None,
        output_root: Path,
    ) -> Path:
        calls["write_args"] = (content, source_path, as_enacted, at, output_root)
        return output_root / "xml" / "enacted" / "ukpga" / "Geo3" / "44" / "42" / "data.xml"

    monkeypatch.setattr("git_legislation.cli.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr("git_legislation.cli.write_source_document_xml", fake_write_source_document_xml)

    result = CliRunner().invoke(
        app,
        ["fetch-source-xml", "ukpga/Geo3/44/42", "--as-enacted", "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert calls["fetch_args"] == (document, True, None)
    assert calls["write_args"] == (
        b"<Legislation>example</Legislation>",
        ("ukpga", "Geo3", "44", "42"),
        True,
        None,
        tmp_path,
    )
    assert "xml/enacted/ukpga/Geo3/44/42/data.xml" in result.output


def test_convert_xml_command_renders_and_writes_markdown(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    xml_path = tmp_path / "14.xml"

    def fake_convert_document_markdown(path: Path, output_root: Path) -> Path:
        calls["convert_args"] = (path, output_root)
        return output_root / "markdown" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14.md"

    monkeypatch.setattr("git_legislation.cli.convert_document_markdown", fake_convert_document_markdown)

    result = CliRunner().invoke(
        app,
        ["convert-xml", str(xml_path), "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert calls["convert_args"] == (xml_path, tmp_path)
    assert "markdown/point-in-time/2026-05-03/ukpga/2026/14.md" in result.output


def test_convert_enacted_corpus_command_converts_fetched_tree(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_convert_xml_tree(xml_root: Path, output_root: Path, report: object, log: object) -> list[Path]:
        calls["convert_xml_tree_args"] = (xml_root, output_root, report, log)
        return [
            output_root / "markdown" / "enacted" / "ukpga" / "2026" / "14.md",
            output_root / "markdown" / "enacted" / "ukpga" / "2026" / "13.md",
        ]

    def fake_write_conversion_report(report: object, output_root: Path) -> Path:
        calls["write_conversion_report_args"] = (report, output_root)
        return output_root / "reports" / "convert" / "enacted" / "ukpga" / "report.json"

    monkeypatch.setattr("git_legislation.cli.convert_xml_tree", fake_convert_xml_tree)
    monkeypatch.setattr("git_legislation.cli.write_conversion_report", fake_write_conversion_report)

    result = CliRunner().invoke(app, ["convert-enacted-corpus", "ukpga", "--output-root", str(tmp_path)])

    assert result.exit_code == 0
    xml_root, output_root, report, log = calls["convert_xml_tree_args"]
    assert (xml_root, output_root) == (tmp_path / "xml" / "enacted" / "ukpga", tmp_path)
    assert report.mode == "enacted"
    assert report.legislation_type == "ukpga"
    assert log is typer.echo
    assert calls["write_conversion_report_args"] == (report, tmp_path)
    assert "Converted enacted ukpga: 2 documents, 0 failures" in result.output
    assert "reports/convert/enacted/ukpga/report.json" in result.output


def test_convert_point_in_time_corpus_command_converts_fetched_tree(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_convert_xml_tree(xml_root: Path, output_root: Path, report: object, log: object) -> list[Path]:
        calls["convert_xml_tree_args"] = (xml_root, output_root, report, log)
        return [
            output_root / "markdown" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14.md",
            output_root / "markdown" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "13.md",
        ]

    def fake_write_conversion_report(report: object, output_root: Path) -> Path:
        calls["write_conversion_report_args"] = (report, output_root)
        return output_root / "reports" / "convert" / "point-in-time" / "2026-05-03" / "ukpga.json"

    monkeypatch.setattr("git_legislation.cli.convert_xml_tree", fake_convert_xml_tree)
    monkeypatch.setattr("git_legislation.cli.write_conversion_report", fake_write_conversion_report)

    result = CliRunner().invoke(
        app,
        ["convert-point-in-time-corpus", "--at", "2026-05-03", "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    xml_root, output_root, report, log = calls["convert_xml_tree_args"]
    assert (xml_root, output_root) == (tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga", tmp_path)
    assert report.mode == "point-in-time"
    assert report.legislation_type == "ukpga"
    assert report.at == "2026-05-03"
    assert log is typer.echo
    assert calls["write_conversion_report_args"] == (report, tmp_path)
    assert "Converted point-in-time ukpga at 2026-05-03: 2 documents, 0 failures" in result.output
    assert "reports/convert/point-in-time/2026-05-03/ukpga.json" in result.output


def test_list_year_command_fetches_and_prints_document_refs(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_year_document_refs(
        client: httpx.Client,
        legislation_type: str,
        year: int,
    ) -> list[SimpleNamespace]:
        calls["client"] = client
        calls["fetch_args"] = (legislation_type, year)
        return [
            SimpleNamespace(
                legislation_type="ukpga",
                year=2026,
                number=14,
                title="Industry and Exports (Financial Assistance) Act 2026",
            )
        ]

    monkeypatch.setattr("git_legislation.cli.fetch_year_document_refs", fake_fetch_year_document_refs)

    result = CliRunner().invoke(app, ["list-year", "ukpga", "2026"])

    assert result.exit_code == 0
    assert calls["fetch_args"] == ("ukpga", 2026)
    assert "ukpga/2026/14  Industry and Exports (Financial Assistance) Act 2026" in result.output


def test_fetch_year_command_fetches_and_writes_each_document(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool,
        at: str | None,
        output_root: Path,
    ) -> list[Path]:
        calls["fetch_year_documents_args"] = (legislation_type, year, as_enacted, at, output_root)
        return [
            output_root
            / "xml"
            / "point-in-time"
            / "2026-05-03"
            / legislation_type
            / str(year)
            / "14"
            / "data.xml",
            output_root
            / "xml"
            / "point-in-time"
            / "2026-05-03"
            / legislation_type
            / str(year)
            / "13"
            / "data.xml",
        ]

    monkeypatch.setattr("git_legislation.cli.fetch_year_documents", fake_fetch_year_documents)

    result = CliRunner().invoke(app, ["fetch-year", "ukpga", "2026", "--output-root", str(tmp_path)])

    assert result.exit_code == 0
    assert calls["fetch_year_documents_args"] == ("ukpga", 2026, False, None, tmp_path)
    assert "xml/point-in-time/2026-05-03/ukpga/2026/14/data.xml" in result.output
    assert "xml/point-in-time/2026-05-03/ukpga/2026/13/data.xml" in result.output


def test_fetch_enacted_corpus_command_fetches_year_range(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_enacted_corpus(
        client: httpx.Client,
        legislation_type: str,
        start_year: int,
        end_year: int,
        output_root: Path,
        report: object,
        log: object,
    ) -> list[Path]:
        calls["fetch_enacted_corpus_args"] = (legislation_type, start_year, end_year, output_root, report, log)
        return [
            output_root / "xml" / "enacted" / legislation_type / "2025" / "1" / "data.xml",
            output_root / "xml" / "enacted" / legislation_type / "2026" / "1" / "data.xml",
        ]

    def fake_write_fetch_report(report: object, output_root: Path) -> Path:
        calls["write_fetch_report_args"] = (report, output_root)
        return output_root / "reports" / "fetch" / "enacted" / "ukpga" / "2025-2026.json"

    monkeypatch.setattr("git_legislation.cli.fetch_enacted_corpus", fake_fetch_enacted_corpus)
    monkeypatch.setattr("git_legislation.cli.write_fetch_report", fake_write_fetch_report)

    result = CliRunner().invoke(
        app,
        ["fetch-enacted-corpus", "ukpga", "2025", "--end-year", "2026", "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    legislation_type, start_year, end_year, output_root, report, log = calls["fetch_enacted_corpus_args"]
    assert (legislation_type, start_year, end_year, output_root) == ("ukpga", 2025, 2026, tmp_path)
    assert report.mode == "enacted"
    assert log is typer.echo
    assert calls["write_fetch_report_args"] == (report, tmp_path)
    assert "xml/enacted/ukpga/2025/1/data.xml" not in result.output
    assert "xml/enacted/ukpga/2026/1/data.xml" not in result.output
    assert "reports/fetch/enacted/ukpga/2025-2026.json" in result.output


def test_fetch_point_in_time_corpus_command_fetches_configured_corpus(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_point_in_time_corpus(
        client: httpx.Client,
        at: str,
        output_root: Path,
        report: object,
        log: object,
    ) -> list[Path]:
        calls["fetch_point_in_time_corpus_args"] = (at, output_root, report, log)
        return [
            output_root
            / "xml"
            / "point-in-time"
            / at
            / "ukpga"
            / "2025"
            / "1"
            / "data.xml",
            output_root
            / "xml"
            / "point-in-time"
            / at
            / "ukpga"
            / "2026"
            / "1"
            / "data.xml",
        ]

    def fake_write_fetch_report(report: object, output_root: Path) -> Path:
        calls["write_fetch_report_args"] = (report, output_root)
        return output_root / "reports" / "fetch" / "point-in-time" / "2026-05-03.json"

    monkeypatch.setattr("git_legislation.cli.fetch_point_in_time_corpus", fake_fetch_point_in_time_corpus)
    monkeypatch.setattr("git_legislation.cli.write_fetch_report", fake_write_fetch_report)

    result = CliRunner().invoke(
        app,
        [
            "fetch-point-in-time-corpus",
            "--at",
            "2026-05-03",
            "--output-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    at, output_root, report, log = calls["fetch_point_in_time_corpus_args"]
    assert (at, output_root) == ("2026-05-03", tmp_path)
    assert report.mode == "point-in-time"
    assert log is typer.echo
    assert calls["write_fetch_report_args"] == (report, tmp_path)
    assert "xml/point-in-time/2026-05-03/ukpga/2025/1/data.xml" not in result.output
    assert "xml/point-in-time/2026-05-03/ukpga/2026/1/data.xml" not in result.output
    assert "reports/fetch/point-in-time/2026-05-03.json" in result.output


def test_fetch_point_in_time_corpus_command_defaults_to_todays_latest_snapshot(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_point_in_time_corpus(
        client: httpx.Client,
        at: str | None,
        output_root: Path,
        report: object,
        log: object,
    ) -> list[Path]:
        calls["fetch_point_in_time_corpus_args"] = (at, output_root, report, log)
        return [output_root / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "1" / "data.xml"]

    def fake_write_fetch_report(report: object, output_root: Path) -> Path:
        calls["write_fetch_report_args"] = (report, output_root)
        return output_root / "reports" / "fetch" / "point-in-time" / "2026-05-03.json"

    monkeypatch.setattr("git_legislation.cli.date", FixedDate)
    monkeypatch.setattr("git_legislation.cli.fetch_point_in_time_corpus", fake_fetch_point_in_time_corpus)
    monkeypatch.setattr("git_legislation.cli.write_fetch_report", fake_write_fetch_report)

    result = CliRunner().invoke(
        app,
        [
            "fetch-point-in-time-corpus",
            "--output-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    at, output_root, report, log = calls["fetch_point_in_time_corpus_args"]
    assert (at, output_root) == (None, tmp_path)
    assert report.mode == "point-in-time"
    assert report.at == "2026-05-03"
    assert log is typer.echo
    assert calls["write_fetch_report_args"] == (report, tmp_path)
    assert "reports/fetch/point-in-time/2026-05-03.json" in result.output


def test_probe_fetch_failures_command_updates_report(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    report_path = tmp_path / "reports" / "fetch" / "point-in-time" / "2026-05-03.json"
    report = SimpleNamespace()

    def fake_read_fetch_report(path: Path) -> object:
        calls["read_fetch_report_arg"] = path
        return report

    def fake_probe_fetch_report_failures(
        client: httpx.Client,
        report: object,
        limit: int | None,
        log: object,
    ) -> int:
        calls["probe_fetch_report_failures_args"] = (client, report, limit, log)
        return 2

    def fake_write_fetch_report(report: object, output_root: Path) -> Path:
        calls["write_fetch_report_args"] = (report, output_root)
        return report_path

    monkeypatch.setattr("git_legislation.cli.read_fetch_report", fake_read_fetch_report)
    monkeypatch.setattr("git_legislation.cli.probe_fetch_report_failures", fake_probe_fetch_report_failures)
    monkeypatch.setattr("git_legislation.cli.write_fetch_report", fake_write_fetch_report)

    result = CliRunner().invoke(app, ["probe-fetch-failures", str(report_path), "--limit", "2"])

    assert result.exit_code == 0
    assert calls["read_fetch_report_arg"] == report_path
    client, probed_report, limit, log = calls["probe_fetch_report_failures_args"]
    assert isinstance(client, object)
    assert probed_report is report
    assert limit == 2
    assert log is typer.echo
    assert calls["write_fetch_report_args"] == (report, tmp_path)
    assert "Probed 2 failures" in result.output
    assert "reports/fetch/point-in-time/2026-05-03.json" in result.output


def test_download_bulk_enacted_xml_command_downloads_enacted_clml(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_download_bulk_archive(dataset: str, data_format: str, output_root: Path) -> Path:
        calls["download_bulk_archive_args"] = (dataset, data_format, output_root)
        return output_root / "bulk" / "research-legislation" / "texts" / dataset / data_format / "archive.zip"

    monkeypatch.setattr("git_legislation.cli.download_bulk_archive", fake_download_bulk_archive)

    result = CliRunner().invoke(
        app,
        [
            "download-bulk-enacted-xml",
            "--output-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert calls["download_bulk_archive_args"] == ("enacted-epublished", "xml", tmp_path)
    assert "bulk/research-legislation/texts/enacted-epublished/xml/archive.zip" in result.output


def test_download_bulk_enacted_xml_command_reports_download_error(monkeypatch, tmp_path: Path) -> None:
    def fake_download_bulk_archive(dataset: str, data_format: str, output_root: Path) -> Path:
        raise BulkArchiveDownloadError("Research Legislation returned 401 Unauthorized")

    monkeypatch.setattr("git_legislation.cli.download_bulk_archive", fake_download_bulk_archive)

    result = CliRunner().invoke(
        app,
        [
            "download-bulk-enacted-xml",
            "--output-root",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    assert "Research Legislation returned 401 Unauthorized" in result.output


def test_seed_enacted_xml_command_seeds_xml_from_archive(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    archive_path = tmp_path / "bulk.zip"

    def fake_seed_enacted_xml_from_archive(archive_path: Path, output_root: Path) -> list[Path]:
        calls["seed_enacted_xml_from_archive_args"] = (archive_path, output_root)
        return [
            output_root / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml",
            output_root / "xml" / "enacted" / "ukpga" / "2026" / "13" / "data.xml",
        ]

    monkeypatch.setattr("git_legislation.cli.seed_enacted_xml_from_archive", fake_seed_enacted_xml_from_archive)

    result = CliRunner().invoke(
        app,
        [
            "seed-enacted-xml",
            str(archive_path),
            "--output-root",
            str(tmp_path / "output"),
        ],
    )

    assert result.exit_code == 0
    assert calls["seed_enacted_xml_from_archive_args"] == (archive_path, tmp_path / "output")
    assert "xml/enacted/ukpga/2026/14/data.xml" in result.output
    assert "xml/enacted/ukpga/2026/13/data.xml" in result.output
