"""Read-only object storage helpers for API responses."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from object_store import LocalObjectStore, file_sha256

from .settings import R2Settings


@dataclass(frozen=True)
class ResolvedContent:
    path: Path
    content_type: str
    sha256: str


@dataclass(frozen=True)
class ResolvedRemoteContent:
    url: str
    content_type: str
    sha256: str


class LocalContentStore:
    def __init__(self, object_store: LocalObjectStore) -> None:
        self.object_store = object_store

    def resolve(self, *, object_key: str, sha256: str, content_type: str) -> ResolvedContent:
        path = self.object_store.path_for_key(object_key)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(object_key)
        actual_sha256 = file_sha256(path)
        if actual_sha256 != sha256:
            raise ValueError(f"Object hash mismatch for {object_key}")
        return ResolvedContent(path=path, content_type=content_type, sha256=sha256)


class R2ContentStore:
    """Resolves object keys to short-lived presigned URLs on an S3-compatible bucket."""

    def __init__(self, settings: R2Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.client = client if client is not None else _create_s3_client(settings)

    def resolve(self, *, object_key: str, sha256: str, content_type: str) -> ResolvedRemoteContent:
        if not self._object_exists(object_key):
            raise FileNotFoundError(object_key)
        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.settings.bucket,
                "Key": object_key,
                "ResponseContentType": content_type,
            },
            ExpiresIn=self.settings.url_ttl_seconds,
        )
        return ResolvedRemoteContent(url=url, content_type=content_type, sha256=sha256)

    def _object_exists(self, object_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.settings.bucket, Key=object_key)
        except Exception as error:
            status = getattr(error, "response", {}).get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in {403, 404}:
                return False
            raise
        return True


def _create_s3_client(settings: R2Settings) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        region_name="auto",
    )
