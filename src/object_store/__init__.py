"""Object storage adapters for generated legislation artifacts."""

import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile

DEFAULT_OBJECT_STORE_ROOT = Path(__file__).resolve().parents[2] / "var" / "object-store"


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    path: Path
    sha256: str
    byte_size: int
    content_type: str


class LocalObjectStore:
    """Filesystem-backed stand-in for an object store such as R2."""

    def __init__(self, root: Path = DEFAULT_OBJECT_STORE_ROOT, bucket: str = "legislation") -> None:
        self.root = root
        self.bucket = bucket

    def put_file(self, source_path: Path, key: str, content_type: str | None = None) -> StoredObject:
        destination = self.path_for_key(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source_path, destination)
        return StoredObject(
            bucket=self.bucket,
            key=key,
            path=destination,
            sha256=file_sha256(destination),
            byte_size=destination.stat().st_size,
            content_type=content_type or guess_content_type(destination),
        )

    def put_bytes(self, content: bytes, key: str, content_type: str | None = None) -> StoredObject:
        destination = self.path_for_key(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return StoredObject(
            bucket=self.bucket,
            key=key,
            path=destination,
            sha256=file_sha256(destination),
            byte_size=destination.stat().st_size,
            content_type=content_type or guess_content_type(destination),
        )

    def put_text(self, content: str, key: str, content_type: str | None = None) -> StoredObject:
        return self.put_bytes(content.encode(), key=key, content_type=content_type)

    def path_for_key(self, key: str) -> Path:
        if key.startswith("/") or ".." in Path(key).parts:
            raise ValueError(f"Unsafe object key: {key}")
        return self.root / self.bucket / key


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guess_content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
