from datetime import date
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError

import httpx
import pytest

from fetchers.legislationdotgovdotuk import (
    POINT_IN_TIME_CORPUS_END_YEARS,
    POINT_IN_TIME_CORPUS_START_YEARS,
    SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES,
    DocumentRef,
    FetchFailure,
    FetchProbe,
    FetchReport,
    create_client,
    document_ref_from_source_path,
    document_ref_xml_url,
    document_xml_output_path,
    document_xml_url,
    fetch_document_xml,
    fetch_enacted_corpus,
    fetch_point_in_time_corpus,
    fetch_year_document_refs,
    fetch_year_documents,
    fetch_year_feed,
    format_xml,
    parse_year_feed,
    probe_fetch_report_failures,
    read_fetch_report,
    write_document_xml,
    write_fetch_report,
    write_source_document_xml,
    year_feed_url,
    year_number_range_feed_url,
)


def test_supported_point_in_time_legislation_types_cover_non_draft_api_types() -> None:
    assert POINT_IN_TIME_CORPUS_START_YEARS == {
        code: legislation_type.start_year
        for code, legislation_type in SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES.items()
    }
    assert POINT_IN_TIME_CORPUS_END_YEARS == {
        code: legislation_type.end_year
        for code, legislation_type in SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES.items()
        if legislation_type.end_year is not None
    }
    assert set(SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES) == {
        "aep",
        "aosp",
        "aip",
        "apgb",
        "gbppa",
        "gbla",
        "ukpga",
        "ukla",
        "ukppa",
        "apni",
        "ukcm",
        "nisro",
        "uksi",
        "nisi",
        "mnia",
        "nisr",
        "asp",
        "ssi",
        "wsi",
        "nia",
        "mwa",
        "anaw",
        "ukci",
        "asc",
        "ukmo",
    }


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


def test_document_ref_from_source_path_reads_calendar_path() -> None:
    document = document_ref_from_source_path("ukpga/2026/14")

    assert document == DocumentRef(
        legislation_type="ukpga",
        year=2026,
        number=14,
        title="",
        source_path=("ukpga", "2026", "14"),
    )


def test_document_ref_from_source_path_reads_regnal_path() -> None:
    document = document_ref_from_source_path("ukpga/Geo3/44/42")

    assert document.legislation_type == "ukpga"
    assert document.year == 0
    assert document.number == 0
    assert document.path == ("ukpga", "Geo3", "44", "42")


def test_document_ref_xml_url_for_source_path_latest_xml() -> None:
    document = document_ref_from_source_path("ukpga/Geo3/44/42")

    assert document_ref_xml_url(document) == "https://www.legislation.gov.uk/ukpga/Geo3/44/42/data.xml"


def test_document_ref_xml_url_for_source_path_enacted_xml() -> None:
    document = document_ref_from_source_path("ukpga/Geo3/44/42")

    assert (
        document_ref_xml_url(document, as_enacted=True)
        == "https://www.legislation.gov.uk/ukpga/Geo3/44/42/enacted/data.xml"
    )


def test_document_ref_xml_url_for_source_path_point_in_time_xml() -> None:
    document = document_ref_from_source_path("ukpga/Geo3/44/42")

    assert (
        document_ref_xml_url(document, at="2026-05-03")
        == "https://www.legislation.gov.uk/ukpga/Geo3/44/42/2026-05-03/data.xml"
    )


def test_fetch_document_xml_rejects_html_choice_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html><head><title>Multiple Choices</title></head></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    try:
        fetch_document_xml(client, legislation_type="ukpga", year=1922, number=3)
    except ValueError as error:
        assert "not legislation XML" in str(error)
    else:
        raise AssertionError("Expected HTML response to be rejected")


def test_year_feed_url_for_legislation_type_and_year() -> None:
    assert year_feed_url(legislation_type="ukpga", year=2026) == "https://www.legislation.gov.uk/ukpga/2026/data.feed"


def test_year_number_range_feed_url_for_legislation_type_year_and_number_range() -> None:
    assert (
        year_number_range_feed_url(legislation_type="ukla", year=1803, start_number=101, end_number=200)
        == "https://www.legislation.gov.uk/ukla/1803/101-200/data.feed"
    )


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
    assert documents[0].source_path == ("ukpga", "2026", "14")


def test_parse_year_feed_reads_regnal_year_document_entries() -> None:
    feed = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Example regnal Act</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukpga/Vict/1-2/42"/>
      </entry>
    </feed>
    """

    documents = parse_year_feed(feed)

    assert documents == [
        DocumentRef(
            legislation_type="ukpga",
            year=0,
            number=0,
            title="Example regnal Act",
            source_path=("ukpga", "Vict", "1-2", "42"),
        )
    ]


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


def test_fetch_year_documents_fetches_regnal_document_source_path(monkeypatch, tmp_path: Path) -> None:
    write_calls: list[tuple[bytes, str, int, int, bool, str | None, Path, tuple[str, ...] | None]] = []

    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        return [
            DocumentRef(
                legislation_type="ukpga",
                year=0,
                number=0,
                title="Regnal Act",
                source_path=("ukpga", "Vict", "1-2", "42"),
            )
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www.legislation.gov.uk/ukpga/Vict/1-2/42/2026-05-03/data.xml"
        return httpx.Response(200, content=b"<Legislation>regnal</Legislation>")

    def fake_write_document_xml(
        content: bytes,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        source_path: tuple[str, ...] | None = None,
    ) -> Path:
        assert at is not None
        write_calls.append((content, legislation_type, year, number, as_enacted, at, output_root, source_path))
        return output_root / "xml" / "point-in-time" / at / "ukpga" / "Vict" / "1-2" / "42" / "data.xml"

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.write_document_xml", fake_write_document_xml)

    paths = fetch_year_documents(
        httpx.Client(transport=httpx.MockTransport(handler)),
        legislation_type="ukpga",
        year=1838,
        at="2026-05-03",
        output_root=tmp_path,
    )

    assert write_calls == [
        (
            b"<Legislation>regnal</Legislation>",
            "ukpga",
            0,
            0,
            False,
            "2026-05-03",
            tmp_path,
            ("ukpga", "Vict", "1-2", "42"),
        )
    ]
    assert paths == [tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "Vict" / "1-2" / "42" / "data.xml"]


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
        DocumentRef(legislation_type="ukpga", year=2020, number=2, title="Act 2", source_path=("ukpga", "2020", "2")),
        DocumentRef(legislation_type="ukpga", year=2020, number=1, title="Act 1", source_path=("ukpga", "2020", "1")),
    ]


def test_fetch_year_document_refs_splits_number_ranges_when_year_feed_is_too_broad() -> None:
    requested_urls: list[str] = []
    messages: list[str] = []

    range_1 = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Local Act 100</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukla/1803/100"/>
      </entry>
      <entry>
        <title>Local Act 1</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukla/1803/1"/>
      </entry>
    </feed>
    """
    range_2_page_1 = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <link rel="next" href="https://www.legislation.gov.uk/ukla/1803/101-200/data.feed?page=2"/>
      <entry>
        <title>Local Act 200</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukla/1803/200"/>
      </entry>
    </feed>
    """
    range_2_page_2 = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Local Act 101</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/ukla/1803/101"/>
      </entry>
    </feed>
    """
    empty_range = b"""<feed xmlns="http://www.w3.org/2005/Atom"/>"""

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == "https://www.legislation.gov.uk/ukla/1803/data.feed":
            return httpx.Response(436, content=b"too broad", request=request)
        if str(request.url) == "https://www.legislation.gov.uk/ukla/1803/1-100/data.feed":
            return httpx.Response(200, content=range_1)
        if str(request.url) == "https://www.legislation.gov.uk/ukla/1803/101-200/data.feed":
            return httpx.Response(200, content=range_2_page_1)
        if str(request.url) == "https://www.legislation.gov.uk/ukla/1803/101-200/data.feed?page=2":
            return httpx.Response(200, content=range_2_page_2)
        if str(request.url) == "https://www.legislation.gov.uk/ukla/1803/201-300/data.feed":
            return httpx.Response(200, content=empty_range)
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    documents = fetch_year_document_refs(client, legislation_type="ukla", year=1803, log=messages.append)

    assert requested_urls == [
        "https://www.legislation.gov.uk/ukla/1803/data.feed",
        "https://www.legislation.gov.uk/ukla/1803/1-100/data.feed",
        "https://www.legislation.gov.uk/ukla/1803/101-200/data.feed",
        "https://www.legislation.gov.uk/ukla/1803/101-200/data.feed?page=2",
        "https://www.legislation.gov.uk/ukla/1803/201-300/data.feed",
    ]
    assert documents == [
        DocumentRef(
            legislation_type="ukla",
            year=1803,
            number=100,
            title="Local Act 100",
            source_path=("ukla", "1803", "100"),
        ),
        DocumentRef(
            legislation_type="ukla",
            year=1803,
            number=1,
            title="Local Act 1",
            source_path=("ukla", "1803", "1"),
        ),
        DocumentRef(
            legislation_type="ukla",
            year=1803,
            number=200,
            title="Local Act 200",
            source_path=("ukla", "1803", "200"),
        ),
        DocumentRef(
            legislation_type="ukla",
            year=1803,
            number=101,
            title="Local Act 101",
            source_path=("ukla", "1803", "101"),
        ),
    ]
    assert messages == [
        "Splitting ukla 1803 feed into 100-number ranges",
        "Discovered 2 documents in ukla 1803 1-100: 2 year total",
        "Read feed page 2: 2 documents discovered so far from "
        "https://www.legislation.gov.uk/ukla/1803/101-200/data.feed?page=2",
        "Discovered 2 documents in ukla 1803 101-200: 4 year total",
    ]


def test_fetch_year_document_refs_retries_transient_436_on_number_range_feeds(monkeypatch) -> None:
    requested_urls: list[str] = []
    messages: list[str] = []
    sleep_calls: list[float] = []
    range_1_attempts = 0

    range_1 = b"""
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Instrument 1</title>
        <link rel="alternate" href="http://www.legislation.gov.uk/wsi/2005/1"/>
      </entry>
    </feed>
    """
    empty_range = b"""<feed xmlns="http://www.w3.org/2005/Atom"/>"""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal range_1_attempts
        requested_urls.append(str(request.url))
        if str(request.url) == "https://www.legislation.gov.uk/wsi/2005/data.feed":
            return httpx.Response(436, content=b"too broad", request=request)
        if str(request.url) == "https://www.legislation.gov.uk/wsi/2005/1-100/data.feed":
            range_1_attempts += 1
            if range_1_attempts <= 2:
                return httpx.Response(436, content=b"unavailable", request=request)
            return httpx.Response(200, content=range_1)
        if str(request.url) == "https://www.legislation.gov.uk/wsi/2005/101-200/data.feed":
            return httpx.Response(200, content=empty_range)
        return httpx.Response(404, request=request)

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", sleep_calls.append)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    documents = fetch_year_document_refs(client, legislation_type="wsi", year=2005, log=messages.append)

    assert range_1_attempts == 3
    assert sleep_calls == [30.0, 60.0]
    assert documents == [
        DocumentRef(
            legislation_type="wsi",
            year=2005,
            number=1,
            title="Instrument 1",
            source_path=("wsi", "2005", "1"),
        ),
    ]
    assert messages == [
        "Splitting wsi 2005 feed into 100-number ranges",
        "Feed unavailable (436) for https://www.legislation.gov.uk/wsi/2005/1-100/data.feed; "
        "waiting 30s before retry 1/5",
        "Feed unavailable (436) for https://www.legislation.gov.uk/wsi/2005/1-100/data.feed; "
        "waiting 60s before retry 2/5",
        "Discovered 1 documents in wsi 2005 1-100: 1 year total",
    ]


def test_fetch_year_document_refs_raises_when_number_range_436_persists(monkeypatch) -> None:
    sleep_calls: list[float] = []
    range_1_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal range_1_attempts
        if str(request.url) == "https://www.legislation.gov.uk/wsi/2005/1-100/data.feed":
            range_1_attempts += 1
        return httpx.Response(436, content=b"unavailable", request=request)

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", sleep_calls.append)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        fetch_year_document_refs(client, legislation_type="wsi", year=2005)

    assert range_1_attempts == 6
    assert sleep_calls == [30.0, 60.0, 120.0, 240.0, 300.0]


def test_create_client_sets_legislation_api_headers() -> None:
    with create_client() as client:
        assert "git-legislation" in client.headers["User-Agent"]
        assert client.headers["Accept"] == "application/xml"
        assert client.timeout == 30.0
        assert client.retries == 2


def test_legislation_client_uses_timeout_for_requests(monkeypatch) -> None:
    calls: list[float | object] = []

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"<Legislation>example</Legislation>"

    def fake_urlopen(request: object, timeout: float) -> Response:
        calls.append(timeout)
        return Response()

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    response = create_client().get("https://www.legislation.gov.uk/ukpga/2026/14/data.xml")

    assert response.status_code == 200
    assert response.content == b"<Legislation>example</Legislation>"
    assert calls == [30.0]


def test_legislation_client_retries_transient_url_errors(monkeypatch) -> None:
    calls = 0

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"<Legislation>example</Legislation>"

    def fake_urlopen(request: object, timeout: float) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise URLError("timed out")
        return Response()

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", lambda seconds: None)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    response = create_client().get("https://www.legislation.gov.uk/ukpga/2026/14/data.xml")

    assert response.status_code == 200
    assert calls == 2


def test_legislation_client_retries_connection_resets(monkeypatch) -> None:
    calls = 0

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"<Legislation>example</Legislation>"

    def fake_urlopen(request: object, timeout: float) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionResetError(54, "Connection reset by peer")
        return Response()

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", lambda seconds: None)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    response = create_client().get("https://www.legislation.gov.uk/ukpga/2026/14/data.xml")

    assert response.status_code == 200
    assert calls == 2


def test_legislation_client_does_not_retry_client_http_status_errors(monkeypatch) -> None:
    calls = 0

    def fake_urlopen(request: object, timeout: float) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            url="https://www.legislation.gov.uk/ukpga/2026/14/data.xml",
            code=404,
            msg="Not Found",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    response = create_client().get("https://www.legislation.gov.uk/ukpga/2026/14/data.xml")

    assert response.status_code == 404
    assert calls == 1


def test_legislation_client_retries_server_http_status_errors(monkeypatch) -> None:
    calls = 0
    sleep_calls: list[float] = []
    messages: list[str] = []

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"<feed />"

    def fake_urlopen(request: object, timeout: float) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(
                url="https://www.legislation.gov.uk/uksi/2004/data.feed?page=69",
                code=504,
                msg="Gateway Timeout",
                hdrs=Message(),
                fp=None,
            )
        return Response()

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", sleep_calls.append)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    response = create_client(log=messages.append).get("https://www.legislation.gov.uk/uksi/2004/data.feed?page=69")

    assert response.status_code == 200
    assert calls == 2
    assert sleep_calls == [5.0]
    assert messages == [
        "Server error 504 fetching https://www.legislation.gov.uk/uksi/2004/data.feed?page=69; "
        "waiting 5s before retry 1/5"
    ]


def test_legislation_client_returns_server_error_after_retries_are_exhausted(monkeypatch) -> None:
    calls = 0
    sleep_calls: list[float] = []

    def fake_urlopen(request: object, timeout: float) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            url="https://www.legislation.gov.uk/uksi/2004/data.feed?page=69",
            code=504,
            msg="Gateway Timeout",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", sleep_calls.append)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    client = create_client()
    client.server_error_retries = 2
    client.server_error_backoff_seconds = 3.0

    response = client.get("https://www.legislation.gov.uk/uksi/2004/data.feed?page=69")

    assert response.status_code == 504
    assert calls == 3
    assert sleep_calls == [3.0, 6.0]


def test_legislation_client_retries_rate_limits_with_retry_after(monkeypatch) -> None:
    calls = 0
    sleep_calls: list[float] = []
    messages: list[str] = []

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"<Legislation>example</Legislation>"

    def fake_urlopen(request: object, timeout: float) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            headers = Message()
            headers["Retry-After"] = "7"
            raise HTTPError(
                url="https://www.legislation.gov.uk/ukppa/1985/data.feed",
                code=429,
                msg="Too Many Requests",
                hdrs=headers,
                fp=None,
            )
        return Response()

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", sleep_calls.append)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    response = create_client(log=messages.append).get("https://www.legislation.gov.uk/ukppa/1985/data.feed")

    assert response.status_code == 200
    assert calls == 2
    assert sleep_calls == [7.0]
    assert messages == [
        "Rate limited fetching https://www.legislation.gov.uk/ukppa/1985/data.feed; waiting 7s before retry 1/5"
    ]


def test_legislation_client_returns_rate_limit_after_retries_are_exhausted(monkeypatch) -> None:
    calls = 0
    sleep_calls: list[float] = []

    def fake_urlopen(request: object, timeout: float) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            url="https://www.legislation.gov.uk/ukppa/1985/data.feed",
            code=429,
            msg="Too Many Requests",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.time.sleep", sleep_calls.append)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.urlopen", fake_urlopen)

    client = create_client()
    client.rate_limit_retries = 2
    client.rate_limit_backoff_seconds = 3.0

    response = client.get("https://www.legislation.gov.uk/ukppa/1985/data.feed")

    assert response.status_code == 429
    assert calls == 3
    assert sleep_calls == [3.0, 6.0]


class FixedDate(date):
    @classmethod
    def today(cls) -> "FixedDate":
        return cls(2026, 5, 3)


def test_write_document_xml_writes_current_xml_to_todays_point_in_time_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.date", FixedDate)

    path = write_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_document_xml_output_path_matches_current_xml_output_folder(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.date", FixedDate)

    path = document_xml_output_path(legislation_type="ukpga", year=2026, number=14, output_root=tmp_path)

    assert path == tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"


def test_write_document_xml_writes_enacted_xml(tmp_path: Path) -> None:
    path = write_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        as_enacted=True,
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_write_document_xml_writes_point_in_time_xml(tmp_path: Path) -> None:
    path = write_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        at="2026-03-18",
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "point-in-time" / "2026-03-18" / "ukpga" / "2026" / "14" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_write_document_xml_writes_source_shaped_point_in_time_xml(tmp_path: Path) -> None:
    path = write_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        legislation_type="ukpga",
        year=0,
        number=0,
        at="2026-03-18",
        output_root=tmp_path,
        source_path=("ukpga", "Vict", "1-2", "42"),
    )

    assert path == tmp_path / "xml" / "point-in-time" / "2026-03-18" / "ukpga" / "Vict" / "1-2" / "42" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_write_source_document_xml_writes_latest_xml(tmp_path: Path) -> None:
    path = write_source_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        source_path=("ukpga", "Geo3", "44", "42"),
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "latest" / "ukpga" / "Geo3" / "44" / "42" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_write_source_document_xml_writes_enacted_xml(tmp_path: Path) -> None:
    path = write_source_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        source_path=("ukpga", "Geo3", "44", "42"),
        as_enacted=True,
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "enacted" / "ukpga" / "Geo3" / "44" / "42" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_write_source_document_xml_writes_point_in_time_xml(tmp_path: Path) -> None:
    path = write_source_document_xml(
        b"<Legislation><Body>example</Body></Legislation>",
        source_path=("ukpga", "Geo3", "44", "42"),
        at="2026-05-03",
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "Geo3" / "44" / "42" / "data.xml"
    assert path.read_bytes() == b"<Legislation>\n\t<Body>example</Body>\n</Legislation>\n"


def test_format_xml_preserves_xml_declaration() -> None:
    assert (
        format_xml(b'<?xml version="1.0" encoding="utf-8"?><Legislation><Body>example</Body></Legislation>')
        == b'<?xml version="1.0" encoding="utf-8"?>\n<Legislation>\n\t<Body>example</Body>\n</Legislation>\n'
    )


def test_fetch_year_documents_fetches_and_writes_each_document(monkeypatch, tmp_path: Path) -> None:
    fetch_year_document_refs_args: tuple[str, int] | None = None
    fetch_document_calls: list[tuple[DocumentRef, bool, str | None]] = []
    write_calls: list[tuple[bytes, str, int, int, bool, str | None, Path, tuple[str, ...] | None]] = []

    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        nonlocal fetch_year_document_refs_args
        fetch_year_document_refs_args = (legislation_type, year)
        return [
            DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14"),
            DocumentRef(legislation_type="ukpga", year=2026, number=13, title="Act 13"),
        ]

    def fake_fetch_document_ref_xml(
        client: httpx.Client, document: DocumentRef, as_enacted: bool = False, at: str | None = None
    ) -> bytes:
        fetch_document_calls.append((document, as_enacted, at))
        return f"<Legislation>{document.number}</Legislation>".encode()

    def fake_write_document_xml(
        content: bytes,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        source_path: tuple[str, ...] | None = None,
    ) -> Path:
        write_calls.append((content, legislation_type, year, number, as_enacted, at, output_root, source_path))
        return output_root / "xml" / "enacted" / legislation_type / str(year) / str(number) / "data.xml"

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.write_document_xml", fake_write_document_xml)

    paths = fetch_year_documents(
        httpx.Client(), legislation_type="ukpga", year=2026, as_enacted=True, output_root=tmp_path
    )

    assert fetch_year_document_refs_args == ("ukpga", 2026)
    assert fetch_document_calls == [
        (DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14"), True, None),
        (DocumentRef(legislation_type="ukpga", year=2026, number=13, title="Act 13"), True, None),
    ]
    assert write_calls == [
        (b"<Legislation>14</Legislation>", "ukpga", 2026, 14, True, None, tmp_path, ("ukpga", "2026", "14")),
        (b"<Legislation>13</Legislation>", "ukpga", 2026, 13, True, None, tmp_path, ("ukpga", "2026", "13")),
    ]
    assert paths == [
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml",
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "13" / "data.xml",
    ]


def test_fetch_year_documents_skips_existing_xml(monkeypatch, tmp_path: Path) -> None:
    existing_path = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(b"<Legislation>already here</Legislation>")

    fetch_document_calls: list[DocumentRef] = []
    write_calls: list[bytes] = []

    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        return [DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14")]

    def fake_fetch_document_ref_xml(
        client: httpx.Client, document: DocumentRef, as_enacted: bool = False, at: str | None = None
    ) -> bytes:
        fetch_document_calls.append(document)
        return b"<Legislation>refetched</Legislation>"

    def fake_write_document_xml(
        content: bytes,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        source_path: tuple[str, ...] | None = None,
    ) -> Path:
        write_calls.append(content)
        return existing_path

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.write_document_xml", fake_write_document_xml)

    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        at="2026-05-03",
        output_root=tmp_path,
    )

    assert paths == [existing_path]
    assert fetch_document_calls == []
    assert write_calls == []
    assert existing_path.read_bytes() == b"<Legislation>already here</Legislation>"


def test_fetch_year_documents_refetches_invalid_existing_xml(monkeypatch, tmp_path: Path) -> None:
    existing_path = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(b"")

    fetch_document_calls: list[DocumentRef] = []

    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        return [DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14")]

    def fake_fetch_document_ref_xml(
        client: httpx.Client, document: DocumentRef, as_enacted: bool = False, at: str | None = None
    ) -> bytes:
        fetch_document_calls.append(document)
        return b"<Legislation>refetched</Legislation>"

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_ref_xml", fake_fetch_document_ref_xml)

    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        at="2026-05-03",
        output_root=tmp_path,
    )

    assert paths == [existing_path]
    assert fetch_document_calls == [DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14")]
    assert existing_path.read_bytes() == b"<Legislation>refetched</Legislation>\n"


def test_fetch_year_documents_removes_invalid_existing_xml_when_refetch_fails(monkeypatch, tmp_path: Path) -> None:
    existing_path = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "14" / "data.xml"
    existing_path.parent.mkdir(parents=True)
    existing_path.write_bytes(b"")

    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        return [DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14")]

    def fake_fetch_document_ref_xml(
        client: httpx.Client, document: DocumentRef, as_enacted: bool = False, at: str | None = None
    ) -> bytes:
        raise ValueError("empty response")

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_ref_xml", fake_fetch_document_ref_xml)

    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        at="2026-05-03",
        output_root=tmp_path,
        report=report,
    )

    assert paths == []
    assert not existing_path.exists()
    assert len(report.failures) == 1


def test_fetch_year_documents_records_document_failures_and_continues(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        return [
            DocumentRef(legislation_type="ukpga", year=2026, number=14, title="Act 14"),
            DocumentRef(legislation_type="ukpga", year=2026, number=13, title="Act 13"),
        ]

    def fake_fetch_document_ref_xml(
        client: httpx.Client, document: DocumentRef, as_enacted: bool = False, at: str | None = None
    ) -> bytes:
        if document.number == 14:
            raise httpx.HTTPStatusError(
                "HTTP status 404",
                request=httpx.Request("GET", "https://www.legislation.gov.uk/ukpga/2026/14/2026-05-03/data.xml"),
                response=httpx.Response(404),
            )
        return b"<Legislation>13</Legislation>"

    def fake_write_document_xml(
        content: bytes,
        legislation_type: str,
        year: int,
        number: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        source_path: tuple[str, ...] | None = None,
    ) -> Path:
        assert at is not None
        return output_root / "xml" / "point-in-time" / at / legislation_type / str(year) / str(number) / "data.xml"

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_ref_xml", fake_fetch_document_ref_xml)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.write_document_xml", fake_write_document_xml)

    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=2026,
        at="2026-05-03",
        output_root=tmp_path,
        report=report,
    )

    assert paths == [tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "13" / "data.xml"]
    assert report.failures == [
        FetchFailure(
            stage="document",
            legislation_type="ukpga",
            year=2026,
            number=14,
            url="https://www.legislation.gov.uk/ukpga/2026/14/2026-05-03/data.xml",
            status_code=404,
            error="HTTP status 404",
        )
    ]


def test_fetch_year_documents_records_transient_failure_url(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch_year_document_refs(client: httpx.Client, legislation_type: str, year: int) -> list[DocumentRef]:
        return [DocumentRef(legislation_type="ukpga", year=1997, number=23, title="Act 23")]

    def fake_fetch_document_ref_xml(
        client: httpx.Client, document: DocumentRef, as_enacted: bool = False, at: str | None = None
    ) -> bytes:
        raise ConnectionResetError(54, "Connection reset by peer")

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_document_refs", fake_fetch_year_document_refs)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_document_ref_xml", fake_fetch_document_ref_xml)

    report = FetchReport.point_in_time_corpus(at="2026-05-04")
    paths = fetch_year_documents(
        httpx.Client(),
        legislation_type="ukpga",
        year=1997,
        output_root=tmp_path,
        report=report,
    )

    assert paths == []
    assert report.failures == [
        FetchFailure(
            stage="document",
            legislation_type="ukpga",
            year=1997,
            number=23,
            url="https://www.legislation.gov.uk/ukpga/1997/23/data.xml",
            status_code=None,
            error="[Errno 54] Connection reset by peer",
        )
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
        log: object = None,
    ) -> list[Path]:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return [output_root / "xml" / "enacted" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    paths = fetch_enacted_corpus(
        httpx.Client(), legislation_type="ukpga", start_year=2025, end_year=2026, output_root=tmp_path
    )

    assert calls == [("ukpga", 2025, True, None, tmp_path), ("ukpga", 2026, True, None, tmp_path)]
    assert paths == [
        tmp_path / "xml" / "enacted" / "ukpga" / "2025" / "1" / "data.xml",
        tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "1" / "data.xml",
    ]


def test_fetch_enacted_corpus_logs_year_progress(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        return [output_root / "xml" / "enacted" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_enacted_corpus(
        httpx.Client(),
        legislation_type="ukpga",
        start_year=2025,
        end_year=2025,
        output_root=tmp_path,
        log=messages.append,
    )

    assert messages == ["Fetched enacted ukpga 2025: 1 documents"]


def test_fetch_enacted_corpus_does_not_log_empty_years(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        return []

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_enacted_corpus(
        httpx.Client(),
        legislation_type="ukpga",
        start_year=2025,
        end_year=2025,
        output_root=tmp_path,
        log=messages.append,
    )

    assert messages == []


def test_fetch_enacted_corpus_logs_empty_year_checkpoints(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        return []

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_enacted_corpus(
        httpx.Client(),
        legislation_type="ukpga",
        start_year=1900,
        end_year=1999,
        output_root=tmp_path,
        log=messages.append,
    )

    assert messages == ["Checked enacted ukpga 1900-1999: no documents"]


def test_fetch_enacted_corpus_resets_empty_year_checkpoints(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        return []

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_enacted_corpus(
        httpx.Client(),
        legislation_type="ukpga",
        start_year=1900,
        end_year=2099,
        output_root=tmp_path,
        log=messages.append,
    )

    assert messages == [
        "Checked enacted ukpga 1900-1999: no documents",
        "Checked enacted ukpga 2000-2099: no documents",
    ]


def test_fetch_enacted_corpus_report_records_year_failures(monkeypatch, tmp_path: Path) -> None:
    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        report: FetchReport | None = None,
        log: object = None,
    ) -> list[Path]:
        if year == 2025:
            raise httpx.HTTPStatusError(
                "HTTP status 404",
                request=httpx.Request("GET", "https://www.legislation.gov.uk/ukpga/2025/data.feed"),
                response=httpx.Response(404),
            )
        return [output_root / "xml" / "enacted" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    report = FetchReport.enacted_corpus(legislation_type="ukpga", start_year=2025, end_year=2026)
    paths = fetch_enacted_corpus(
        httpx.Client(), legislation_type="ukpga", start_year=2025, end_year=2026, output_root=tmp_path, report=report
    )

    assert paths == [tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "1" / "data.xml"]
    assert report.fetched_paths == [tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "1" / "data.xml"]
    assert report.failures == [
        FetchFailure(
            stage="year",
            legislation_type="ukpga",
            year=2025,
            number=None,
            url="https://www.legislation.gov.uk/ukpga/2025/data.feed",
            status_code=404,
            error="HTTP status 404",
        )
    ]


def test_fetch_point_in_time_corpus_fetches_configured_corpus_to_snapshot_year(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int, bool, str | None, Path]] = []
    monkeypatch.setattr(
        "fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS",
        {"ukpga": 2026, "uksi": 2025},
    )

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return [output_root / "xml" / "point-in-time" / "2026-05-03" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    paths = fetch_point_in_time_corpus(httpx.Client(), at="2026-05-03", output_root=tmp_path)

    assert calls == [
        ("ukpga", 2026, False, "2026-05-03", tmp_path),
        ("uksi", 2025, False, "2026-05-03", tmp_path),
        ("uksi", 2026, False, "2026-05-03", tmp_path),
    ]
    assert paths == [
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "1" / "data.xml",
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "uksi" / "2025" / "1" / "data.xml",
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "uksi" / "2026" / "1" / "data.xml",
    ]


def test_fetch_point_in_time_corpus_fetches_requested_legislation_types(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int, bool, str | None, Path]] = []
    monkeypatch.setattr(
        "fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS",
        {"ukpga": 2026, "uksi": 2025},
    )

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return [output_root / "xml" / "point-in-time" / "2026-05-03" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    paths = fetch_point_in_time_corpus(
        httpx.Client(),
        at="2026-05-03",
        legislation_types=("uksi",),
        output_root=tmp_path,
    )

    assert calls == [
        ("uksi", 2025, False, "2026-05-03", tmp_path),
        ("uksi", 2026, False, "2026-05-03", tmp_path),
    ]
    assert paths == [
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "uksi" / "2025" / "1" / "data.xml",
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "uksi" / "2026" / "1" / "data.xml",
    ]


def test_fetch_point_in_time_corpus_respects_closed_series_end_years(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, int, bool, str | None, Path]] = []
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS", {"aip": 1799})
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_END_YEARS", {"aip": 1800})

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return [output_root / "xml" / "point-in-time" / "2026-05-03" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    paths = fetch_point_in_time_corpus(
        httpx.Client(),
        at="2026-05-03",
        legislation_types=("aip",),
        output_root=tmp_path,
    )

    assert calls == [
        ("aip", 1799, False, "2026-05-03", tmp_path),
        ("aip", 1800, False, "2026-05-03", tmp_path),
    ]
    assert paths == [
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "aip" / "1799" / "1" / "data.xml",
        tmp_path / "xml" / "point-in-time" / "2026-05-03" / "aip" / "1800" / "1" / "data.xml",
    ]


def test_fetch_point_in_time_corpus_rejects_unknown_legislation_type() -> None:
    try:
        fetch_point_in_time_corpus(httpx.Client(), at="2026-05-03", legislation_types=("unknown",))
    except ValueError as error:
        assert "Unsupported point-in-time corpus legislation type(s): unknown" in str(error)
    else:
        raise AssertionError("Expected unsupported legislation type to be rejected")


def test_fetch_point_in_time_corpus_without_date_fetches_latest_xml_to_todays_snapshot(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, int, bool, str | None, Path]] = []
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.date", FixedDate)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS", {"ukpga": 2026})

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        calls.append((legislation_type, year, as_enacted, at, output_root))
        return [output_root / "xml" / "point-in-time" / "2026-05-03" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    paths = fetch_point_in_time_corpus(httpx.Client(), output_root=tmp_path)

    assert calls == [("ukpga", 2026, False, None, tmp_path)]
    assert paths == [tmp_path / "xml" / "point-in-time" / "2026-05-03" / "ukpga" / "2026" / "1" / "data.xml"]


def test_fetch_point_in_time_corpus_logs_year_progress(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS", {"ukpga": 2026})

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        return [output_root / "xml" / "point-in-time" / "2026-05-03" / legislation_type / str(year) / "1" / "data.xml"]

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_point_in_time_corpus(httpx.Client(), at="2026-05-03", output_root=tmp_path, log=messages.append)

    assert messages == ["Fetched point-in-time ukpga 2026 at 2026-05-03: 1 documents"]


def test_fetch_point_in_time_corpus_logs_year_document_failures(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS", {"ukpga": 2026})

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        report: FetchReport | None = None,
        log: object = None,
    ) -> list[Path]:
        assert report is not None
        report.record_failure(
            FetchFailure(
                stage="document",
                legislation_type=legislation_type,
                year=year,
                number=14,
                url="https://www.legislation.gov.uk/ukpga/2026/14/2026-05-03/data.xml",
                status_code=404,
                error="HTTP status 404",
            )
        )
        return []

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_point_in_time_corpus(
        httpx.Client(),
        at="2026-05-03",
        output_root=tmp_path,
        report=FetchReport.point_in_time_corpus(at="2026-05-03"),
        log=messages.append,
    )

    assert messages == ["Fetched point-in-time ukpga 2026 at 2026-05-03: 0 documents, 1 failures"]


def test_fetch_point_in_time_corpus_logs_empty_year_checkpoints(monkeypatch, tmp_path: Path) -> None:
    messages: list[str] = []
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.POINT_IN_TIME_CORPUS_START_YEARS", {"ukpga": 1900})

    def fake_fetch_year_documents(
        client: httpx.Client,
        legislation_type: str,
        year: int,
        as_enacted: bool = False,
        at: str | None = None,
        output_root: Path = tmp_path,
        log: object = None,
    ) -> list[Path]:
        return []

    monkeypatch.setattr("fetchers.legislationdotgovdotuk.date", FixedDate)
    monkeypatch.setattr("fetchers.legislationdotgovdotuk.fetch_year_documents", fake_fetch_year_documents)

    fetch_point_in_time_corpus(httpx.Client(), at="1999-05-03", output_root=tmp_path, log=messages.append)

    assert messages == ["Checked point-in-time ukpga 1900-1999 at 1999-05-03: no documents"]


def test_write_fetch_report_writes_json_report(tmp_path: Path) -> None:
    report = FetchReport.enacted_corpus(legislation_type="ukpga", start_year=2025, end_year=2026)
    report.record_fetched(tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "1" / "data.xml")
    report.record_failure(
        FetchFailure(
            stage="year",
            legislation_type="ukpga",
            year=2025,
            number=None,
            url="https://www.legislation.gov.uk/ukpga/2025/data.feed",
            status_code=404,
            error="HTTP status 404",
        )
    )

    path = write_fetch_report(report, output_root=tmp_path)

    assert path == tmp_path / "reports" / "fetch" / "enacted" / "ukpga" / "2025-2026.json"
    assert '"mode": "enacted"' in path.read_text()
    assert '"status_code": 404' in path.read_text()


def test_fetch_report_deduplicates_fetched_paths(tmp_path: Path) -> None:
    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    path = tmp_path / "xml" / "point-in-time" / "2026-05-03" / "wsi" / "2026" / "1" / "data.xml"

    report.record_fetched(path)
    report.record_fetched(path)

    assert report.fetched_paths == [path]


def test_write_fetch_report_includes_failure_probes(tmp_path: Path) -> None:
    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    report.record_failure(
        FetchFailure(
            stage="document",
            legislation_type="ukpga",
            year=2025,
            number=27,
            url="https://www.legislation.gov.uk/ukpga/2025/27/2026-05-03/data.xml",
            status_code=404,
            error="HTTP status 404",
            probes=[
                FetchProbe(
                    label="latest_xml",
                    url="https://www.legislation.gov.uk/ukpga/2025/27/data.xml",
                    status_code=200,
                    error=None,
                    pdf_alternatives=(),
                )
            ],
        )
    )

    path = write_fetch_report(report, output_root=tmp_path)

    assert '"probes"' in path.read_text()
    assert '"label": "latest_xml"' in path.read_text()
    assert '"classification": "dated_xml_unavailable_latest_xml_available"' in path.read_text()


def test_read_fetch_report_reads_probe_results(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(
        """
        {
          "mode": "point-in-time",
          "legislation_type": null,
          "start_year": null,
          "end_year": 2026,
          "at": "2026-05-03",
          "fetched": [],
          "failures": [
            {
              "stage": "document",
              "legislation_type": "ukpga",
              "year": 2025,
              "number": 27,
              "url": "https://www.legislation.gov.uk/ukpga/2025/27/2026-05-03/data.xml",
              "status_code": 404,
              "error": "HTTP status 404",
              "classification": "dated_xml_unavailable_latest_xml_available",
              "probes": [
                {
                  "label": "latest_xml",
                  "url": "https://www.legislation.gov.uk/ukpga/2025/27/data.xml",
                  "status_code": 200,
                  "error": null,
                  "pdf_alternatives": []
                }
              ]
            }
          ]
        }
        """
    )

    report = read_fetch_report(path)

    assert report.failures[0].probes == [
        FetchProbe(
            label="latest_xml",
            url="https://www.legislation.gov.uk/ukpga/2025/27/data.xml",
            status_code=200,
            error=None,
            pdf_alternatives=(),
        )
    ]
    assert report.failures[0].classification == "dated_xml_unavailable_latest_xml_available"


def test_probe_fetch_report_failures_adds_fallback_probe_results() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == "https://www.legislation.gov.uk/ukpga/2025/27/resources/data.xml":
            return httpx.Response(
                200,
                content=b"""
                <Legislation xmlns:ukm="http://www.legislation.gov.uk/namespaces/metadata">
                  <ukm:Metadata>
                    <ukm:Alternatives>
                      <ukm:Alternative URI="https://www.legislation.gov.uk/ukpga/2025/27/pdfs/ukpga_20250027_en.pdf"/>
                    </ukm:Alternatives>
                  </ukm:Metadata>
                </Legislation>
                """,
            )
        if str(request.url) == "https://www.legislation.gov.uk/ukpga/2025/27/data.xml":
            return httpx.Response(404)
        if str(request.url) == "https://www.legislation.gov.uk/ukpga/2025/27/enacted/data.xml":
            return httpx.Response(200, content=b"<Legislation />")
        return httpx.Response(500)

    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    report.record_failure(
        FetchFailure(
            stage="document",
            legislation_type="ukpga",
            year=2025,
            number=27,
            url="https://www.legislation.gov.uk/ukpga/2025/27/2026-05-03/data.xml",
            status_code=404,
            error="HTTP status 404",
        )
    )

    probed = probe_fetch_report_failures(httpx.Client(transport=httpx.MockTransport(handler)), report)

    assert probed == 1
    assert requested_urls == [
        "https://www.legislation.gov.uk/ukpga/2025/27/data.xml",
        "https://www.legislation.gov.uk/ukpga/2025/27/enacted/data.xml",
        "https://www.legislation.gov.uk/ukpga/2025/27/resources/data.xml",
    ]
    assert report.failures[0].probes == [
        FetchProbe(
            label="latest_xml",
            url="https://www.legislation.gov.uk/ukpga/2025/27/data.xml",
            status_code=404,
            error=None,
            pdf_alternatives=(),
        ),
        FetchProbe(
            label="enacted_xml",
            url="https://www.legislation.gov.uk/ukpga/2025/27/enacted/data.xml",
            status_code=200,
            error=None,
            pdf_alternatives=(),
        ),
        FetchProbe(
            label="resources_xml",
            url="https://www.legislation.gov.uk/ukpga/2025/27/resources/data.xml",
            status_code=200,
            error=None,
            pdf_alternatives=("https://www.legislation.gov.uk/ukpga/2025/27/pdfs/ukpga_20250027_en.pdf",),
        ),
    ]
    assert report.failures[0].classification == "dated_xml_unavailable_enacted_xml_available_pdf_available"


def test_probe_fetch_report_failures_respects_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    for number in [27, 28]:
        report.record_failure(
            FetchFailure(
                stage="document",
                legislation_type="ukpga",
                year=2025,
                number=number,
                url=f"https://www.legislation.gov.uk/ukpga/2025/{number}/2026-05-03/data.xml",
                status_code=404,
                error="HTTP status 404",
            )
        )

    probed = probe_fetch_report_failures(httpx.Client(transport=httpx.MockTransport(handler)), report, limit=1)

    assert probed == 1
    assert len(report.failures[0].probes) == 3
    assert report.failures[1].probes == []


def test_probe_fetch_report_failures_classifies_missing_all_fallbacks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    report = FetchReport.point_in_time_corpus(at="2026-05-03")
    report.record_failure(
        FetchFailure(
            stage="document",
            legislation_type="ukpga",
            year=2025,
            number=27,
            url="https://www.legislation.gov.uk/ukpga/2025/27/2026-05-03/data.xml",
            status_code=404,
            error="HTTP status 404",
        )
    )

    probe_fetch_report_failures(httpx.Client(transport=httpx.MockTransport(handler)), report)

    assert report.failures[0].classification == "dated_xml_unavailable_no_fallback_found"
