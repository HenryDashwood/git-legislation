import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import httpx
from xmlformatter import Formatter


@dataclass(frozen=True)
class LegislationType:
    code: str
    label: str
    start_year: int
    end_year: int | None = None


BASE_URL = "https://www.legislation.gov.uk"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "output"
USER_AGENT = "git-legislation/0.1"
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"
LEGISLATION_NAMESPACE = "http://www.legislation.gov.uk/namespaces/legislation"
PUBLICATION_LOG_NAMESPACE = "http://www.legislation.gov.uk/namespaces/publication-log"
EMPTY_YEAR_LOG_INTERVAL = 100
FEED_NUMBER_RANGE_SIZE = 100
FEED_RANGE_436_RETRIES = 5
FEED_RANGE_436_BACKOFF_SECONDS = 30.0
FEED_RANGE_436_MAX_BACKOFF_SECONDS = 300.0
REQUEST_RETRY_DELAY_SECONDS = 1.0
REQUEST_RETRIES = 2
REQUEST_SERVER_ERROR_RETRIES = 5
REQUEST_SERVER_ERROR_BACKOFF_SECONDS = 5.0
REQUEST_SERVER_ERROR_MAX_BACKOFF_SECONDS = 60.0
REQUEST_RATE_LIMIT_RETRIES = 5
REQUEST_RATE_LIMIT_BACKOFF_SECONDS = 30.0
REQUEST_RATE_LIMIT_MAX_BACKOFF_SECONDS = 300.0
# legislation.gov.uk signals rate limiting with 429 and the non-standard 432
# (seen on sustained bulk PDF downloads).
RATE_LIMIT_STATUS_CODES = {429, 432}
REQUEST_TIMEOUT_SECONDS = 30.0
SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES = {
    "aep": LegislationType("aep", "Acts of the English Parliament", 1267, 1706),
    "aosp": LegislationType("aosp", "Acts of the Old Scottish Parliament", 1424, 1707),
    "aip": LegislationType("aip", "Acts of the Old Irish Parliament", 1495, 1800),
    "apgb": LegislationType("apgb", "Acts of the Parliament of Great Britain", 1707, 1800),
    "gbppa": LegislationType("gbppa", "Private and Personal Acts of the Parliament of Great Britain", 1707, 1800),
    "gbla": LegislationType("gbla", "Local Acts of the Parliament of Great Britain", 1797, 1800),
    "ukpga": LegislationType("ukpga", "UK Public General Acts", 1801),
    "ukla": LegislationType("ukla", "UK Local Acts", 1801),
    "ukppa": LegislationType("ukppa", "UK Private and Personal Acts", 1801),
    "apni": LegislationType("apni", "Acts of the Northern Ireland Parliament", 1921, 1972),
    "ukcm": LegislationType("ukcm", "UK Church Measures", 1920),
    "nisro": LegislationType("nisro", "Northern Ireland Statutory Rules and Orders", 1922),
    "uksi": LegislationType("uksi", "UK Statutory Instruments", 1948),
    "nisi": LegislationType("nisi", "Northern Ireland Orders in Council", 1972),
    "mnia": LegislationType("mnia", "Measures of the Northern Ireland Assembly", 1974, 1974),
    "nisr": LegislationType("nisr", "Northern Ireland Statutory Rules", 1991),
    "asp": LegislationType("asp", "Acts of the Scottish Parliament", 1999),
    "ssi": LegislationType("ssi", "Scottish Statutory Instruments", 1999),
    "wsi": LegislationType("wsi", "Wales Statutory Instruments", 1999),
    "nia": LegislationType("nia", "Acts of the Northern Ireland Assembly", 2000),
    "mwa": LegislationType("mwa", "Measures of the Welsh Assembly", 2008),
    "anaw": LegislationType("anaw", "Acts of the Welsh Assembly", 2012),
    "ukci": LegislationType("ukci", "UK Church Instruments", 2013),
    "asc": LegislationType("asc", "Acts of Senedd Cymru", 2020),
    "ukmo": LegislationType("ukmo", "UK Ministerial Orders", 2020),
}
POINT_IN_TIME_CORPUS_START_YEARS = {
    code: legislation_type.start_year for code, legislation_type in SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES.items()
}
POINT_IN_TIME_CORPUS_END_YEARS = {
    code: legislation_type.end_year
    for code, legislation_type in SUPPORTED_POINT_IN_TIME_LEGISLATION_TYPES.items()
    if legislation_type.end_year is not None
}


@dataclass(frozen=True)
class DocumentRef:
    legislation_type: str
    year: int
    number: int
    title: str
    source_path: tuple[str, ...] | None = None

    @property
    def path(self) -> tuple[str, ...]:
        return self.source_path or (self.legislation_type, str(self.year), str(self.number))


@dataclass(frozen=True)
class FetchProbe:
    label: str
    url: str
    status_code: int | None
    error: str | None
    pdf_alternatives: tuple[str, ...] = ()


@dataclass(frozen=True)
class FetchFailure:
    stage: str
    legislation_type: str
    year: int
    number: int | None
    url: str | None
    status_code: int | None
    error: str
    classification: str | None = None
    probes: list[FetchProbe] = field(default_factory=list)


class FetchResponseLike(Protocol):
    status_code: int
    content: bytes

    def raise_for_status(self) -> object: ...


class FetchClient(Protocol):
    def get(self, url: str) -> FetchResponseLike: ...


@dataclass
class FetchReport:
    mode: str
    legislation_type: str | None
    start_year: int | None
    end_year: int | None
    at: str | None
    fetched_paths: list[Path]
    failures: list[FetchFailure]

    @classmethod
    def enacted_corpus(cls, legislation_type: str, start_year: int, end_year: int) -> "FetchReport":
        return cls(
            mode="enacted",
            legislation_type=legislation_type,
            start_year=start_year,
            end_year=end_year,
            at=None,
            fetched_paths=[],
            failures=[],
        )

    @classmethod
    def point_in_time_corpus(cls, at: str) -> "FetchReport":
        return cls(
            mode="point-in-time",
            legislation_type=None,
            start_year=None,
            end_year=date.fromisoformat(at).year,
            at=at,
            fetched_paths=[],
            failures=[],
        )

    def record_fetched(self, path: Path) -> None:
        if path not in self.fetched_paths:
            self.fetched_paths.append(path)

    def record_failure(self, failure: FetchFailure) -> None:
        self.failures.append(failure)


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
    def __init__(
        self,
        headers: dict[str, str] | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        retries: int = REQUEST_RETRIES,
        server_error_retries: int = REQUEST_SERVER_ERROR_RETRIES,
        server_error_backoff_seconds: float = REQUEST_SERVER_ERROR_BACKOFF_SECONDS,
        server_error_max_backoff_seconds: float = REQUEST_SERVER_ERROR_MAX_BACKOFF_SECONDS,
        rate_limit_retries: int = REQUEST_RATE_LIMIT_RETRIES,
        rate_limit_backoff_seconds: float = REQUEST_RATE_LIMIT_BACKOFF_SECONDS,
        rate_limit_max_backoff_seconds: float = REQUEST_RATE_LIMIT_MAX_BACKOFF_SECONDS,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.headers = headers or {}
        self.timeout = timeout
        self.retries = retries
        self.server_error_retries = server_error_retries
        self.server_error_backoff_seconds = server_error_backoff_seconds
        self.server_error_max_backoff_seconds = server_error_max_backoff_seconds
        self.rate_limit_retries = rate_limit_retries
        self.rate_limit_backoff_seconds = rate_limit_backoff_seconds
        self.rate_limit_max_backoff_seconds = rate_limit_max_backoff_seconds
        self.log = log

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
        connection_attempts = 0
        rate_limit_attempts = 0
        server_error_attempts = 0

        while True:
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return FetchResponse(response.status, response.read(), url)
            except HTTPError as error:
                if error.code in RATE_LIMIT_STATUS_CODES and rate_limit_attempts < self.rate_limit_retries:
                    rate_limit_attempts += 1
                    delay_seconds = self._rate_limit_delay_seconds(error, rate_limit_attempts)
                    _log(
                        self.log,
                        f"Rate limited fetching {url}; waiting {delay_seconds:g}s before retry "
                        f"{rate_limit_attempts}/{self.rate_limit_retries}",
                    )
                    time.sleep(delay_seconds)
                    continue
                if error.code in {500, 502, 503, 504} and server_error_attempts < self.server_error_retries:
                    server_error_attempts += 1
                    delay_seconds = min(
                        self.server_error_backoff_seconds * (2 ** (server_error_attempts - 1)),
                        self.server_error_max_backoff_seconds,
                    )
                    _log(
                        self.log,
                        f"Server error {error.code} fetching {url}; waiting {delay_seconds:g}s before retry "
                        f"{server_error_attempts}/{self.server_error_retries}",
                    )
                    time.sleep(delay_seconds)
                    continue
                return FetchResponse(error.code, error.read(), url)
            except (TimeoutError, URLError, ConnectionResetError) as error:
                if connection_attempts == self.retries:
                    raise error
                connection_attempts += 1
                time.sleep(REQUEST_RETRY_DELAY_SECONDS)

    def _rate_limit_delay_seconds(self, error: HTTPError, attempt: int) -> float:
        retry_after = error.headers.get("Retry-After") if error.headers is not None else None
        retry_after_seconds = _retry_after_seconds(retry_after)
        if retry_after_seconds is not None:
            return retry_after_seconds
        return min(
            self.rate_limit_backoff_seconds * (2 ** (attempt - 1)),
            self.rate_limit_max_backoff_seconds,
        )


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    if value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(tz=UTC)).total_seconds())


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


def year_number_range_feed_url(legislation_type: str, year: int, start_number: int, end_number: int) -> str:
    return f"{BASE_URL}/{legislation_type}/{year}/{start_number}-{end_number}/data.feed"


def next_feed_url(feed: bytes) -> str | None:
    root = ElementTree.fromstring(feed)
    link = root.find(f"{{{ATOM_NAMESPACE}}}link[@rel='next']")
    if link is None:
        return None
    return link.attrib.get("href")


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
    parts = tuple(part for part in urlparse(href).path.strip("/").split("/") if part)
    if parts and parts[0] == "id":
        parts = parts[1:]

    legislation_type = parts[0]
    year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    number = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    return DocumentRef(
        legislation_type=legislation_type,
        year=year,
        number=number,
        title=title,
        source_path=parts,
    )


def publication_log_feed_url(updated_date: str, page: int = 1) -> str:
    # The feed's own rel="next" link is malformed (it appends a second "?page="
    # clause), so pagination is driven by an explicit page parameter instead.
    return f"{BASE_URL}/update/{updated_date}/legislation/data.feed?event=published&format=xml&page={page}"


@dataclass(frozen=True)
class PublicationEvent:
    document: DocumentRef
    updated: str
    is_new: bool
    is_republished: bool


def parse_publication_log_feed(feed: bytes) -> tuple[list[PublicationEvent], int]:
    """Parse one Publication Log page into events plus the remaining page count."""
    root = ElementTree.fromstring(feed)
    more_pages_text = root.findtext(f"{{{LEGISLATION_NAMESPACE}}}morePages")
    more_pages = int(more_pages_text) if more_pages_text and more_pages_text.isdigit() else 0

    events: list[PublicationEvent] = []
    for entry in root.findall(f"{{{ATOM_NAMESPACE}}}entry"):
        identifier = entry.findtext(f"{{{DC_NAMESPACE}}}identifier")
        if identifier is None:
            continue
        content_type = entry.findtext(f"{{{PUBLICATION_LOG_NAMESPACE}}}ContentType")
        if content_type != "legislation":
            continue
        document = _document_ref_from_href(
            href=identifier,
            title=entry.findtext(f"{{{ATOM_NAMESPACE}}}title") or "",
        )
        events.append(
            PublicationEvent(
                document=document,
                updated=entry.findtext(f"{{{ATOM_NAMESPACE}}}updated") or "",
                is_new=entry.findtext(f"{{{PUBLICATION_LOG_NAMESPACE}}}New") == "true",
                is_republished=entry.findtext(f"{{{PUBLICATION_LOG_NAMESPACE}}}Republished") == "true",
            )
        )

    return events, more_pages


def fetch_publication_day_events(
    client: FetchClient,
    updated_date: str,
    log: Callable[[str], None] | None = None,
) -> list[PublicationEvent]:
    """Fetch every XML legislation publication event logged on one date."""
    events: list[PublicationEvent] = []
    page = 1
    while True:
        response = client.get(publication_log_feed_url(updated_date, page=page))
        response.raise_for_status()
        page_events, more_pages = parse_publication_log_feed(response.content)
        events.extend(page_events)
        if more_pages <= 0:
            break
        page += 1
        if log is not None and page % 25 == 0:
            log(f"Publication Log {updated_date}: fetched {page} pages ({len(events)} events so far)")
    return events


def create_client(log: Callable[[str], None] | None = None) -> LegislationClient:
    return LegislationClient(
        headers={
            "Accept": "application/xml",
            "User-Agent": USER_AGENT,
        },
        log=log,
    )


def fetch_document_xml(
    client: FetchClient,
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
    _ensure_legislation_xml(response.content, url)
    return response.content


def fetch_document_ref_xml(
    client: FetchClient,
    document: DocumentRef,
    as_enacted: bool = False,
    at: str | None = None,
) -> bytes:
    url = document_ref_xml_url(document=document, as_enacted=as_enacted, at=at)
    response = client.get(url)
    response.raise_for_status()
    _ensure_legislation_xml(response.content, url)
    return response.content


def document_ref_from_source_path(source_path: str) -> DocumentRef:
    parts = tuple(part for part in source_path.strip("/").split("/") if part)
    if len(parts) < 3:
        raise ValueError("Source path must look like {type}/{year-or-era}/{number-or-regnal-year}/...")

    legislation_type = parts[0]
    year = int(parts[1]) if parts[1].isdigit() else 0
    number = int(parts[2]) if len(parts) == 3 and parts[2].isdigit() else 0

    return DocumentRef(
        legislation_type=legislation_type,
        year=year,
        number=number,
        title="",
        source_path=parts,
    )


def document_ref_xml_url(document: DocumentRef, as_enacted: bool = False, at: str | None = None) -> str:
    if as_enacted and at is not None:
        raise ValueError("Cannot fetch enacted XML at a point in time.")

    path = "/".join(document.path)
    if as_enacted:
        return f"{BASE_URL}/{path}/enacted/data.xml"
    if at is not None:
        return f"{BASE_URL}/{path}/{at}/data.xml"
    return f"{BASE_URL}/{path}/data.xml"


def write_source_document_xml(
    content: bytes,
    source_path: tuple[str, ...],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    as_enacted: bool = False,
    at: str | None = None,
) -> Path:
    if as_enacted and at is not None:
        raise ValueError("Cannot write enacted XML at a point in time.")
    if not source_path:
        raise ValueError("Cannot write XML without a source path.")

    if as_enacted:
        path = output_root / "xml" / "enacted" / Path(*source_path) / "data.xml"
    elif at is not None:
        path = output_root / "xml" / "point-in-time" / at / Path(*source_path) / "data.xml"
    else:
        path = output_root / "xml" / "latest" / Path(*source_path) / "data.xml"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(format_xml(content))
    return path


def fetch_year_feed(client: FetchClient, legislation_type: str, year: int) -> bytes:
    url = year_feed_url(legislation_type=legislation_type, year=year)
    response = client.get(url)
    response.raise_for_status()
    return response.content


def fetch_year_document_refs(
    client: FetchClient,
    legislation_type: str,
    year: int,
    log: Callable[[str], None] | None = None,
) -> list[DocumentRef]:
    try:
        return _fetch_document_refs_from_feed(
            client,
            year_feed_url(legislation_type=legislation_type, year=year),
            log=log,
        )
    except httpx.HTTPStatusError as error:
        if error.response.status_code != 436:
            raise
        _log(log, f"Splitting {legislation_type} {year} feed into {FEED_NUMBER_RANGE_SIZE}-number ranges")
        return _fetch_year_document_refs_by_number_range(
            client,
            legislation_type=legislation_type,
            year=year,
            log=log,
        )


def _fetch_document_refs_from_feed(
    client: FetchClient,
    url: str,
    log: Callable[[str], None] | None = None,
) -> list[DocumentRef]:
    documents: list[DocumentRef] = []
    page_count = 0
    next_url: str | None = url

    while next_url is not None:
        response = client.get(next_url)
        response.raise_for_status()
        page_count += 1
        page_documents = parse_year_feed(response.content)
        documents.extend(page_documents)
        if page_count > 1:
            _log(log, f"Read feed page {page_count}: {len(documents)} documents discovered so far from {next_url}")
        next_url = next_feed_url(response.content)

    return documents


def _fetch_year_document_refs_by_number_range(
    client: FetchClient,
    legislation_type: str,
    year: int,
    log: Callable[[str], None] | None = None,
) -> list[DocumentRef]:
    documents: list[DocumentRef] = []
    start_number = 1

    while True:
        end_number = start_number + FEED_NUMBER_RANGE_SIZE - 1
        url = year_number_range_feed_url(
            legislation_type=legislation_type,
            year=year,
            start_number=start_number,
            end_number=end_number,
        )
        try:
            range_documents = _fetch_number_range_documents(client, url, log=log)
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                break
            raise

        if not range_documents:
            break

        documents.extend(range_documents)
        _log(
            log,
            f"Discovered {len(range_documents)} documents in {legislation_type} {year} "
            f"{start_number}-{end_number}: {len(documents)} year total",
        )
        start_number = end_number + 1

    return documents


def _fetch_number_range_documents(
    client: FetchClient,
    url: str,
    log: Callable[[str], None] | None = None,
) -> list[DocumentRef]:
    # A number-range feed is never too broad, so a 436 here means the search
    # backend is under strain rather than the query being unanswerable.
    attempts = 0
    while True:
        try:
            return _fetch_document_refs_from_feed(client, url, log=log)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 436 or attempts == FEED_RANGE_436_RETRIES:
                raise
            attempts += 1
            delay_seconds = min(
                FEED_RANGE_436_BACKOFF_SECONDS * (2 ** (attempts - 1)),
                FEED_RANGE_436_MAX_BACKOFF_SECONDS,
            )
            _log(
                log,
                f"Feed unavailable (436) for {url}; waiting {delay_seconds:g}s before retry "
                f"{attempts}/{FEED_RANGE_436_RETRIES}",
            )
            time.sleep(delay_seconds)


def fetch_year_documents(
    client: FetchClient,
    legislation_type: str,
    year: int,
    as_enacted: bool = False,
    at: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report: FetchReport | None = None,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    if log is None:
        documents = fetch_year_document_refs(client, legislation_type=legislation_type, year=year)
    else:
        documents = fetch_year_document_refs(client, legislation_type=legislation_type, year=year, log=log)
    paths: list[Path] = []

    for index, document in enumerate(documents, start=1):
        path = document_xml_output_path(
            legislation_type=document.legislation_type,
            year=document.year,
            number=document.number,
            as_enacted=as_enacted,
            at=at,
            output_root=output_root,
            source_path=document.path,
        )
        if _usable_existing_document_xml(path):
            paths.append(path)
            continue
        if path.exists():
            path.unlink()

        attempted_url = document_ref_xml_url(document=document, as_enacted=as_enacted, at=at)
        try:
            content = fetch_document_ref_xml(
                client,
                document=document,
                as_enacted=as_enacted,
                at=at,
            )
        except Exception as error:
            if report is None:
                raise
            report.record_failure(
                _failure_from_error(
                    error,
                    stage="document",
                    legislation_type=document.legislation_type,
                    year=year,
                    number=document.number,
                    url=attempted_url,
                )
            )
            continue

        paths.append(
            write_document_xml(
                content,
                legislation_type=document.legislation_type,
                year=document.year,
                number=document.number,
                as_enacted=as_enacted,
                at=at,
                output_root=output_root,
                source_path=document.path,
            )
        )
        if index % 500 == 0:
            _log(log, f"Fetched {index} of {len(documents)} documents for {legislation_type} {year}")

    return paths


def fetch_enacted_corpus(
    client: FetchClient,
    legislation_type: str,
    start_year: int,
    end_year: int,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report: FetchReport | None = None,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    if start_year > end_year:
        raise ValueError("start_year must be before or equal to end_year.")

    paths: list[Path] = []
    empty_start_year: int | None = None
    for year in range(start_year, end_year + 1):
        try:
            failure_count_before = len(report.failures) if report is not None else 0
            if report is None:
                year_paths = fetch_year_documents(
                    client,
                    legislation_type=legislation_type,
                    year=year,
                    as_enacted=True,
                    output_root=output_root,
                    log=log,
                )
            else:
                year_paths = fetch_year_documents(
                    client,
                    legislation_type=legislation_type,
                    year=year,
                    as_enacted=True,
                    output_root=output_root,
                    report=report,
                    log=log,
                )
        except Exception as error:
            if report is None:
                raise
            report.record_failure(
                _failure_from_error(error, stage="year", legislation_type=legislation_type, year=year)
            )
            empty_start_year = None
            _log(log, f"Failed enacted {legislation_type} {year}: {error}")
            continue

        year_failures = len(report.failures) - failure_count_before if report is not None else 0
        if not year_paths and not year_failures:
            empty_start_year = _log_empty_year_checkpoint(
                log,
                empty_start_year=empty_start_year,
                year=year,
                message=lambda start, current: f"Checked enacted {legislation_type} {start}-{current}: no documents",
            )
            continue

        empty_start_year = None
        paths.extend(year_paths)
        if report is not None:
            for path in year_paths:
                report.record_fetched(path)
        _log(
            log,
            _year_fetch_message(
                prefix=f"Fetched enacted {legislation_type} {year}",
                documents=len(year_paths),
                failures=year_failures,
            ),
        )

    return paths


def fetch_point_in_time_corpus(
    client: FetchClient,
    at: str | None = None,
    legislation_types: tuple[str, ...] | list[str] | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    report: FetchReport | None = None,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    snapshot_date = at or date.today().isoformat()
    snapshot_year = date.fromisoformat(snapshot_date).year
    paths: list[Path] = []
    for legislation_type in _point_in_time_corpus_types(legislation_types):
        start_year = POINT_IN_TIME_CORPUS_START_YEARS[legislation_type]
        end_year = min(snapshot_year, POINT_IN_TIME_CORPUS_END_YEARS.get(legislation_type, snapshot_year))
        empty_start_year: int | None = None
        for year in range(start_year, end_year + 1):
            try:
                failure_count_before = len(report.failures) if report is not None else 0
                if report is None:
                    year_paths = fetch_year_documents(
                        client,
                        legislation_type=legislation_type,
                        year=year,
                        at=at,
                        output_root=output_root,
                        log=log,
                    )
                else:
                    year_paths = fetch_year_documents(
                        client,
                        legislation_type=legislation_type,
                        year=year,
                        at=at,
                        output_root=output_root,
                        report=report,
                        log=log,
                    )
            except Exception as error:
                if report is None:
                    raise
                report.record_failure(
                    _failure_from_error(error, stage="year", legislation_type=legislation_type, year=year)
                )
                empty_start_year = None
                _log(log, f"Failed point-in-time {legislation_type} {year} at {snapshot_date}: {error}")
                continue

            year_failures = len(report.failures) - failure_count_before if report is not None else 0
            if not year_paths and not year_failures:
                empty_start_year = _log_empty_year_checkpoint(
                    log,
                    empty_start_year=empty_start_year,
                    year=year,
                    message=lambda start, current, legislation_type=legislation_type: (
                        f"Checked point-in-time {legislation_type} {start}-{current} at {snapshot_date}: no documents"
                    ),
                )
                continue

            empty_start_year = None
            paths.extend(year_paths)
            if report is not None:
                for path in year_paths:
                    report.record_fetched(path)
            _log(
                log,
                _year_fetch_message(
                    prefix=f"Fetched point-in-time {legislation_type} {year} at {snapshot_date}",
                    documents=len(year_paths),
                    failures=year_failures,
                ),
            )

    return paths


def _point_in_time_corpus_types(legislation_types: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    selected_types = tuple(POINT_IN_TIME_CORPUS_START_YEARS) if legislation_types is None else tuple(legislation_types)
    unknown_types = sorted(set(selected_types) - set(POINT_IN_TIME_CORPUS_START_YEARS))
    if unknown_types:
        raise ValueError(f"Unsupported point-in-time corpus legislation type(s): {', '.join(unknown_types)}")
    return selected_types


def write_fetch_report(report: FetchReport, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    if report.mode == "enacted":
        if report.legislation_type is None or report.start_year is None or report.end_year is None:
            raise ValueError("Enacted fetch reports require legislation_type, start_year, and end_year.")
        path = (
            output_root
            / "reports"
            / "fetch"
            / "enacted"
            / report.legislation_type
            / f"{report.start_year}-{report.end_year}.json"
        )
    elif report.mode == "point-in-time":
        if report.at is None:
            raise ValueError("Point-in-time fetch reports require at.")
        path = output_root / "reports" / "fetch" / "point-in-time" / f"{report.at}.json"
    else:
        raise ValueError(f"Unsupported fetch report mode: {report.mode}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_report_json(report), indent=2) + "\n")
    return path


def read_fetch_report(path: Path) -> FetchReport:
    data = json.loads(path.read_text())
    return FetchReport(
        mode=data["mode"],
        legislation_type=data["legislation_type"],
        start_year=data["start_year"],
        end_year=data["end_year"],
        at=data["at"],
        fetched_paths=[Path(fetched_path) for fetched_path in data["fetched"]],
        failures=[
            FetchFailure(
                stage=failure["stage"],
                legislation_type=failure["legislation_type"],
                year=failure["year"],
                number=failure["number"],
                url=failure["url"],
                status_code=failure["status_code"],
                error=failure["error"],
                classification=failure.get("classification"),
                probes=[
                    FetchProbe(
                        label=probe["label"],
                        url=probe["url"],
                        status_code=probe["status_code"],
                        error=probe["error"],
                        pdf_alternatives=tuple(probe.get("pdf_alternatives", [])),
                    )
                    for probe in failure.get("probes", [])
                ],
            )
            for failure in data["failures"]
        ],
    )


def probe_fetch_report_failures(
    client: FetchClient,
    report: FetchReport,
    limit: int | None = None,
    log: Callable[[str], None] | None = None,
) -> int:
    probed = 0

    for index, failure in enumerate(report.failures):
        if limit is not None and probed >= limit:
            break
        if failure.probes:
            continue

        probe_urls = _failure_probe_urls(failure.url)
        if not probe_urls:
            continue

        probes = [_probe_url(client, label=label, url=url) for label, url in probe_urls]
        report.failures[index] = replace(failure, probes=probes, classification=_classify_failure_probes(probes))
        probed += 1
        _log(log, f"Probed {failure.url}: {_probe_summary(probes)}")

    return probed


def _report_json(report: FetchReport) -> dict[str, object]:
    return {
        "mode": report.mode,
        "legislation_type": report.legislation_type,
        "start_year": report.start_year,
        "end_year": report.end_year,
        "at": report.at,
        "fetched": [str(path) for path in report.fetched_paths],
        "failures": [
            {
                "stage": failure.stage,
                "legislation_type": failure.legislation_type,
                "year": failure.year,
                "number": failure.number,
                "url": failure.url,
                "status_code": failure.status_code,
                "error": failure.error,
                "classification": failure.classification or _classify_failure_probes(failure.probes),
                "probes": [
                    {
                        "label": probe.label,
                        "url": probe.url,
                        "status_code": probe.status_code,
                        "error": probe.error,
                        "pdf_alternatives": list(probe.pdf_alternatives),
                    }
                    for probe in failure.probes
                ],
            }
            for failure in report.failures
        ],
    }


def _failure_from_error(
    error: Exception,
    stage: str,
    legislation_type: str,
    year: int,
    number: int | None = None,
    url: str | None = None,
) -> FetchFailure:
    status_code: int | None = None
    message = str(error)

    if isinstance(error, httpx.HTTPStatusError):
        url = str(error.request.url)
        status_code = error.response.status_code

    return FetchFailure(
        stage=stage,
        legislation_type=legislation_type,
        year=year,
        number=number,
        url=url,
        status_code=status_code,
        error=message,
    )


def _ensure_legislation_xml(content: bytes, url: str) -> None:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise ValueError(f"Response from {url} is not parseable legislation XML: {error}") from error

    if _local_name(root.tag) != "Legislation":
        raise ValueError(f"Response from {url} is {_local_name(root.tag)!r}, not legislation XML")


def _usable_existing_document_xml(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        root = ElementTree.parse(path).getroot()
    except ElementTree.ParseError:
        return False
    return _local_name(root.tag) == "Legislation"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _year_fetch_message(prefix: str, documents: int, failures: int) -> str:
    message = f"{prefix}: {documents} documents"
    if failures:
        message += f", {failures} failures"
    return message


def _failure_probe_urls(url: str | None) -> list[tuple[str, str]]:
    if url is None:
        return []

    parsed = urlparse(url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2 or parts[-1] != "data.xml":
        return []

    document_parts = parts[:-1]
    if _looks_like_iso_date(document_parts[-1]):
        document_parts = document_parts[:-1]

    base_url = f"{parsed.scheme}://{parsed.netloc}/{'/'.join(document_parts)}"
    return [
        ("latest_xml", f"{base_url}/data.xml"),
        ("enacted_xml", f"{base_url}/enacted/data.xml"),
        ("resources_xml", f"{base_url}/resources/data.xml"),
    ]


def _looks_like_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _probe_url(client: FetchClient, label: str, url: str) -> FetchProbe:
    try:
        response = client.get(url)
        status_code = response.status_code
        content = response.content
    except Exception as error:
        return FetchProbe(label=label, url=url, status_code=None, error=str(error))

    pdf_alternatives: tuple[str, ...] = ()
    if label == "resources_xml" and status_code < 400:
        pdf_alternatives = _pdf_alternatives_from_resources(content)

    return FetchProbe(label=label, url=url, status_code=status_code, error=None, pdf_alternatives=pdf_alternatives)


def _pdf_alternatives_from_resources(content: bytes) -> tuple[str, ...]:
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return ()

    alternatives: list[str] = []
    for element in root.iter():
        uri = element.attrib.get("URI")
        if uri is not None and ".pdf" in uri.lower():
            alternatives.append(uri)
    return tuple(alternatives)


def _probe_summary(probes: list[FetchProbe]) -> str:
    return ", ".join(f"{probe.label}={probe.status_code or 'error'}" for probe in probes)


def _classify_failure_probes(probes: list[FetchProbe]) -> str | None:
    if not probes:
        return None

    latest_xml = _probe_status(probes, "latest_xml")
    enacted_xml = _probe_status(probes, "enacted_xml")
    resources_xml = _probe_status(probes, "resources_xml")
    has_pdf = any(probe.pdf_alternatives for probe in probes)

    if latest_xml == 200:
        if has_pdf:
            return "dated_xml_unavailable_latest_xml_available_pdf_available"
        return "dated_xml_unavailable_latest_xml_available"
    if enacted_xml == 200:
        if has_pdf:
            return "dated_xml_unavailable_enacted_xml_available_pdf_available"
        return "dated_xml_unavailable_enacted_xml_available"
    if resources_xml == 200 and has_pdf:
        return "dated_xml_unavailable_pdf_available"
    if resources_xml == 200:
        return "dated_xml_unavailable_metadata_available"
    return "dated_xml_unavailable_no_fallback_found"


def _probe_status(probes: list[FetchProbe], label: str) -> int | None:
    for probe in probes:
        if probe.label == label:
            return probe.status_code
    return None


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log is not None:
        log(message)


def _log_empty_year_checkpoint(
    log: Callable[[str], None] | None,
    empty_start_year: int | None,
    year: int,
    message: Callable[[int, int], str],
) -> int | None:
    start_year = empty_start_year or year
    if (year - start_year + 1) % EMPTY_YEAR_LOG_INTERVAL == 0:
        _log(log, message(start_year, year))
        return None
    return start_year


def document_xml_output_path(
    legislation_type: str,
    year: int,
    number: int,
    as_enacted: bool = False,
    at: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    source_path: tuple[str, ...] | None = None,
) -> Path:
    if as_enacted and at is not None:
        raise ValueError("Cannot write enacted XML at a point in time.")
    document_path = source_path or (legislation_type, str(year), str(number))
    if as_enacted:
        return output_root / "xml" / "enacted" / Path(*document_path) / "data.xml"

    snapshot_date = at or date.today().isoformat()
    return output_root / "xml" / "point-in-time" / snapshot_date / Path(*document_path) / "data.xml"


def write_document_xml(
    content: bytes,
    legislation_type: str,
    year: int,
    number: int,
    as_enacted: bool = False,
    at: str | None = None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    source_path: tuple[str, ...] | None = None,
) -> Path:
    path = document_xml_output_path(
        legislation_type=legislation_type,
        year=year,
        number=number,
        as_enacted=as_enacted,
        at=at,
        output_root=output_root,
        source_path=source_path,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(format_xml(content))
    return path


def format_xml(content: bytes) -> bytes:
    formatter = Formatter(indent=1, indent_char="\t", selfclose=True, eof_newline=True)
    return formatter.format_string(content)
