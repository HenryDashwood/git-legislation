"""Runtime settings for the read API."""

import os
from dataclasses import dataclass
from pathlib import Path

from object_store import DEFAULT_OBJECT_STORE_ROOT


@dataclass(frozen=True)
class ApiSettings:
    database_url: str | None
    object_store_root: Path
    object_store_bucket: str
    cors_origins: tuple[str, ...]


def load_settings() -> ApiSettings:
    return ApiSettings(
        database_url=os.environ.get("DB_URL"),
        object_store_root=Path(os.environ.get("OBJECT_STORE_ROOT", str(DEFAULT_OBJECT_STORE_ROOT))),
        object_store_bucket=os.environ.get("OBJECT_STORE_BUCKET", "legislation"),
        cors_origins=_parse_csv(os.environ.get("CORS_ORIGINS", "")),
    )


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
