"""Bulk corpus import tools."""

from pathlib import Path
from shutil import copyfileobj
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZipFile

RESEARCH_LEGISLATION_BASE_URL = "https://research.legislation.gov.uk"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"
USER_AGENT = "git-legislation/0.1"


class BulkArchiveDownloadError(RuntimeError):
    pass


def bulk_archive_filename(dataset: str, data_format: str) -> str:
    return f"{dataset}-{data_format}.zip"


def bulk_archive_url(dataset: str, data_format: str) -> str:
    filename = bulk_archive_filename(dataset=dataset, data_format=data_format)
    return f"{RESEARCH_LEGISLATION_BASE_URL}/data/downloads/texts/{dataset}/{data_format}/{filename}"


def download_bulk_archive(
    dataset: str,
    data_format: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    url = bulk_archive_url(dataset=dataset, data_format=data_format)
    path = output_root / "bulk" / "research-legislation" / "texts" / dataset / data_format / Path(url).name
    path.parent.mkdir(parents=True, exist_ok=True)

    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request) as response, path.open("wb") as output:
            copyfileobj(response, output)
    except HTTPError as error:
        if error.code == 401:
            raise BulkArchiveDownloadError(
                f"Research Legislation returned 401 Unauthorized for {url}. "
                "The bulk download site currently requires access credentials. "
                "Download the archive manually if you have access, then run seed-enacted-xml with the local ZIP path."
            ) from error
        raise BulkArchiveDownloadError(f"Failed to download {url}: HTTP {error.code} {error.reason}") from error

    return path


def seed_enacted_xml_from_archive(
    archive_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> list[Path]:
    paths: list[Path] = []

    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.endswith(".xml"):
                continue

            content = archive.read(member)
            path = document_output_path_from_xml(content, output_root=output_root, collection="enacted")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            paths.append(path)

    return paths


def document_output_path_from_xml(content: bytes, output_root: Path, collection: str) -> Path:
    legislation_type, year, number = document_ref_from_xml(content)
    return output_root / "xml" / collection / legislation_type / str(year) / str(number) / "data.xml"


def document_ref_from_xml(content: bytes) -> tuple[str, int, int]:
    root = ElementTree.fromstring(content)
    document_uri = root.attrib.get("DocumentURI")
    if document_uri is None:
        raise ValueError("No DocumentURI found in bulk XML document.")

    return document_ref_from_uri(document_uri)


def document_ref_from_uri(uri: str) -> tuple[str, int, int]:
    parts = [part for part in urlparse(uri).path.split("/") if part]
    if parts and parts[0] == "id":
        parts = parts[1:]

    for index in range(len(parts) - 2):
        legislation_type = parts[index]
        year = parts[index + 1]
        number = parts[index + 2]
        if year.isdigit() and number.isdigit():
            return legislation_type, int(year), int(number)

    raise ValueError(f"Could not identify legislation type, year, and number from URI: {uri}")
