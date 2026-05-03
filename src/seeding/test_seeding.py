from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request
from zipfile import ZipFile

from seeding import (
    BulkArchiveDownloadError,
    bulk_archive_filename,
    bulk_archive_url,
    document_output_path_from_xml,
    download_bulk_archive,
    seed_enacted_xml_from_archive,
)


def test_bulk_archive_filename_for_enacted_clml() -> None:
    assert bulk_archive_filename(dataset="enacted-epublished", data_format="xml") == "enacted-epublished-xml.zip"


def test_bulk_archive_url_for_enacted_clml() -> None:
    assert (
        bulk_archive_url(dataset="enacted-epublished", data_format="xml")
        == "https://research.legislation.gov.uk/data/downloads/texts/enacted-epublished/xml/"
        "enacted-epublished-xml.zip"
    )


def test_download_bulk_archive_writes_archive_to_bulk_output(monkeypatch, tmp_path: Path) -> None:
    class FakeResponse:
        def __init__(self) -> None:
            self.content = b"zip bytes"

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, length: int = -1) -> bytes:
            content = self.content
            self.content = b""
            return content

    calls: dict[str, Request] = {}

    def fake_urlopen(request: Request) -> FakeResponse:
        calls["request"] = request
        return FakeResponse()

    monkeypatch.setattr("seeding.urlopen", fake_urlopen)

    path = download_bulk_archive(dataset="enacted-epublished", data_format="xml", output_root=tmp_path)

    assert path == (
        tmp_path
        / "bulk"
        / "research-legislation"
        / "texts"
        / "enacted-epublished"
        / "xml"
        / "enacted-epublished-xml.zip"
    )
    assert path.read_bytes() == b"zip bytes"
    assert calls["request"].full_url == bulk_archive_url(dataset="enacted-epublished", data_format="xml")


def test_download_bulk_archive_raises_clear_error_for_unauthorized_response(monkeypatch, tmp_path: Path) -> None:
    def fake_urlopen(request: object) -> object:
        raise HTTPError(
            url="https://research.legislation.gov.uk/data/downloads/texts/enacted-epublished/xml/archive.zip",
            code=401,
            msg="Unauthorized",
            hdrs=Message(),
            fp=None,
        )

    monkeypatch.setattr("seeding.urlopen", fake_urlopen)

    try:
        download_bulk_archive(dataset="enacted-epublished", data_format="xml", output_root=tmp_path)
    except BulkArchiveDownloadError as error:
        assert "401 Unauthorized" in str(error)
        assert "requires access credentials" in str(error)
    else:
        raise AssertionError("Expected BulkArchiveDownloadError")


def test_document_output_path_from_xml_uses_document_uri(tmp_path: Path) -> None:
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  DocumentURI="http://www.legislation.gov.uk/ukpga/2026/14">
</Legislation>
"""

    path = document_output_path_from_xml(xml, output_root=tmp_path, collection="enacted")

    assert path == tmp_path / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml"


def test_seed_enacted_xml_from_archive_writes_xml_to_converter_input_layout(tmp_path: Path) -> None:
    archive_path = tmp_path / "bulk.zip"
    first_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  DocumentURI="http://www.legislation.gov.uk/ukpga/2026/14">
</Legislation>
"""
    second_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<Legislation xmlns="http://www.legislation.gov.uk/namespaces/legislation"
  DocumentURI="http://www.legislation.gov.uk/ukpga/2026/13">
</Legislation>
"""

    with ZipFile(archive_path, "w") as archive:
        archive.writestr("ukpga/2026/14/data.xml", first_xml)
        archive.writestr("ukpga/2026/13/data.xml", second_xml)
        archive.writestr("README.txt", "not legislation xml")

    paths = seed_enacted_xml_from_archive(archive_path, output_root=tmp_path / "output")

    assert paths == [
        tmp_path / "output" / "xml" / "enacted" / "ukpga" / "2026" / "14" / "data.xml",
        tmp_path / "output" / "xml" / "enacted" / "ukpga" / "2026" / "13" / "data.xml",
    ]
    assert paths[0].read_bytes() == first_xml
    assert paths[1].read_bytes() == second_xml
