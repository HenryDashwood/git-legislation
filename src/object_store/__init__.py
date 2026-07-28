"""Object storage adapters for generated legislation artifacts."""

import gzip
import hashlib
import mimetypes
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OBJECT_STORE_ROOT = Path(__file__).resolve().parents[2] / "var" / "object-store"
GZIP_SUFFIX = ".gz"
# XML and Markdown compress about 10x and 3x respectively, which is a far bigger
# saving than deduplication could offer (whole-document objects embed their
# request date, so byte-identical copies across snapshots are rare). PDFs and
# images are already compressed and are stored as-is.
COMPRESSIBLE_CONTENT_TYPES = (
    "text/",
    "application/xml",
    "application/json",
    "application/x-ndjson",
)
# mtime in the gzip header would make otherwise identical output differ run to
# run, which would defeat content-addressed comparisons downstream.
GZIP_MTIME = 0


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    path: Path
    sha256: str
    byte_size: int
    content_type: str


def is_compressible(content_type: str) -> bool:
    return content_type.startswith(COMPRESSIBLE_CONTENT_TYPES)


class LocalObjectStore:
    """Filesystem-backed stand-in for an object store such as R2."""

    def __init__(self, root: Path = DEFAULT_OBJECT_STORE_ROOT, bucket: str = "legislation") -> None:
        self.root = root
        self.bucket = bucket

    def put_file(self, source_path: Path, key: str, content_type: str | None = None) -> StoredObject:
        return self.put_bytes(
            source_path.read_bytes(),
            key=key,
            content_type=content_type or guess_content_type(source_path),
        )

    def put_bytes(self, content: bytes, key: str, content_type: str | None = None) -> StoredObject:
        resolved_type = content_type or guess_content_type(Path(key))
        stored_key = key
        payload = content
        if is_compressible(resolved_type):
            stored_key = f"{key}{GZIP_SUFFIX}"
            payload = gzip.compress(content, mtime=GZIP_MTIME)

        destination = self.path_for_key(stored_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        return StoredObject(
            bucket=self.bucket,
            key=stored_key,
            path=destination,
            # The hash is of the original content, not the stored bytes: version
            # identity and file integrity are about what the object says, not
            # how it happens to be encoded.
            sha256=hashlib.sha256(content).hexdigest(),
            byte_size=len(payload),
            content_type=resolved_type,
        )

    def put_text(self, content: str, key: str, content_type: str | None = None) -> StoredObject:
        return self.put_bytes(content.encode(), key=key, content_type=content_type)

    def read_bytes(self, key: str) -> bytes:
        """Read an object, decompressing transparently.

        Accepts either the stored key or the uncompressed name it was derived
        from, so callers holding a pre-compression key keep working.
        """
        path = self.path_for_key(key)
        if key.endswith(GZIP_SUFFIX):
            return gzip.decompress(path.read_bytes())
        compressed = self.path_for_key(f"{key}{GZIP_SUFFIX}")
        if compressed.exists():
            return gzip.decompress(compressed.read_bytes())
        return path.read_bytes()

    def read_text(self, key: str, errors: str = "strict") -> str:
        return self.read_bytes(key).decode(errors=errors)

    def exists(self, key: str) -> bool:
        return self.path_for_key(key).exists() or self.path_for_key(f"{key}{GZIP_SUFFIX}").exists()

    def path_for_key(self, key: str) -> Path:
        if key.startswith("/") or ".." in Path(key).parts:
            raise ValueError(f"Unsafe object key: {key}")
        return self.root / self.bucket / key


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guess_content_type(path: Path) -> str:
    name = path.name
    if name.endswith(GZIP_SUFFIX):
        name = name[: -len(GZIP_SUFFIX)]
    return mimetypes.guess_type(name)[0] or "application/octet-stream"
