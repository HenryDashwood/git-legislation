from pathlib import Path

import httpx

from fetchers.legislationdotgovdotuk import (
    create_client,
    document_xml_url,
    fetch_document_xml,
    write_document_xml,
)


def test_document_xml_url_for_numbered_legislation() -> None:
    assert (
        document_xml_url(legislation_type="ukpga", year=2026, number=14)
        == "https://www.legislation.gov.uk/ukpga/2026/14/data.xml"
    )


def test_fetch_document_xml_gets_the_document_xml_url() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"<Legislation>example</Legislation>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    content = fetch_document_xml(client, legislation_type="ukpga", year=2026, number=14)

    assert content == b"<Legislation>example</Legislation>"
    assert requested_urls == ["https://www.legislation.gov.uk/ukpga/2026/14/data.xml"]


def test_create_client_sets_legislation_api_headers() -> None:
    with create_client() as client:
        assert "git-legislation" in client.headers["User-Agent"]
        assert client.headers["Accept"] == "application/xml"


def test_write_document_xml_writes_current_consolidated_xml(tmp_path: Path) -> None:
    path = write_document_xml(
        b"<Legislation>example</Legislation>",
        legislation_type="ukpga",
        year=2026,
        number=14,
        output_root=tmp_path,
    )

    assert path == tmp_path / "xml" / "consolidated" / "ukpga" / "2026" / "14" / "current.xml"
    assert path.read_bytes() == b"<Legislation>example</Legislation>"
