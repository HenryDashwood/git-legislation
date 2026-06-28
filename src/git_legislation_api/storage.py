"""Read-only object storage helpers for API responses."""

from dataclasses import dataclass
from pathlib import Path

from object_store import LocalObjectStore, file_sha256


@dataclass(frozen=True)
class ResolvedContent:
    path: Path
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
