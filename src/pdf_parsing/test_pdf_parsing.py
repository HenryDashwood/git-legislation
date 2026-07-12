from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

from object_store import LocalObjectStore
from pdf_parsing import (
    LiteparseMarkdownCandidate,
    PdfParseCandidate,
    cache_document_marker_markdown,
    cache_document_pdf,
    liteparse_json_to_markdown,
    liteparse_markdown_object_key,
    liteparse_report_object_key,
    liteparse_text_object_key,
    marker_markdown_object_key,
    normalize_liteparse_markdown_sample,
    parse_pdf_sample,
    pdf_object_key,
)

PDF_URL = "https://www.legislation.gov.uk/ukpga/1963/1/pdfs/ukpga_19630001_en.pdf"


def test_pdf_and_liteparse_object_keys_are_deterministic(tmp_path: Path) -> None:
    candidate = PdfParseCandidate(
        document_file_id=1,
        document_id="ukpga/1963/1",
        version_id="point-in-time:2026-05-05:ukpga/1963/1",
        source_url=PDF_URL,
        object_key=None,
        source_path=("ukpga", "1963", "1"),
        version_kind="point_in_time",
        snapshot_date="2026-05-05",
    )
    pdf_key = pdf_object_key(candidate)

    assert pdf_key.startswith("pdf/point-in-time/2026-05-05/ukpga/1963/1/ukpga_19630001_en-")
    assert pdf_key.endswith(".pdf")

    pdf_object = LocalObjectStore(root=tmp_path / "objects").put_bytes(b"%PDF", key=pdf_key)

    assert liteparse_text_object_key(candidate, pdf_object).startswith(
        "extracted-text/liteparse/point-in-time/2026-05-05/ukpga/1963/1/ukpga_19630001_en-"
    )
    assert liteparse_text_object_key(candidate, pdf_object).endswith(".txt")
    assert liteparse_report_object_key(candidate, pdf_object).endswith(".json")
    assert marker_markdown_object_key(candidate, pdf_object).startswith(
        "markdown/marker/point-in-time/2026-05-05/ukpga/1963/1/ukpga_19630001_en-"
    )
    assert marker_markdown_object_key(candidate, pdf_object).endswith(".md")


def test_parse_pdf_sample_caches_pdf_and_records_liteparse_artifacts(tmp_path: Path) -> None:
    connection = RecordingConnection(
        rows=[
            (
                1,
                "ukpga/1963/1",
                "point-in-time:2026-05-05:ukpga/1963/1",
                PDF_URL,
                None,
                ["ukpga", "1963", "1"],
                "point_in_time",
                "2026-05-05",
            )
        ]
    )
    client = FakeClient()
    object_store = LocalObjectStore(root=tmp_path / "objects")
    commands: list[list[str]] = []

    def fake_runner(args: list[str]) -> CompletedProcess[str]:
        commands.append(args)
        output_path = Path(args[args.index("-o") + 1])
        output_path.write_text(
            "Section 1 Example extracted text" if args[args.index("--format") + 1] == "text" else '{"pages":[]}'
        )
        return CompletedProcess(args=args, returncode=0)

    report = parse_pdf_sample(
        connection,
        client=client,
        object_store=object_store,
        at="2026-05-05",
        limit=1,
        legislation_type="ukpga",
        command_runner=fake_runner,
    )

    assert report.scanned == 1
    assert report.parsed == 1
    assert report.failures == []
    assert client.urls == [PDF_URL]
    assert len(commands) == 2
    assert commands[0][commands[0].index("--format") + 1] == "text"
    assert commands[1][commands[1].index("--format") + 1] == "json"
    assert report.artifacts[0].word_count == 5
    assert report.artifacts[0].text_object.path.read_text() == "Section 1 Example extracted text"
    assert report.artifacts[0].report_object.path.read_text() == '{"pages":[]}'
    assert any(
        params[0] == report.artifacts[0].pdf_object.key
        for sql, params in connection.executed
        if sql.startswith("update document_files")
    )
    inserted_file_kinds = [
        params[2] for sql, params in connection.executed if "insert into document_files" in sql and len(params) >= 3
    ]
    assert "extracted_text" in inserted_file_kinds
    assert "report" in inserted_file_kinds


def test_cache_document_pdf_caches_target_document_without_liteparse(tmp_path: Path) -> None:
    connection = RecordingConnection(
        rows=[
            (
                1,
                "ukpga/1963/1",
                "point-in-time:2026-05-05:ukpga/1963/1",
                PDF_URL,
                None,
                ["ukpga", "1963", "1"],
                "point_in_time",
                "2026-05-05",
            )
        ]
    )
    client = FakeClient()
    object_store = LocalObjectStore(root=tmp_path / "objects")

    pdf_object = cache_document_pdf(
        connection,
        client=client,
        object_store=object_store,
        source_path=("ukpga", "1963", "1"),
        at="2026-05-05",
    )

    assert client.urls == [PDF_URL]
    assert pdf_object.key.startswith("pdf/point-in-time/2026-05-05/ukpga/1963/1/ukpga_19630001_en-")
    assert pdf_object.path.read_bytes() == b"%PDF-1.7"
    assert any(
        params[0] == pdf_object.key for sql, params in connection.executed if sql.startswith("update document_files")
    )
    select_sql, select_params = connection.executed[0]
    assert "d.source_path = %s" in select_sql
    assert "dv.snapshot_date = %s" in select_sql
    assert select_params == (["ukpga", "1963", "1"], "2026-05-05")


def test_cache_document_marker_markdown_records_noncanonical_markdown(tmp_path: Path) -> None:
    connection = RecordingConnection(
        rows=[
            (
                1,
                "ukpga/1963/1",
                "point-in-time:2026-05-05:ukpga/1963/1",
                PDF_URL,
                None,
                ["ukpga", "1963", "1"],
                "point_in_time",
                "2026-05-05",
            )
        ]
    )
    client = FakeClient()
    object_store = LocalObjectStore(root=tmp_path / "objects")
    commands: list[list[str]] = []

    def fake_runner(args: list[str]) -> CompletedProcess[str]:
        commands.append(args)
        output_dir = Path(args[args.index("--output_dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "source.md").write_text("# Marker extracted text\n\nBody text from PDF.")
        return CompletedProcess(args=args, returncode=0)

    markdown_object = cache_document_marker_markdown(
        connection,
        client=client,
        object_store=object_store,
        source_path=("ukpga", "1963", "1"),
        at="2026-05-05",
        marker_executable="marker_single",
        command_runner=fake_runner,
    )

    assert client.urls == [PDF_URL]
    assert len(commands) == 1
    assert commands[0][0] == "marker_single"
    assert commands[0][1].endswith(".pdf")
    assert commands[0][commands[0].index("--output_format") + 1] == "markdown"
    assert "--output_dir" in commands[0]
    assert "--disable_image_extraction" in commands[0]
    assert markdown_object.key.startswith("markdown/marker/point-in-time/2026-05-05/ukpga/1963/1/")
    assert markdown_object.path.read_text() == "# Marker extracted text\n\nBody text from PDF."
    inserted_file_kinds = [
        params[2] for sql, params in connection.executed if "insert into document_files" in sql and len(params) >= 3
    ]
    assert "markdown" in inserted_file_kinds


def test_liteparse_json_to_markdown_drops_likely_marginalia() -> None:
    markdown = liteparse_json_to_markdown(
        {
            "pages": [
                {
                    "page": 1,
                    "text_items": [
                        text_item("Marginal note", 0, 100),
                        text_item("WHEREAS", 90, 100),
                        text_item("the", 160, 100),
                        text_item("Sea", 190, 100),
                        text_item("Sand", 220, 100),
                        text_item("Short note", 0, 112),
                        text_item("by", 90, 112),
                        text_item("long", 115, 112),
                        text_item("trial", 150, 112),
                        text_item("Another note", 0, 124),
                        text_item("hath", 90, 124),
                        text_item("beene", 125, 124),
                        text_item("found.", 170, 124),
                    ],
                }
            ]
        },
        title="ukpga/1963/1",
    )

    assert "# ukpga/1963/1" in markdown
    assert "<!-- Page 1 -->" in markdown
    assert "Marginal note" not in markdown
    assert "Short note" not in markdown
    assert "WHEREAS the Sea Sand by long trial hath beene found." in markdown


def test_normalize_liteparse_markdown_sample_records_noncanonical_markdown(tmp_path: Path) -> None:
    connection = RecordingConnection(
        rows=[
            (
                "ukpga/1963/1",
                "point-in-time:2026-05-05:ukpga/1963/1",
                PDF_URL,
                "reports/liteparse/point-in-time/2026-05-05/ukpga/1963/1/source.json",
                ["ukpga", "1963", "1"],
                "point_in_time",
                "2026-05-05",
            )
        ]
    )
    object_store = LocalObjectStore(root=tmp_path / "objects")
    report_object = object_store.put_text(
        '{"pages":[{"page":1,"text_items":[{"text":"Example","x":80,"y":10,"height":8,"confidence":0.9}]}]}',
        key="reports/liteparse/point-in-time/2026-05-05/ukpga/1963/1/source.json",
        content_type="application/json",
    )

    report = normalize_liteparse_markdown_sample(
        connection,
        object_store=object_store,
        at="2026-05-05",
        legislation_type="ukpga",
        limit=1,
    )

    candidate = LiteparseMarkdownCandidate(
        document_id="ukpga/1963/1",
        version_id="point-in-time:2026-05-05:ukpga/1963/1",
        source_url=PDF_URL,
        report_object_key=report_object.key,
        source_path=("ukpga", "1963", "1"),
        version_kind="point_in_time",
        snapshot_date="2026-05-05",
    )
    markdown_key = liteparse_markdown_object_key(candidate)

    assert report.scanned == 1
    assert report.normalized == 1
    assert report.markdown_object_keys == [markdown_key]
    select_sql = next(sql for sql, _ in connection.executed if sql.startswith("select df.document_id"))
    assert "reports/liteparse/%%" in select_sql
    assert (tmp_path / "objects" / "legislation" / markdown_key).read_text().startswith("# ukpga/1963/1")
    inserted_file_kinds = [
        params[2] for sql, params in connection.executed if "insert into document_files" in sql and len(params) >= 3
    ]
    assert "markdown" in inserted_file_kinds


def text_item(text: str, x: float, y: float) -> dict[str, object]:
    return {"text": text, "x": x, "y": y, "height": 8, "confidence": 0.9}


class FakeResponse:
    status_code = 200
    content = b"%PDF-1.7"

    def raise_for_status(self) -> None:
        return None


class FakeClient:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return FakeResponse()


class RecordingConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> "RecordingCursor":
        normalized_sql = " ".join(sql.split())
        self.executed.append((normalized_sql, params))
        if normalized_sql.startswith("select df.id"):
            return RecordingCursor(self.rows)
        if normalized_sql.startswith("select df.document_id"):
            return RecordingCursor(self.rows)
        return RecordingCursor([])


class RecordingCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def test_ensure_pdf_cached_rejects_html_and_heals_poisoned_cache(tmp_path: Path) -> None:
    from pdf_parsing import ensure_pdf_cached

    candidate = PdfParseCandidate(
        document_file_id=1,
        document_id="uksi/1954/898",
        version_id="point-in-time:2026-05-05:uksi/1954/898",
        source_url="https://www.legislation.gov.uk/uksi/1954/898/made/data.pdf",
        object_key=None,
        source_path=("uksi", "1954", "898"),
        version_kind="point_in_time",
        snapshot_date="2026-05-05",
    )
    object_store = LocalObjectStore(root=tmp_path / "objects")
    connection = RecordingConnection([])

    class HtmlResponse:
        status_code = 200
        content = b"<!DOCTYPE html\n<html>error page</html>"

        def raise_for_status(self) -> None:
            return None

    class HtmlClient:
        def get(self, url: str) -> HtmlResponse:
            return HtmlResponse()

    try:
        ensure_pdf_cached(connection, candidate, client=HtmlClient(), object_store=object_store)
        raised = False
    except ValueError as error:
        raised = True
        assert "not a PDF" in str(error)
    assert raised
    assert not object_store.path_for_key(pdf_object_key(candidate)).exists()

    # A poisoned cache entry from before validation existed is replaced.
    poisoned_key = pdf_object_key(candidate)
    poisoned_path = object_store.path_for_key(poisoned_key)
    poisoned_path.parent.mkdir(parents=True, exist_ok=True)
    poisoned_path.write_bytes(b"<!DOCTYPE html\n<html>old error page</html>")

    pdf_object = ensure_pdf_cached(connection, candidate, client=FakeClient(), object_store=object_store)

    assert object_store.path_for_key(pdf_object.key).read_bytes() == b"%PDF-1.7"


def test_ensure_pdf_cached_waits_out_202_generation(monkeypatch, tmp_path: Path) -> None:
    from pdf_parsing import ensure_pdf_cached

    candidate = PdfParseCandidate(
        document_file_id=1,
        document_id="aep/Edw2/7/0",
        version_id="point-in-time:2026-05-05:aep/Edw2/7/0",
        source_url="https://www.legislation.gov.uk/aep/Edw2/7/0/2026-05-05/data.pdf",
        object_key=None,
        source_path=("aep", "Edw2", "7", "0"),
        version_kind="point_in_time",
        snapshot_date="2026-05-05",
    )
    object_store = LocalObjectStore(root=tmp_path / "objects")
    connection = RecordingConnection([])
    sleep_calls: list[float] = []
    monkeypatch.setattr("pdf_parsing.time.sleep", sleep_calls.append)

    class GeneratingClient:
        def __init__(self) -> None:
            self.calls = 0

        def get(self, url: str):
            self.calls += 1
            calls = self.calls

            class R:
                status_code = 202 if calls <= 2 else 200
                content = b"please wait" if calls <= 2 else b"%PDF-1.4 generated"

                def raise_for_status(self) -> None:
                    return None

            return R()

    client = GeneratingClient()
    pdf_object = ensure_pdf_cached(connection, candidate, client=client, object_store=object_store)

    assert client.calls == 3
    assert sleep_calls == [5.0, 5.0]
    assert object_store.path_for_key(pdf_object.key).read_bytes() == b"%PDF-1.4 generated"


def test_permanent_pdf_failure_classifier() -> None:
    from pdf_parsing import _is_permanent_pdf_failure

    assert _is_permanent_pdf_failure(ValueError("Response from https://x is not a PDF"))
    assert _is_permanent_pdf_failure(Exception("HTTP status 404 for https://x"))
    assert not _is_permanent_pdf_failure(Exception("HTTP status 432 for https://x"))
    assert not _is_permanent_pdf_failure(Exception("HTTP status 429 for https://x"))
    assert not _is_permanent_pdf_failure(TimeoutError("timed out"))
