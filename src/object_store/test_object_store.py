import gzip
import hashlib
from pathlib import Path

import pytest

from object_store import LocalObjectStore, guess_content_type


def test_compressible_objects_are_stored_gzipped_under_a_gz_key(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# Example\n")
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")

    stored = store.put_file(source, key="markdown/example.md")

    assert stored.key == "markdown/example.md.gz"
    assert stored.path == tmp_path / "objects" / "legislation" / "markdown" / "example.md.gz"
    assert gzip.decompress(stored.path.read_bytes()) == b"# Example\n"
    assert stored.content_type == "text/markdown"


def test_stored_hash_is_of_the_original_content_not_the_compressed_bytes(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")

    stored = store.put_bytes(b"<xml />", key="xml/example.xml", content_type="application/xml")

    # Version identity and file integrity are about what the object says, so the
    # hash must not change just because the encoding did.
    assert stored.sha256 == hashlib.sha256(b"<xml />").hexdigest()
    assert stored.byte_size == stored.path.stat().st_size


def test_incompressible_objects_are_stored_as_is(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")

    stored = store.put_bytes(b"%PDF-1.7", key="pdf/example.pdf", content_type="application/pdf")

    assert stored.key == "pdf/example.pdf"
    assert stored.path.read_bytes() == b"%PDF-1.7"


def test_read_round_trips_compressed_and_plain_objects(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")
    compressed = store.put_text("# Heading\n", key="markdown/a.md")
    plain = store.put_bytes(b"%PDF-1.7", key="pdf/b.pdf", content_type="application/pdf")

    assert store.read_text(compressed.key) == "# Heading\n"
    assert store.read_bytes(plain.key) == b"%PDF-1.7"


def test_read_accepts_the_uncompressed_key_for_a_compressed_object(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")
    store.put_text("# Heading\n", key="markdown/a.md")

    # Callers holding a key recorded before compression must keep working.
    assert store.read_text("markdown/a.md") == "# Heading\n"
    assert store.exists("markdown/a.md")


def test_gzip_output_is_deterministic(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects", bucket="legislation")

    first = store.put_text("same text\n", key="markdown/one.md").path.read_bytes()
    second = store.put_text("same text\n", key="markdown/two.md").path.read_bytes()

    assert first == second


def test_local_object_store_rejects_unsafe_keys(tmp_path: Path) -> None:
    store = LocalObjectStore(root=tmp_path / "objects")

    with pytest.raises(ValueError):
        store.path_for_key("../outside.txt")

    with pytest.raises(ValueError):
        store.path_for_key("/absolute.txt")


def test_guess_content_type_sees_through_the_gz_suffix(tmp_path: Path) -> None:
    assert guess_content_type(Path("data.xml.gz")) == "application/xml"
    assert guess_content_type(Path("object.unknownsuffix")) == "application/octet-stream"
