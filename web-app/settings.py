"""Runtime settings for the HTMX web app."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WebSettings:
    api_base_url: str


def load_settings() -> WebSettings:
    return WebSettings(api_base_url=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"))
