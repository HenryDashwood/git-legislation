from datetime import date
from pathlib import Path

import httpx

from fetchers.legislationdotgovdotuk import (
    DocumentRef,
    create_client,
    document_xml_url,
    fetch_document_xml,
    fetch_enacted_corpus,
    fetch_year_document_refs,
    fetch_year_documents,
    fetch_year_feed,
    parse_year_feed,
    write_document_xml,
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


def test_fetch_year_document_refs_follows_next_feed_links() -> None:
    requested_urls: list[str] = []

    page_1 = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <link rel="next" href="https://www.legislation.gov.uk/ukpga/2020/data.feed?page=2"/>
      <entry>
        <title>Act 2</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukpga/2020/2"/>
      </entry>
    </feed>
    """
    page_2 = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Act 1</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukpga/2020/1"/>
      </entry>
    </feed>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == "https://www.legislation.gov.uk/ukpga/2020/data.feed":
            return httpx.Response(200, content=page_1)
        if str(request.url) == "https://www.legislation.gov.uk/ukpga/2020/data.feed?page=2":
            return httpx.Response(200, content=page_2)
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    documents = fetch_year_document_refs(client, legislation_type="ukpga", year=2020)

    assert requested_urls == [
        "https://www.legislation.gov.uk/ukpga/2020/data.feed",
        "https://www.legislation.gov.uk/ukpga/2020/data.feed?page=2",
    ]
    assert documents == [
        DocumentRef(legislation_type="ukpga", year=2020, number=2, title="Act 2"),
        DocumentRef(legislation_type="ukpga", year=2020, number=1, title="Act 1"),
    ]


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

    def fake_fetch_year_document_refs(
        client: httpx.Client,
        legislation_type: str,
        year: int,
    ) -> list[DocumentRef]:
        calls["fetch_year_document_refs_args"] = (legislation_type, year)
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

    monkeypatch.setattr(
        "fetchers.legislationdotgovdotuk.fetch_year_document_refs",
        fake_fetch_year_document_refs,
    )
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_xml", fake_fetch_document_xml)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.write_document_xml", fake_write_document_xml)

    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        as_enacted=True,
        output_root=tmp_path,
    )

    assert calls["fetch_year_document_refs_args"] == ("ukpga", 2026)
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

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
    ) -> list[Path]:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return [output_root / "xml" / "enacted" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr(
        "fetchers.legislationdotgovdotuk.fetch_year_documents",
        fake_fetch_year_documents,
    )

    paths = fetch_enacted_corpus(
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
    assert paths == [
        tmp_path / "xml" / "enacted" / "ukpga" / "2025" / "1" / "data.xml",
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "1" / "data.xml",
    ]
