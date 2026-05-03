from datetime import date
from pathlib import Path

import httpx

from fetchers.legislationdotgovdotuk import (
    DocumentRef,
    FetchManifest,
    FetchRecord,
    create_client,
    document_xml_url,
    fetch_document_xml,
    fetch_enacted_corpus,
    fetch_year_documents,
    fetch_year_documents_manifest,
    fetch_year_feed,
    parse_year_feed,
    write_document_xml,
    write_fetch_manifest,
    year_feed_url,
)


def test_document_xml_url_for_numbered_legislation() -> None:
    assert (
        document_xml_url(legislation_type="ukpga", year=2026, number=14)
        == "https://www.legislation.gov.uk/ukpga/2026/14/data.xml"
    )


def test_document_xml_url_for_enacted_legislation() -> None:
    assert (
        document_xml_url(legislation_type="ukpga", year=2026, number=14, as_enacted=True)
        == "https://www.legislation.gov.uk/ukpga/2026/14/enacted/data.xml"
    )


def test_document_xml_url_for_point_in_time_legislation() -> None:
    assert (
        document_xml_url(legislation_type="ukpga", year=2026, number=14, at="2026-03-18")
        == "https://www.legislation.gov.uk/ukpga/2026/14/2026-03-18/data.xml"
    )


def test_year_feed_url_for_legislation_type_and_year() -> None:
    assert year_feed_url(legislation_type="ukpga", year=2026) == "https://www.legislation.gov.uk/ukpga/2026/data.feed"


def test_parse_year_feed_reads_document_entries() -> None:
    feed = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Industry and Exports (Financial Assistance) Act 2026</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukpga/2026/14"/>
      </entry>
    </feed>
    """

    documents = parse_year_feed(feed)

    assert len(documents) == 1
    assert documents[0].legislation_type == "ukpga"
    assert documents[0].year == 2026
    assert documents[0].number == 14
    assert documents[0].title == "Industry and Exports (Financial Assistance) Act 2026"


def test_parse_year_feed_prefers_self_id_link_over_versioned_alternate_links() -> None:
    feed = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Industry and Exports (Financial Assistance) Act 2026</title>
        <link rel="self" href="http://www.legislation.gov.uk/id/ukpga/2026/14"/>
        <link href="http://www.legislation.gov.uk/ukpga/2026/14/2026-03-18"/>
        <link rel="alternate" type="application/xml" href="http://www.legislation.gov.uk/ukpga/2026/14/2026-03-18/data.xml"/>
      </entry>
    </feed>
    """

    documents = parse_year_feed(feed)

    assert documents[0].legislation_type == "ukpga"
    assert documents[0].year == 2026
    assert documents[0].number == 14


def test_fetch_document_xml_gets_the_document_xml_url() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"<Legislation>example</Legislation>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    content = fetch_document_xml(client, legislation_type="ukpga", year=2026, number=14)

    assert content == b"<Legislation>example</Legislation>"
    assert requested_urls == ["https://www.legislation.gov.uk/ukpga/2026/14/data.xml"]


def test_fetch_document_xml_can_get_enacted_xml() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"<Legislation>enacted</Legislation>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    content = fetch_document_xml(client, legislation_type="ukpga", year=2026, number=14, as_enacted=True)

    assert content == b"<Legislation>enacted</Legislation>"
    assert requested_urls == ["https://www.legislation.gov.uk/ukpga/2026/14/enacted/data.xml"]


def test_fetch_year_feed_gets_the_year_feed_url() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"<feed>example</feed>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    content = fetch_year_feed(client, legislation_type="ukpga", year=2026)

    assert content == b"<feed>example</feed>"
    assert requested_urls == ["https://www.legislation.gov.uk/ukpga/2026/data.feed"]


def test_create_client_sets_legislation_api_headers() -> None:
    with create_client() as client:
        assert "git-legislation" in client.headers["User-Agent"]
        assert client.headers["Accept"] == "application/xml"


class FixedDate(date):
    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2026, 5, 3)


def test_write_document_xml_writes_current_xml_to_todays_point_in_time_folder(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.date", FixedDate)

    path = write_document_xml(
        b"<Legislation>example</Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"
    assert path.read_bytes() == b"<Legislation>example</Legislation>"


def test_write_document_xml_writes_enacted_xml(tmp_path: Path) -> None:
    path = write_document_xml(
        b"<Legislation>example</Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        as_enacted=True,
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml"
    assert path.read_bytes() == b"<Legislation>example</Legislation>"


def test_write_document_xml_writes_point_in_time_xml(tmp_path: Path) -> None:
    path = write_document_xml(
        b"<Legislation>example</Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        at="2026-03-18",
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "point-in-time" / "2026-03-18" / "ukpga" / "2026" / "14" / "data.xml"
    assert path.read_bytes() == b"<Legislation>example</Legislation>"


def test_fetch_year_documents_fetches_and_writes_each_document(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {"fetch_documents": [], "writes": []}

    def fake_fetch_year_feed(client: httpx.Client, legislation_type: str, year: int) -> bytes:
        calls["fetch_year_args"] = (legislation_type, year)
        return b"<feed>example</feed>"

    def fake_parse_year_feed(feed: bytes) -> list[DocumentRef]:
        calls["feed"] = feed
        return [
            DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14"),
            DocumentRef(legislation_type="ukpga", year=2026, number=13, title="Act 13"),
        ]

    def fake_fetch_document_xml(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
    ) -> bytes:
        calls["fetch_documents"].append((legislation_type, year, number, as_enacted, at))
        return f"<Legislation>{number}</Legislation>".encode()

    def fake_write_document_xml(
        content: bytes,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
    ) -> Path:
        calls["writes"].append((content, legislation_type, year, number, as_enacted, at, output_root))
        return output_root / "xml" / "enacted" / legislation_type / str(year) / str(number) / "data.xml"

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_feed", fake_fetch_year_feed)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.parse_year_feed", fake_parse_year_feed)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_xml", fake_fetch_document_xml)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.write_document_xml", fake_write_document_xml)

    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        as_enacted=True,
        output_root=tmp_path,
    )

    assert calls["fetch_year_args"] == ("ukpga", 2026)
    assert calls["feed"] == b"<feed>example</feed>"
    assert calls["fetch_documents"] == [("ukpga", 2026, 14, True, None), ("ukpga", 2026, 13, True, None)]
    assert calls["writes"] == [
        (b"<Legislation>14</Legislation>", "ukpga", 2026, 14, True, None, tmp_path),
        (b"<Legislation>13</Legislation>", "ukpga", 2026, 13, True, None, tmp_path),
    ]
    assert paths == [
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml",
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "13" / "data.xml",
    ]


def test_fetch_enacted_corpus_fetches_each_year_in_range(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int, bool, str | None, Path]] = []

    def fake_fetch_year_documents_manifest(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
    ) -> FetchManifest:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return FetchManifest(
            corpus="enacted",
            legislation_type=legislation_type,
            start_year=year,
            end_year=year,
            records=[
                FetchRecord(
                    status="fetched",
                    legislation_type=legislation_type,
                    year=year,
                    number=1,
                    title="Act 1",
                    path=output_root / "xml" / "enacted" / legislation_type / str(year) / "1" / "data.xml",
                )
            ],
        )

    monkeypatch.setattr(
        "fetchers.legislationdotgovdotuk.fetch_year_documents_manifest",
        fake_fetch_year_documents_manifest,
    )

    manifest = fetch_enacted_corpus(
        httpx.Client(),
        legislation_type="ukpga",
        start_year=2025,
        end_year=2026,
        output_root=tmp_path,
    )

    assert calls == [
        ("ukpga", 2025, True, None, tmp_path),
        ("ukpga", 2026, True, None, tmp_path),
    ]
    assert manifest.paths == [
        tmp_path / "xml" / "enacted" / "ukpga" / "2025" / "1" / "data.xml",
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "1" / "data.xml",
    ]


def test_fetch_year_documents_manifest_records_missing_document_xml(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch_year_feed(client: httpx.Client, legislation_type: str, year: int) -> bytes:
        return b"<feed>example</feed>"

    def fake_parse_year_feed(feed: bytes) -> list[DocumentRef]:
        return [DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14")]

    def fake_fetch_document_xml(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
    ) -> bytes:
        request = httpx.Request("GET", "https://www.legislation.gov.uk/ukpga/2026/14/enacted/data.xml")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_feed", fake_fetch_year_feed)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.parse_year_feed", fake_parse_year_feed)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_xml", fake_fetch_document_xml)

    manifest = fetch_year_documents_manifest(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        as_enacted=True,
        output_root=tmp_path,
    )

    assert manifest.records == [
        FetchRecord(
            status="missing",
            legislation_type="ukpga",
            year=2026,
            number=14,
            title="Act 14",
            url="https://www.legislation.gov.uk/ukpga/2026/14/enacted/data.xml",
            error="HTTP 404",
        )
    ]


def test_fetch_year_documents_manifest_records_missing_year_feed(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch_year_feed(client: httpx.Client, legislation_type: str, year: int) -> bytes:
        request = httpx.Request("GET", "https://www.legislation.gov.uk/ukpga/1800/data.feed")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("not found", request=request, response=response)

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_feed", fake_fetch_year_feed)

    manifest = fetch_year_documents_manifest(
        httpx.Client(),
        legislation_type="ukpga",
        year=1800,
        as_enacted=True,
        output_root=tmp_path,
    )

    assert manifest.records == [
        FetchRecord(
            status="missing-feed",
            legislation_type="ukpga",
            year=1800,
            url="https://www.legislation.gov.uk/ukpga/1800/data.feed",
            error="HTTP 404",
        )
    ]


def test_write_fetch_manifest_writes_json(tmp_path: Path) -> None:
    manifest = FetchManifest(
        corpus="enacted",
        legislation_type="ukpga",
        start_year=2025,
        end_year=2026,
        records=[
            FetchRecord(
                status="fetched",
                legislation_type="ukpga",
                year=2026,
                number=14,
                title="Act 14",
                path=tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml",
            )
        ],
    )

    path = write_fetch_manifest(manifest, output_root=tmp_path)

    assert path == tmp_path / "manifests" / "enacted" / "ukpga" / "2025-2026.json"
    assert '"status": "fetched"' in path.read_text()
    assert '"path": "' in path.read_text()
