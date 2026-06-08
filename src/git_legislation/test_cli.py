from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import typer
from typer.testing import CliRunner

from git_legislation.cli import app


class FixedDate:
    @classmethod
    def today(cls) -> object:
        return SimpleNamespace(isoformat=lambda: "2026-05-03")

    @classmethod
    def fromisoformat(cls, value: str) -> date:
        return date.fromisoformat(value)


def test_list_year_command_fetches_and_prints_document_refs(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_fetch_year_document_refs(
        client: object,
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


def test_ingest_document_command_fetches_converts_and_publishes(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {}
    published_version = SimpleNamespace(created=True, version_id="point-in-time:2026-05-05:ukpga/2026/14")

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_fetch_document_ref_xml(client: object, document: object, as_enacted: bool, at: str | None) -> bytes:
        calls["fetch_args"] = (client, document, as_enacted, at)
        return b"<Legislation />"

    def fake_render_document_markdown_from_xml(xml_content: bytes) -> str:
        calls["render_args"] = xml_content
        return "---\ntitle: Example\n---\n\n# Example\n"

    def fake_publish_document_text_to_postgres(**kwargs: object) -> object:
        calls["publish_args"] = kwargs
        return published_version

    monkeypatch.setattr("git_legislation.cli.create_client", lambda log: FakeClient())
    monkeypatch.setattr("git_legislation.cli.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr(
        "git_legislation.cli.render_document_markdown_from_xml",
        fake_render_document_markdown_from_xml,
    )
    monkeypatch.setattr(
        "git_legislation.cli.publish_document_text_to_postgres",
        fake_publish_document_text_to_postgres,
    )

    result = CliRunner().invoke(
        app,
        [
            "ingest-document",
            "ukpga/2026/14",
            "--at",
            "2026-05-05",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert calls["render_args"] == b"<Legislation />"
    assert calls["publish_args"] == {
        "database_url": "postgres://example",
        "source_path": ("ukpga", "2026", "14"),
        "xml_content": b"<Legislation />",
        "markdown": "---\ntitle: Example\n---\n\n# Example\n",
        "collection": "point-in-time",
        "snapshot_date": "2026-05-05",
        "object_store_root": tmp_path / "objects",
        "object_store_bucket": "legislation",
    }
    assert "created document version point-in-time:2026-05-05:ukpga/2026/14" in result.output


def test_ingest_point_in_time_year_command_publishes_each_document(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {"recorded": []}
    documents = [
        SimpleNamespace(path=("ukpga", "2026", "14")),
        SimpleNamespace(path=("ukpga", "2026", "15")),
    ]

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def commit(self) -> None:
            calls["committed"] = True

    connection = FakeConnection()

    def fake_fetch_year_document_refs(client: object, legislation_type: str, year: int, log: object) -> object:
        calls["refs_args"] = (client, legislation_type, year, log)
        return documents

    def fake_fetch_document_ref_xml(client: object, document: SimpleNamespace, at: str) -> bytes:
        return f"<Legislation>{document.path[-1]}</Legislation>".encode()

    def fake_render_document_markdown_from_xml(xml_content: bytes) -> str:
        return f"---\ntitle: Example {xml_content.decode()}\n---\n\n# Example\n"

    def fake_publish_document_text(connection_arg: object, **kwargs: Any) -> object:
        kwargs["connection"] = connection_arg
        calls.setdefault("publish_args", []).append(kwargs)
        source_path = kwargs["source_path"]
        return SimpleNamespace(
            document_id="/".join(source_path),
            version_id=f"point-in-time:2026-05-05:{'/'.join(source_path)}",
            source_uri=None,
            source_sha256="abc",
            created=True,
        )

    monkeypatch.setattr("git_legislation.cli.create_client", lambda log: FakeClient())
    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: connection)
    monkeypatch.setattr("git_legislation.cli.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("git_legislation.cli.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr(
        "git_legislation.cli.render_document_markdown_from_xml",
        fake_render_document_markdown_from_xml,
    )
    monkeypatch.setattr("git_legislation.cli.publish_document_text", fake_publish_document_text)
    monkeypatch.setattr("git_legislation.cli.create_publish_run", lambda *args, **kwargs: 123)
    monkeypatch.setattr(
        "git_legislation.cli.finish_publish_run",
        lambda *args, **kwargs: calls.setdefault("finished", True),
    )
    monkeypatch.setattr(
        "git_legislation.cli.record_publish_observation",
        lambda _connection, run_id, version: calls["recorded"].append((run_id, version.version_id)),
    )

    result = CliRunner().invoke(
        app,
        [
            "ingest-point-in-time-year",
            "ukpga",
            "2026",
            "--at",
            "2026-05-05",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert calls["refs_args"][1:] == ("ukpga", 2026, typer.echo)
    assert len(calls["publish_args"]) == 2
    assert calls["publish_args"][0]["connection"] is connection
    assert calls["publish_args"][0]["source_path"] == ("ukpga", "2026", "14")
    assert calls["recorded"] == [
        (123, "point-in-time:2026-05-05:ukpga/2026/14"),
        (123, "point-in-time:2026-05-05:ukpga/2026/15"),
    ]
    assert calls["committed"] is True
    assert "Published 2 Markdown documents to Postgres" in result.output


def test_ingest_point_in_time_corpus_command_runs_supported_year_range(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {"years": []}

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def commit(self) -> None:
            calls["committed"] = True

    connection = FakeConnection()

    def fake_ingest_point_in_time_year(
        connection_arg: object,
        client: object,
        object_store: object,
        legislation_type: str,
        year: int,
        at: str,
        log: object,
    ) -> object:
        calls["years"].append((connection_arg, client, legislation_type, year, at, log))
        return SimpleNamespace(
            scanned=1,
            published=1,
            created_versions=1,
            reused_versions=0,
            failures=[],
        )

    monkeypatch.setattr("git_legislation.cli.create_client", lambda log: FakeClient())
    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: connection)
    monkeypatch.setattr("git_legislation.cli._ingest_point_in_time_year", fake_ingest_point_in_time_year)

    result = CliRunner().invoke(
        app,
        [
            "ingest-point-in-time-corpus",
            "--legislation-type",
            "ukmo",
            "--at",
            "2021-06-01",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert [(item[2], item[3], item[4], item[5]) for item in calls["years"]] == [
        ("ukmo", 2020, "2021-06-01", typer.echo),
        ("ukmo", 2021, "2021-06-01", typer.echo),
    ]
    assert all(item[0] is connection for item in calls["years"])
    assert calls["committed"] is True
    assert "Published 2 Markdown documents to Postgres" in result.output


def test_ingest_point_in_time_corpus_command_defaults_to_todays_snapshot(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {"years": []}

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def commit(self) -> None:
            calls["committed"] = True

    def fake_ingest_point_in_time_year(connection: object, **kwargs: object) -> object:
        kwargs["connection"] = connection
        calls["years"].append(kwargs)
        return SimpleNamespace(scanned=0, published=0, created_versions=0, reused_versions=0, failures=[])

    monkeypatch.setattr("git_legislation.cli.date", FixedDate)
    monkeypatch.setattr("git_legislation.cli.create_client", lambda log: FakeClient())
    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: FakeConnection())
    monkeypatch.setattr(
        "git_legislation.cli._point_in_time_corpus_types",
        lambda legislation_types, start_legislation_type=None: ("ukmo",),
    )
    monkeypatch.setattr("git_legislation.cli._ingest_point_in_time_year", fake_ingest_point_in_time_year)

    result = CliRunner().invoke(
        app,
        [
            "ingest-point-in-time-corpus",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert {call["at"] for call in calls["years"]} == {"2026-05-03"}


def test_ingest_point_in_time_corpus_command_can_resume_from_type_and_year(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {"years": []}

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def commit(self) -> None:
            calls["commits"] = calls.get("commits", 0) + 1

    def fake_ingest_point_in_time_year(
        connection: object,
        client: object,
        object_store: object,
        legislation_type: str,
        year: int,
        at: str,
        log: object,
    ) -> object:
        calls["years"].append((legislation_type, year, at))
        return SimpleNamespace(scanned=0, published=0, created_versions=0, reused_versions=0, failures=[])

    monkeypatch.setattr("git_legislation.cli.create_client", lambda log: FakeClient())
    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: FakeConnection())
    monkeypatch.setattr("git_legislation.cli._ingest_point_in_time_year", fake_ingest_point_in_time_year)

    result = CliRunner().invoke(
        app,
        [
            "ingest-point-in-time-corpus",
            "--start-legislation-type",
            "ukmo",
            "--start-year",
            "2021",
            "--at",
            "2022-06-01",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert calls["years"] == [
        ("ukmo", 2021, "2022-06-01"),
        ("ukmo", 2022, "2022-06-01"),
    ]
    assert calls["commits"] == 2


def test_corpus_counts_command_reports_database_and_object_store_counts(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "objects" / "legislation" / "markdown").mkdir(parents=True)
    (tmp_path / "objects" / "legislation" / "markdown" / "a.md").write_text("hello")
    (tmp_path / "objects" / "legislation" / "xml").mkdir()
    (tmp_path / "objects" / "legislation" / "xml" / "a.xml").write_text("<xml />")

    counts = {
        "documents": 1,
        "document_versions": 2,
        "provisions": 3,
        "storage_objects": 4,
        "document_files": 5,
        "fetch_runs": 6,
        "fetch_observations": 7,
    }

    class FakeResult:
        def __init__(self, count: int) -> None:
            self.count = count

        def fetchone(self) -> tuple[int]:
            return (self.count,)

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def execute(self, sql: str) -> FakeResult:
            table = sql.split(" from ", 1)[1]
            return FakeResult(counts[table])

    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: FakeConnection())

    result = CliRunner().invoke(
        app,
        [
            "corpus-counts",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert "- documents: 1" in result.output
    assert "- fetch_observations: 7" in result.output
    assert "- object_store_files: 2" in result.output
    assert "- object_store_bytes: 12" in result.output


def test_parse_pdf_sample_command_runs_experimental_parser(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {}

    class FakeClient:
        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def commit(self) -> None:
            calls["committed"] = True

    connection = FakeConnection()

    def fake_parse_pdf_sample(connection_arg: object, **kwargs: Any) -> object:
        calls["connection"] = connection_arg
        calls["parse_args"] = kwargs
        return SimpleNamespace(scanned=2, parsed=2, failures=[], artifacts=[])

    monkeypatch.setattr("git_legislation.cli.create_client", lambda log: FakeClient())
    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: connection)
    monkeypatch.setattr("git_legislation.cli.parse_pdf_sample", fake_parse_pdf_sample)

    result = CliRunner().invoke(
        app,
        [
            "parse-pdf-sample",
            "--at",
            "2026-05-05",
            "--legislation-type",
            "ukpga",
            "--limit",
            "2",
            "--include-full-text",
            "--force",
            "--no-ocr",
            "--target-pages",
            "1-2",
            "--lit-executable",
            "lit-test",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert calls["connection"] is connection
    assert calls["parse_args"]["at"] == "2026-05-05"
    assert calls["parse_args"]["legislation_type"] == "ukpga"
    assert calls["parse_args"]["limit"] == 2
    assert calls["parse_args"]["only_metadata"] is False
    assert calls["parse_args"]["force"] is True
    assert calls["parse_args"]["no_ocr"] is True
    assert calls["parse_args"]["target_pages"] == "1-2"
    assert calls["parse_args"]["lit_executable"] == "lit-test"
    assert calls["parse_args"]["object_store"].root == tmp_path / "objects"
    assert calls["committed"] is True
    assert "Parsed 2 PDF-backed documents with LiteParse" in result.output


def test_normalize_liteparse_markdown_sample_command_runs_normalizer(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, Any] = {}

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def commit(self) -> None:
            calls["committed"] = True

    connection = FakeConnection()

    def fake_normalize_liteparse_markdown_sample(connection_arg: object, **kwargs: Any) -> object:
        calls["connection"] = connection_arg
        calls["normalize_args"] = kwargs
        return SimpleNamespace(scanned=1, normalized=1, failures=[], markdown_object_keys=["markdown/liteparse/a.md"])

    monkeypatch.setattr("git_legislation.cli.psycopg.connect", lambda _: connection)
    monkeypatch.setattr(
        "git_legislation.cli.normalize_liteparse_markdown_sample",
        fake_normalize_liteparse_markdown_sample,
    )

    result = CliRunner().invoke(
        app,
        [
            "normalize-liteparse-markdown-sample",
            "--at",
            "2026-05-05",
            "--legislation-type",
            "ukpga",
            "--limit",
            "1",
            "--force",
            "--database-url",
            "postgres://example",
            "--object-store-root",
            str(tmp_path / "objects"),
        ],
    )

    assert result.exit_code == 0
    assert calls["connection"] is connection
    assert calls["normalize_args"]["at"] == "2026-05-05"
    assert calls["normalize_args"]["legislation_type"] == "ukpga"
    assert calls["normalize_args"]["limit"] == 1
    assert calls["normalize_args"]["force"] is True
    assert calls["normalize_args"]["object_store"].root == tmp_path / "objects"
    assert calls["committed"] is True
    assert "Normalized 1 LiteParse reports to Markdown" in result.output
