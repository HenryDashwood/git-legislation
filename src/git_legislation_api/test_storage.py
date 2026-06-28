from pathlib import Path

import pytest

from git_legislation_api.storage import LocalContentStore
from object_store import LocalObjectStore, file_sha256


def test_local_content_store_resolves_existing_object_with_matching_hash(tmp_path: Path) -> None:
    path = tmp_path / "objects" / "legislation" / "markdown" / "example.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Example\n")
    store = LocalContentStore(LocalObjectStore(root=tmp_path / "objects", bucket="legislation"))

    content = store.resolve(
        object_key="markdown/example.md",
        sha256=file_sha256(path),
        content_type="text/markdown",
    )

    assert content.path == path
    assert content.content_type == "text/markdown"
    assert content.sha256 == file_sha256(path)


def test_local_content_store_rejects_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "objects" / "legislation" / "markdown" / "example.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Example\n")
    store = LocalContentStore(LocalObjectStore(root=tmp_path / "objects", bucket="legislation"))

    with pytest.raises(ValueError, match="Object hash mismatch"):
        store.resolve(
            object_key="markdown/example.md",
            sha256="wrong",
            content_type="text/markdown",
        )


def test_local_content_store_rejects_missing_object(tmp_path: Path) -> None:
    store = LocalContentStore(LocalObjectStore(root=tmp_path / "objects", bucket="legislation"))

    with pytest.raises(FileNotFoundError):
        store.resolve(
            object_key="markdown/missing.md",
            sha256="abc123",
            content_type="text/markdown",
        )
