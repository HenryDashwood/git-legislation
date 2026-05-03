import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import TracebackType
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import httpx

BASE_URL = "https://www.legislation.gov.uk"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "output"
USER_AGENT = "git-legislation/0.1"
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"


@dataclass(frozen=True)
class DocumentRef:
    legislation_type: str
    year: int
    number: int
    title: str


@dataclass(frozen=True)
class FetchRecord:
    status: str
    legislation_type: str
    year: int
    number: int | None = None
    title: str | None = None
    path: Path | None = None
    url: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "status": self.status,
            "legislation_type": self.legislation_type,
            "year": self.year,
        }
        if self.number is not None:
            record["number"] = self.number
        if self.title is not None:
            record["title"] = self.title
        if self.path is not None:
            record["path"] = str(self.path)
        if self.url is not None:
            record["url"] = self.url
        if self.error is not None:
            record["error"] = self.error
        return record


@dataclass(frozen=True)
class FetchManifest:
    corpus: str
    legislation_type: str
    start_year: int
    end_year: int
    records: list[FetchRecord]

    @property
    def paths(self) -> list[Path]:
        return [record.path for record in self.records if record.path is not None]

    def to_dict(self) -> dict[str, object]:
        return {
            "corpus": self.corpus,
            "legislation_type": self.legislation_type,
            "start_year": self.start_year,
            "end_year": self.end_year,
            "records": [record.to_dict() for record in self.records],
        }


class FetchResponse:
    def __init__(self, status_code: int, content: bytes, url: str) -> None:
        self.status_code = status_code
        self.content = content
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP status {self.status_code} for {self.url}",
                request=httpx.Request("GET", self.url),
                response=httpx.Response(self.status_code, request=httpx.Request("GET", self.url)),
            )


class LegislationClient:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}

    def __enter__(self) -> "LegislationClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def get(self, url: str) -> FetchResponse:
        request = Request(url, headers=self.headers)
        try:
            with urlopen(request) as response:
                return FetchResponse(response.status, response.read(), url)
        except HTTPError as error:
            return FetchResponse(error.code, error.read(), url)


def document_xml_url(
    legislation_type: str,
    year: int,
    number: int,
    as_enacted: bool = False,
    at: str | None = None,
) -> str:
    if as_enacted and at is not None:
        raise ValueError("Cannot fetch enacted XML at a point in time.")
    if as_enacted:
        return f"{BASE_URL}/{legislation_type}/{year}/{number}/enacted/data.xml"
    if at is not None:
        return f"{BASE_URL}/{legislation_type}/{year}/{number}/{at}/data.xml"
    return f"{BASE_URL}/{legislation_type}/{year}/{number}/data.xml"


def year_feed_url(legislation_type: str, year: int) -> str:
    return f"{BASE_URL}/{legislation_type}/{year}/data.feed"


def parse_year_feed(feed: bytes) -> list[DocumentRef]:
    root = ElementTree.fromstring(feed)
    documents: list[DocumentRef] = []

    for entry in root.findall(f"{{{ATOM_NAMESPACE}}}entry"):
        title = entry.findtext(f"{{{ATOM_NAMESPACE}}}title")
        link = entry.find(f"{{{ATOM_NAMESPACE}}}link[@rel='self']")
        if link is None:
            link = entry.find(f"{{{ATOM_NAMESPACE}}}link[@rel='alternate']")

        if title is None or link is None:
            continue

        href = link.attrib.get("href")
        if href is None:
            continue

        documents.append(_document_ref_from_href(href=href, title=title))

    return documents


def _document_ref_from_href(href: str, title: str) -> DocumentRef:
    parts = href.rstrip("/").split("/")
    return DocumentRef(
        legislation_type=parts[-3],
        year=int(parts[-2]),
        number=int(parts[-1]),
        title=title,
    )


def create_client() -> LegislationClient:
    return LegislationClient(
        headers={
            "Accept": "application/xml",
            "User-Agent": USER_AGENT,
        }
    )


def fetch_document_xml(
    client: httpx.Client,
    legislation_type: str,
    year: int,
    number: int,
    as_enacted: bool = False,
    at: str | None = None,
) -> bytes:
    url = document_xml_url(
        legislation_type=legislation_type,
        year=year,
        number=number,
        as_enacted=as_enacted,
        at=at,
    )
    response = client.get(url)
    response.raise_for_status()
    return response.content


def fetch_year_feed(client: httpx.Client, legislation_type: str, year: int) -> bytes:
    url = year_feed_url(legislation_type=legislation_type, year=year)
    response = client.get(url)
    response.raise_for_status()
    return response.content


def fetch_year_documents(
    client: httpx.Client,
    legislation_type: str,
    year: int,
    as_enacted: bool = False,
    at: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> list[Path]:
    return fetch_year_documents_manifest(
        client,
        legislation_type=legislation_type,
        year=year,
        as_enacted=as_enacted,
        at=at,
        output_root=output_root,
    ).paths


def fetch_year_documents_manifest(
    client: httpx.Client,
    legislation_type: str,
    year: int,
    as_enacted: bool = False,
    at: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> FetchManifest:
    try:
        feed = fetch_year_feed(client, legislation_type=legislation_type, year=year)
    except httpx.HTTPStatusError as error:
        return FetchManifest(
            corpus=_corpus_name(as_enacted=as_enacted, at=at),
            legislation_type=legislation_type,
            start_year=year,
            end_year=year,
            records=[
                FetchRecord(
                    status="missing-feed" if error.response.status_code == 404 else "failed-feed",
                    legislation_type=legislation_type,
                    year=year,
                    url=year_feed_url(legislation_type=legislation_type, year=year),
                    error=f"HTTP {error.response.status_code}",
                )
            ],
        )

    documents = parse_year_feed(feed)
    records: list[FetchRecord] = []

    for document in documents:
        try:
            content = fetch_document_xml(
                client,
                legislation_type=document.legislation_type,
                year=document.year,
                number=document.number,
                as_enacted=as_enacted,
                at=at,
            )
        except httpx.HTTPStatusError as error:
            records.append(
                FetchRecord(
                    status="missing" if error.response.status_code == 404 else "failed",
                    legislation_type=document.legislation_type,
                    year=document.year,
                    number=document.number,
                    title=document.title,
                    url=document_xml_url(
                        legislation_type=document.legislation_type,
                        year=document.year,
                        number=document.number,
                        as_enacted=as_enacted,
                        at=at,
                    ),
                    error=f"HTTP {error.response.status_code}",
                )
            )
            continue

        path = write_document_xml(
            content,
            legislation_type=document.legislation_type,
            year=document.year,
            number=document.number,
            as_enacted=as_enacted,
            at=at,
            output_root=output_root,
        )
        records.append(
            FetchRecord(
                status="fetched",
                legislation_type=document.legislation_type,
                year=document.year,
                number=document.number,
                title=document.title,
                path=path,
            )
        )

    return FetchManifest(
        corpus=_corpus_name(as_enacted=as_enacted, at=at),
        legislation_type=legislation_type,
        start_year=year,
        end_year=year,
        records=records,
    )


def fetch_enacted_corpus(
    client: httpx.Client,
    legislation_type: str,
    start_year: int,
    end_year: int,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> FetchManifest:
    if start_year > end_year:
        raise ValueError("start_year must be before or equal to end_year.")

    records: list[FetchRecord] = []
    for year in range(start_year, end_year + 1):
        records.extend(
            fetch_year_documents_manifest(
                client,
                legislation_type=legislation_type,
                year=year,
                as_enacted=True,
                output_root=output_root,
            ).records
        )

    return FetchManifest(
        corpus="enacted",
        legislation_type=legislation_type,
        start_year=start_year,
        end_year=end_year,
        records=records,
    )


def write_fetch_manifest(manifest: FetchManifest, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    path = (
        output_root
        / "manifests"
        / manifest.corpus
        / manifest.legislation_type
        / f"{manifest.start_year}-{manifest.end_year}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
    return path


def _corpus_name(as_enacted: bool, at: str | None) -> str:
    if as_enacted:
        return "enacted"
    if at is not None:
        return "point-in-time"
    return "point-in-time"


def write_document_xml(
    content: bytes,
    legislation_type: str,
    year: int,
    number: int,
    as_enacted: bool = False,
    at: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
) -> Path:
    if as_enacted and at is not None:
        raise ValueError("Cannot write enacted XML at a point in time.")
    if as_enacted:
        path = output_root / "xml" / "enacted" / legislation_type / str(year) / str(number) / "data.xml"
    else:
        snapshot_date = at or date.today().isoformat()
        path = (
            output_root
            / "xml"
            / "point-in-time"
            / snapshot_date
            / legislation_type
            / str(year)
            / str(number)
            / "data.xml"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
