from pathlib import Path
from types import SimpleNamespace

import httpx
from typer.testing import CliRunner

from fetchers.legislationdotgovdotuk import FetchManifest, FetchRecord
from git_legislation.cli import app


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


def test_convert_xml_command_renders_and_writes_markdown(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}
    xml_path = tmp_path / "14.xml"

    def fake_render_document_markdown(path: Path) -> str:
        calls["render_path"] = path
        return "# Example\n"

    def fake_write_document_markdown(
        markdown: str,
        legislation_type: str,
        year: int,
        number: int,
        output_root: Path,
    ) -> Path:
        calls["write_args"] = (markdown, legislation_type, year, number, output_root)
        return tmp_path / "markdown" / "enacted" / "ukpga" / "2026" / "14.md"

    monkeypatch.setattr("git_legislation.cli.render_document_markdown", fake_render_document_markdown)
    monkeypatch.setattr("git_legislation.cli.write_document_markdown", fake_write_document_markdown)

    result = CliRunner().invoke(
        app,
        ["convert-xml", str(xml_path), "ukpga", "2026", "14", "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert calls["render_path"] == xml_path
    assert calls["write_args"] == ("# Example\n", "ukpga", 2026, 14, tmp_path)
    assert "markdown/enacted/ukpga/2026/14.md" in result.output


def test_list_year_command_fetches_and_prints_document_refs(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_year_feed(client: httpx.Client, legislation_type: str, year: int) -> bytes:
        calls["client"] = client
        calls["fetch_args"] = (legislation_type, year)
        return b"<feed>example</feed>"

    def fake_parse_year_feed(feed: bytes) -> list[SimpleNamespace]:
        calls["feed"] = feed
        return [
            SimpleNamespace(
                legislation_type="ukpga",
                year=2026,
                number=14,
                title="Industry and Exports (Financial Assistance) Act 2026",
            )
        ]

    monkeypatch.setattr("git_legislation.cli.fetch_year_feed", fake_fetch_year_feed)
    monkeypatch.setattr("git_legislation.cli.parse_year_feed", fake_parse_year_feed)

    result = CliRunner().invoke(app, ["list-year", "ukpga", "2026"])

    assert result.exit_code == 0
    assert calls["fetch_args"] == ("ukpga", 2026)
    assert calls["feed"] == b"<feed>example</feed>"
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
    ) -> FetchManifest:
        calls["fetch_enacted_corpus_args"] = (legislation_type, start_year, end_year, output_root)
        return FetchManifest(
            corpus="enacted",
            legislation_type=legislation_type,
            start_year=start_year,
            end_year=end_year,
            records=[
                FetchRecord(
                    status="fetched",
                    legislation_type=legislation_type,
                    year=2025,
                    number=1,
                    path=output_root / "xml" / "enacted" / legislation_type / "2025" / "1" / "data.xml",
                ),
                FetchRecord(
                    status="fetched",
                    legislation_type=legislation_type,
                    year=2026,
                    number=1,
                    path=output_root / "xml" / "enacted" / legislation_type / "2026" / "1" / "data.xml",
                ),
            ],
        )

    def fake_write_fetch_manifest(manifest: FetchManifest, output_root: Path) -> Path:
        calls["write_fetch_manifest_args"] = (manifest, output_root)
        return output_root / "manifests" / "enacted" / "ukpga" / "2025-2026.json"

    monkeypatch.setattr("git_legislation.cli.fetch_enacted_corpus", fake_fetch_enacted_corpus)
    monkeypatch.setattr("git_legislation.cli.write_fetch_manifest", fake_write_fetch_manifest)

    result = CliRunner().invoke(
        app,
        ["fetch-enacted-corpus", "ukpga", "2025", "--end-year", "2026", "--output-root", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert calls["fetch_enacted_corpus_args"] == ("ukpga", 2025, 2026, tmp_path)
    assert calls["write_fetch_manifest_args"][1] == tmp_path
    assert "xml/enacted/ukpga/2025/1/data.xml" in result.output
    assert "xml/enacted/ukpga/2026/1/data.xml" in result.output
    assert "manifests/enacted/ukpga/2025-2026.json" in result.output
