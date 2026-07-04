"""Runtime settings for the read API."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from object_store import DEFAULT_OBJECT_STORE_ROOT


@dataclass(frozen=True)
class R2Settings:
    endpoint_url: str
    bucket: str
    access_key_id: str
    secret_access_key: str
    url_ttl_seconds: int


@dataclass(frozen=True)
class ApiSettings:
    database_url: str | None
    object_store_root: Path
    object_store_bucket: str
    cors_origins: tuple[str, ...]
    content_store_backend: str = "local"
    r2: R2Settings | None = None


def load_settings() -> ApiSettings:
    backend = os.environ.get("CONTENT_STORE_BACKEND", "local")
    if backend not in {"local", "r2"}:
        raise ValueError(f"Unsupported CONTENT_STORE_BACKEND: {backend}")
    return ApiSettings(
        database_url=os.environ.get("DB_URL"),
        object_store_root=Path(os.environ.get("OBJECT_STORE_ROOT", str(DEFAULT_OBJECT_STORE_ROOT))),
        object_store_bucket=os.environ.get("OBJECT_STORE_BUCKET", "legislation"),
        cors_origins=_parse_csv(os.environ.get("CORS_ORIGINS", "")),
        content_store_backend=backend,
        r2=_load_r2_settings() if backend == "r2" else None,
    )


def _load_r2_settings() -> R2Settings:
    endpoint_url = os.environ.get("R2_ENDPOINT_URL", "")
    bucket = os.environ.get("R2_BUCKET", "")
    if not endpoint_url or not bucket:
        # Fall back to the combined form: https://<account>.r2.cloudflarestorage.com/<bucket>
        combined = os.environ.get("R2_URL", "")
        if combined:
            parsed = urlparse(combined)
            endpoint_url = endpoint_url or f"{parsed.scheme}://{parsed.netloc}"
            bucket = bucket or parsed.path.strip("/")
    access_key_id = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_access_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    missing = [
        name
        for name, value in (
            ("R2_ENDPOINT_URL (or R2_URL)", endpoint_url),
            ("R2_BUCKET (or R2_URL)", bucket),
            ("R2_ACCESS_KEY_ID", access_key_id),
            ("R2_SECRET_ACCESS_KEY", secret_access_key),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"CONTENT_STORE_BACKEND=r2 requires: {', '.join(missing)}")
    return R2Settings(
        endpoint_url=endpoint_url,
        bucket=bucket,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        url_ttl_seconds=int(os.environ.get("R2_URL_TTL_SECONDS", "300")),
    )


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
