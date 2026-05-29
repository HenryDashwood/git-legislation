from pathlib import Path

import pytest

from object_store import LocalObjectStore, file_sha256, guess_content_type


def test_local_object_store_copies_file_under_bucket_root(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Example\n")
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")

    stored = store.put_file(source, key="markdown/example.md")

    assert stored.bucket == "legislation"
    assert stored.key == "markdown/example.md"
    assert stored.path == tmp_path / "objects" / "legislation" / "markdown" / "example.md"
    assert stored.path.read_text() == "# Example\n"
    assert stored.sha256 == file_sha256(source)
    assert stored.byte_size == len("# Example\n")
    assert stored.content_type == "text/markdown"


def test_local_object_store_rejects_unsafe_keys(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects")

    with pytest.raises(ValueError):
        store.path_for_key("../outside.txt")

    with pytest.raises(ValueError):
        store.path_for_key("/absolute.txt")


def test_guess_content_type_falls_back_for_unknown_suffix(tmp_path: Path) -> None:
    path = tmp_path / "object.unknownsuffix"
    path.write_text("example")

    assert guess_content_type(path) == "application/octet-stream"
