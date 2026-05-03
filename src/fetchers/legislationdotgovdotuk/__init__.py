from pathlib import Path
from types import TracebackType
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import httpx

BASE_URL = "https://www.legislation.gov.uk"
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[3] / "output"
USER_AGENT = "git-legislation/0.1"


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


def document_xml_url(legislation_type: str, year: int, number: int) -> str:
    return f"{BASE_URL}/{legislation_type}/{year}/{number}/data.xml"


def create_client() -> LegislationClient:
    return LegislationClient(
        headers={
            "Accept": "application/xml",
            "User-Agent": USER_AGENT,
        }
    )


def fetch_document_xml(client: httpx.Client, legislation_type: str, year: int, number: int) -> bytes:
    url = document_xml_url(legislation_type=legislation_type, year=year, number=number)
    response = client.get(url)
    response.raise_for_status()
    return response.content


def write_document_xml(
    content: bytes, legislation_type: str, year: int, number: int, output_root: Path = DEFAULT_OUTPUT_ROOT
) -> Path:
    path = output_root / "00_xml" / legislation_type / str(year) / f"{number}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
