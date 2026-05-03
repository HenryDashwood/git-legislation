from pathlib import Path

import httpx
from typer.testing import CliRunner

from git_legislation.cli import app


def test_fetch_xml_command_fetches_and_writes_xml(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_document_xml(client: httpx.Client, legislation_type: str, year: int, number: int) -> bytes:
        calls["client"] = client
        calls["fetch_args"] = (legislation_type, year, number)
        return b"<Legislation>example</Legislation>"

    def fake_write_document_xml(
        content: bytes, legislation_type: str, year: int, number: int, output_root: Path
    ) -> Path:
        calls["write_args"] = (content, legislation_type, year, number, output_root)
        return tmp_path / "xml" / "consolidated" / "ukpga" / "2026" / "14" / "current.xml"

    monkeypatch.setattr("git_legislation.cli.fetch_document_xml", fake_fetch_document_xml)
    monkeypatch.setattr("git_legislation.cli.write_document_xml", fake_write_document_xml)

    result = CliRunner().invoke(app, ["fetch-xml", "ukpga", "2026", "14", "--output-root", str(tmp_path)])

    assert result.exit_code == 0
    assert calls["fetch_args"] == ("ukpga", 2026, 14)
    assert calls["write_args"] == (b"<Legislation>example</Legislation>", "ukpga", 2026, 14, tmp_path)
    assert "xml/consolidated/ukpga/2026/14/current.xml" in result.output


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
