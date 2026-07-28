"""Publish converted legislation Markdown into queryable databases."""

import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import yaml

from object_store import (
    DEFAULT_OBJECT_STORE_ROOT,
    LocalObjectStore,
    StoredObject,
    guess_content_type,
    is_compressible,
)

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"
PUBLISH_LOG_INTERVAL = 1000
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
SCHEDULE_HEADING_RE = re.compile(r"^SCHEDULES?\.?\s+([A-Za-z]?\d+[A-Za-z]?)\b", re.IGNORECASE)
# A trailing "(S)" / "(E+W)" / "(N.I.)" marks an alternative-extent reading of a
# provision. Restricted to extent letters so ordinary parenthesised headings
# are not mistaken for one.
EXTENT_SUFFIX_RE = re.compile(r"\s+\(([EWSNI.+ ]+)\)$")
# Point-in-time CLML embeds the request date in legislation.gov.uk URIs
# (DocumentURI, PDF alternatives), so identical content fetched under two
# --at dates hashes differently unless those date segments are stripped.
DATED_LEGISLATION_URI_RE = re.compile(
    r"(https?://(?:www\.)?legislation\.gov\.uk/[^\s\"'<>\])]*?)/\d{4}-\d{2}-\d{2}(?=[/\s\"'<>\]),?#]|$)"
)
WINDOWS_1252_CONTROL_CHARS = str.maketrans(
    {
        "\x80": "EUR",
        "\x82": "'",
        "\x83": "f",
        "\x84": '"',
        "\x85": "...",
        "\x86": "+",
        "\x87": "++",
        "\x88": "^",
        "\x89": " per mille ",
        "\x8a": "S",
        "\x8b": "<",
        "\x8c": "OE",
        "\x8e": "Z",
        "\x91": "'",
        "\x92": "'",
        "\x93": '"',
        "\x94": '"',
        "\x95": "*",
        "\x96": "-",
        "\x97": "-",
        "\x98": "~",
        "\x99": "TM",
        "\x9a": "s",
        "\x9b": ">",
        "\x9c": "oe",
        "\x9e": "z",
        "\x9f": "Y",
    }
)


@dataclass(frozen=True)
class MarkdownDocumentRef:
    collection: str
    snapshot_date: str | None
    source_path: tuple[str, ...]
    markdown_path: Path

    @property
    def legislation_type(self) -> str:
        return self.source_path[0]

    @property
    def year(self) -> str | None:
        if len(self.source_path) < 3:
            return None
        return self.source_path[1]

    @property
    def number(self) -> str:
        return self.source_path[-1]

    @property
    def document_id(self) -> str:
        return "/".join(self.source_path)

    @property
    def version_id(self) -> str:
        if self.collection == "enacted":
            return f"enacted:{self.document_id}"
        return f"point-in-time:{self.snapshot_date}:{self.document_id}"


@dataclass(frozen=True)
class ProvisionRecord:
    ordinal: int
    heading: str
    number: str | None
    anchor: str
    markdown: str
    text: str
    extent: str | None = None

    @property
    def text_sha256(self) -> str:
        """Content address of this provision's text, shared across every version that repeats it."""
        return hashlib.sha256(self.markdown.encode()).hexdigest()


@dataclass(frozen=True)
class ParsedMarkdownDocument:
    ref: MarkdownDocumentRef
    metadata: dict[str, Any]
    markdown: str
    body_markdown: str
    provisions: tuple[ProvisionRecord, ...]

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or _fallback_title(self.body_markdown) or self.ref.document_id)

    @property
    def document_uri(self) -> str | None:
        value = self.metadata.get("document_uri")
        return str(value) if value else None

    @property
    def status(self) -> str | None:
        value = self.metadata.get("status")
        return str(value) if value else None

    @property
    def extent(self) -> str | None:
        value = self.metadata.get("extent")
        return str(value) if value else None

    @property
    def pdf_alternatives(self) -> tuple[str, ...]:
        value = self.metadata.get("pdf_alternatives")
        if not isinstance(value, list):
            return ()
        return tuple(str(item) for item in value)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.markdown.encode()).hexdigest()

    @property
    def canonical_content_hash(self) -> str:
        return canonical_markdown_sha256(self.markdown)

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\b\w+\b", markdown_to_text(self.body_markdown)))

    @property
    def is_metadata_only(self) -> bool:
        return "Source XML contains metadata only" in self.body_markdown


@dataclass
class PublishReport:
    collection: str
    snapshot_date: str | None = None
    scanned: int = 0
    published: int = 0
    created_versions: int = 0
    reused_versions: int = 0
    failures: list[str] = field(default_factory=list)
    database_path: str | None = None


@dataclass(frozen=True)
class PublishedVersion:
    document_id: str
    version_id: str
    source_uri: str | None
    source_sha256: str
    created: bool


def publish_markdown_to_postgres(
    markdown_root: Path,
    database_url: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    object_store_root: Path = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: str = "legislation",
    collection: str = "point-in-time",
    snapshot_date: str | None = None,
    legislation_types: Iterable[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> PublishReport:
    if collection not in {"enacted", "point-in-time"}:
        raise ValueError(f"Unknown Markdown collection: {collection}")
    if collection == "point-in-time" and snapshot_date is None:
        raise ValueError("Point-in-time Markdown publishing requires a snapshot date.")
    if collection == "enacted" and snapshot_date is not None:
        raise ValueError("Enacted Markdown publishing cannot use a snapshot date.")

    report = PublishReport(collection=collection, snapshot_date=snapshot_date, database_path="Postgres")
    selected_types = set(legislation_types or [])
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)

    with psycopg.connect(database_url) as connection:
        publish_run_id = create_publish_run(
            connection,
            collection=collection,
            snapshot_date=snapshot_date,
            legislation_types=selected_types,
        )
        for index, markdown_path in enumerate(
            iter_markdown_paths(markdown_root=markdown_root, legislation_types=selected_types),
            start=1,
        ):
            report.scanned += 1
            try:
                ref = markdown_ref_from_path(
                    markdown_path,
                    output_root=output_root,
                    collection=collection,
                    snapshot_date=snapshot_date,
                )
                if selected_types and ref.legislation_type not in selected_types:
                    continue
                document = parse_markdown_document(ref)
                published_version = upsert_postgres_markdown_document(
                    connection,
                    document,
                    output_root=output_root,
                    object_store=object_store,
                )
                record_publish_observation(connection, publish_run_id, published_version)
            except Exception as error:
                report.failures.append(f"{markdown_path}: {error}")
            else:
                report.published += 1
                if published_version.created:
                    report.created_versions += 1
                else:
                    report.reused_versions += 1

            if index % PUBLISH_LOG_INTERVAL == 0:
                _log(
                    log,
                    f"Scanned {index} Markdown files: {report.published} published, "
                    f"{report.created_versions} versions created, {report.reused_versions} reused, "
                    f"{len(report.failures)} failures",
                )

        finish_publish_run(connection, publish_run_id)
        connection.commit()

    return report


def publish_document_text_to_postgres(
    database_url: str,
    source_path: tuple[str, ...],
    xml_content: bytes,
    markdown: str,
    collection: str,
    snapshot_date: str | None,
    object_store_root: Path = DEFAULT_OBJECT_STORE_ROOT,
    object_store_bucket: str = "legislation",
) -> PublishedVersion:
    object_store = LocalObjectStore(root=object_store_root, bucket=object_store_bucket)
    with psycopg.connect(database_url) as connection:
        publish_run_id = create_publish_run(
            connection,
            collection=collection,
            snapshot_date=snapshot_date,
            legislation_types={source_path[0]} if source_path else set(),
        )
        published_version = publish_document_text(
            connection,
            source_path=source_path,
            xml_content=xml_content,
            markdown=markdown,
            collection=collection,
            snapshot_date=snapshot_date,
            object_store=object_store,
        )
        record_publish_observation(connection, publish_run_id, published_version)
        finish_publish_run(connection, publish_run_id)
        connection.commit()

    return published_version


def publish_document_text(
    connection: psycopg.Connection[Any],
    source_path: tuple[str, ...],
    xml_content: bytes,
    markdown: str,
    collection: str,
    snapshot_date: str | None,
    object_store: LocalObjectStore,
) -> PublishedVersion:
    _validate_collection(collection=collection, snapshot_date=snapshot_date)
    xml_key = source_xml_object_key(collection=collection, source_path=source_path, snapshot_date=snapshot_date)
    markdown_key = markdown_object_key(collection=collection, source_path=source_path, snapshot_date=snapshot_date)
    source_object = object_store.put_bytes(xml_content, key=xml_key, content_type="application/xml")
    markdown_object = object_store.put_text(markdown, key=markdown_key, content_type="text/markdown")
    ref = MarkdownDocumentRef(
        collection=collection,
        snapshot_date=snapshot_date,
        source_path=source_path,
        markdown_path=Path(markdown_key),
    )
    document = parse_markdown_document_text(ref, markdown)
    return upsert_postgres_stored_document(
        connection,
        document,
        markdown_object=markdown_object,
        source_object=source_object,
    )


def point_in_time_markdown_root(output_root: Path, at: str) -> Path:
    return output_root / "markdown" / "point-in-time" / at


def enacted_markdown_root(output_root: Path) -> Path:
    return output_root / "markdown" / "enacted"


def iter_markdown_paths(markdown_root: Path, legislation_types: set[str] | None = None) -> list[Path]:
    if legislation_types:
        paths: list[Path] = []
        for legislation_type in sorted(legislation_types):
            type_root = markdown_root / legislation_type
            if type_root.exists():
                paths.extend(type_root.rglob("*.md"))
        return sorted(paths)

    return sorted(markdown_root.rglob("*.md"))


def markdown_ref_from_path(
    markdown_path: Path,
    output_root: Path,
    collection: str,
    snapshot_date: str | None,
) -> MarkdownDocumentRef:
    base = output_root / "markdown" / collection
    if collection == "point-in-time":
        if snapshot_date is None:
            raise ValueError("Point-in-time Markdown requires a snapshot date.")
        base = base / snapshot_date

    try:
        relative_path = markdown_path.resolve().relative_to(base.resolve())
    except ValueError as error:
        raise ValueError(f"{markdown_path} is not under {base}") from error

    if relative_path.suffix != ".md":
        raise ValueError(f"{markdown_path} is not a Markdown file")

    source_path = (*relative_path.with_suffix("").parts,)
    if len(source_path) < 3:
        raise ValueError(f"{markdown_path} does not include type/year/number path parts")

    return MarkdownDocumentRef(
        collection=collection,
        snapshot_date=snapshot_date,
        source_path=source_path,
        markdown_path=markdown_path,
    )


def parse_markdown_document(ref: MarkdownDocumentRef) -> ParsedMarkdownDocument:
    markdown = normalize_markdown_text(ref.markdown_path.read_text())
    return parse_markdown_document_text(ref, markdown)


def parse_markdown_document_text(ref: MarkdownDocumentRef, markdown: str) -> ParsedMarkdownDocument:
    markdown = normalize_markdown_text(markdown)
    metadata, body = split_frontmatter(markdown)
    provisions = tuple(split_provisions(body))
    return ParsedMarkdownDocument(
        ref=ref,
        metadata=metadata,
        markdown=markdown,
        body_markdown=body,
        provisions=provisions,
    )


def split_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(markdown)
    if match is None:
        return {}, markdown

    metadata = yaml.safe_load(match.group(1)) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Markdown frontmatter is not a mapping")

    return metadata, markdown[match.end() :]


def normalize_markdown_text(markdown: str) -> str:
    return markdown.translate(WINDOWS_1252_CONTROL_CHARS)


def canonicalize_dated_uris(text: str) -> str:
    return DATED_LEGISLATION_URI_RE.sub(r"\1", text)


def canonical_markdown_sha256(markdown: str) -> str:
    return hashlib.sha256(canonicalize_dated_uris(normalize_markdown_text(markdown)).encode()).hexdigest()


def split_provisions(body_markdown: str) -> list[ProvisionRecord]:
    matches = list(SECTION_HEADING_RE.finditer(body_markdown))
    if not matches:
        text = markdown_to_text(body_markdown)
        return [
            ProvisionRecord(
                ordinal=1,
                heading="Document",
                number=None,
                anchor="document",
                markdown=body_markdown.strip(),
                text=text,
            )
        ]

    provisions: list[ProvisionRecord] = []
    for index, match in enumerate(matches, start=1):
        start = match.start()
        end = matches[index].start() if index < len(matches) else len(body_markdown)
        markdown = body_markdown[start:end].strip()
        heading = match.group(1).strip()
        extent_match = EXTENT_SUFFIX_RE.search(heading)
        provisions.append(
            ProvisionRecord(
                ordinal=index,
                heading=heading,
                number=_heading_number(heading),
                anchor=slugify(heading) or f"provision-{index}",
                markdown=markdown,
                text=markdown_to_text(markdown),
                extent=extent_match.group(1).strip() if extent_match else None,
            )
        )

    return provisions


def upsert_postgres_markdown_document(
    connection: psycopg.Connection[Any],
    document: ParsedMarkdownDocument,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    object_store: LocalObjectStore | None = None,
) -> PublishedVersion:
    ref = document.ref
    object_store = object_store or LocalObjectStore()
    markdown_object_key = _storage_key(ref.markdown_path, output_root=output_root)
    xml_path = source_xml_path_for_markdown_ref(ref, output_root=output_root)
    markdown_object = object_store.put_file(ref.markdown_path, key=markdown_object_key)
    source_object = None
    if xml_path.exists():
        source_object = object_store.put_file(xml_path, key=_storage_key(xml_path, output_root=output_root))

    return upsert_postgres_stored_document(
        connection,
        document,
        markdown_object=markdown_object,
        source_object=source_object,
    )


def upsert_postgres_stored_document(
    connection: psycopg.Connection[Any],
    document: ParsedMarkdownDocument,
    markdown_object: StoredObject,
    source_object: StoredObject | None,
) -> PublishedVersion:
    ref = document.ref
    calendar_year = int(ref.year) if ref.year and ref.year.isdigit() else None
    document_uri = document.document_uri or f"https://www.legislation.gov.uk/{ref.document_id}"
    version_kind = _postgres_version_kind(ref.collection)
    snapshot_date = ref.snapshot_date if version_kind == "point_in_time" else None
    source_uri = _source_uri(document)
    source_object_key = source_object.key if source_object is not None else None
    source_sha256 = source_object.sha256 if source_object is not None else document.content_hash
    canonical_sha256 = document.canonical_content_hash
    version_id = existing_content_version_id(
        connection,
        document_id=ref.document_id,
        version_kind=version_kind,
        canonical_sha256=canonical_sha256,
        source_sha256=source_sha256,
        markdown_sha256=document.content_hash,
    )
    created_version = version_id is None
    if version_id is None:
        version_id = available_version_id(connection, preferred_id=ref.version_id, content_hash=document.content_hash)
    else:
        connection.execute(
            "update document_versions set canonical_sha256 = %s where id = %s and canonical_sha256 is null",
            (canonical_sha256, version_id),
        )

    upsert_storage_object(connection, markdown_object, source_url=None)
    if source_object is not None:
        upsert_storage_object(connection, source_object, source_url=source_uri)

    connection.execute(
        """
        insert into documents (
            id, legislation_type, year, calendar_year, number, title, document_uri,
            status, extent, source_path, updated_at
        ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
        on conflict(id) do update set
            legislation_type = excluded.legislation_type,
            year = excluded.year,
            calendar_year = excluded.calendar_year,
            number = excluded.number,
            title = excluded.title,
            document_uri = excluded.document_uri,
            status = excluded.status,
            extent = excluded.extent,
            source_path = excluded.source_path,
            updated_at = now()
        """,
        (
            ref.document_id,
            ref.legislation_type,
            ref.year,
            calendar_year,
            ref.number,
            document.title,
            document_uri,
            document.status,
            document.extent,
            list(ref.source_path),
        ),
    )
    if created_version:
        connection.execute(
            """
            insert into document_versions (
                id, document_id, version_kind, snapshot_date, source_uri, source_object_key,
                markdown_object_key, source_sha256, markdown_sha256, canonical_sha256,
                word_count, is_metadata_only
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict(id) do update set
                source_uri = excluded.source_uri,
                source_object_key = excluded.source_object_key,
                markdown_object_key = excluded.markdown_object_key,
                source_sha256 = excluded.source_sha256,
                markdown_sha256 = excluded.markdown_sha256,
                canonical_sha256 = excluded.canonical_sha256,
                word_count = excluded.word_count,
                is_metadata_only = excluded.is_metadata_only
            """,
            (
                version_id,
                ref.document_id,
                version_kind,
                snapshot_date,
                source_uri,
                source_object_key,
                markdown_object.key,
                source_sha256,
                document.content_hash,
                canonical_sha256,
                document.word_count,
                document.is_metadata_only,
            ),
        )
    connection.execute(
        "update documents set latest_version_id = %s, updated_at = now() where id = %s",
        (version_id, ref.document_id),
    )

    insert_document_file(
        connection,
        document_id=ref.document_id,
        version_id=version_id,
        file_kind="markdown",
        object_key=markdown_object.key,
        sha256=document.content_hash,
        source_url=None,
        is_canonical=True,
    )
    if source_object_key is not None:
        insert_document_file(
            connection,
            document_id=ref.document_id,
            version_id=version_id,
            file_kind="clml_xml",
            object_key=source_object_key,
            sha256=source_sha256,
            source_url=source_uri,
            is_canonical=True,
        )
    for pdf_url in document.pdf_alternatives:
        insert_document_file(
            connection,
            document_id=ref.document_id,
            version_id=version_id,
            file_kind="pdf",
            object_key=None,
            sha256=None,
            source_url=pdf_url,
            is_canonical=False,
        )

    for provision in document.provisions:
        provision_id = f"{version_id}:provision:{provision.ordinal}"
        connection.execute(
            """
            insert into provisions (
                id, version_id, document_id, ordinal, provision_type, number,
                heading, anchor, text_sha256, extent
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict(id) do update set
                provision_type = excluded.provision_type,
                number = excluded.number,
                heading = excluded.heading,
                anchor = excluded.anchor,
                text_sha256 = excluded.text_sha256,
                extent = excluded.extent
            """,
            (
                provision_id,
                version_id,
                ref.document_id,
                provision.ordinal,
                _provision_type(provision),
                provision.number,
                provision.heading,
                provision.anchor,
                upsert_provision_text(connection, provision),
                provision.extent,
            ),
        )

    return PublishedVersion(
        document_id=ref.document_id,
        version_id=version_id,
        source_uri=source_uri,
        source_sha256=source_sha256,
        created=created_version,
    )


def create_publish_run(
    connection: psycopg.Connection[Any],
    collection: str,
    snapshot_date: str | None,
    legislation_types: set[str],
) -> int:
    notes = f"collection={collection}"
    if legislation_types:
        notes = f"{notes}; legislation_types={','.join(sorted(legislation_types))}"
    row = connection.execute(
        """
        insert into fetch_runs (mode, snapshot_date, notes)
        values ('publish', %s, %s)
        returning id
        """,
        (snapshot_date, notes),
    ).fetchone()
    if row is None:
        raise RuntimeError("Failed to create publish run.")
    return int(row[0])


def finish_publish_run(connection: psycopg.Connection[Any], publish_run_id: int) -> None:
    connection.execute(
        "update fetch_runs set finished_at = now() where id = %s",
        (publish_run_id,),
    )


def record_publish_observation(
    connection: psycopg.Connection[Any],
    publish_run_id: int,
    published_version: PublishedVersion,
) -> None:
    connection.execute(
        """
        insert into fetch_observations (
            fetch_run_id, document_id, version_id, source_url, status, source_sha256
        ) values (%s, %s, %s, %s, %s, %s)
        """,
        (
            publish_run_id,
            published_version.document_id,
            published_version.version_id,
            published_version.source_uri or published_version.document_id,
            "fetched" if published_version.created else "not_modified",
            published_version.source_sha256,
        ),
    )


def existing_content_version_id(
    connection: psycopg.Connection[Any],
    document_id: str,
    version_kind: str,
    canonical_sha256: str,
    source_sha256: str,
    markdown_sha256: str,
) -> str | None:
    # Match on the date-invariant canonical hash; rows published before the
    # canonical column existed fall back to the legacy exact-hash pair.
    row = connection.execute(
        """
        select id
        from document_versions
        where document_id = %s
          and version_kind = %s
          and (
            canonical_sha256 = %s
            or (canonical_sha256 is null and source_sha256 = %s and markdown_sha256 = %s)
          )
        order by created_at, id
        limit 1
        """,
        (document_id, version_kind, canonical_sha256, source_sha256, markdown_sha256),
    ).fetchone()
    return str(row[0]) if row is not None else None


def available_version_id(connection: psycopg.Connection[Any], preferred_id: str, content_hash: str) -> str:
    row = connection.execute("select 1 from document_versions where id = %s", (preferred_id,)).fetchone()
    if row is None:
        return preferred_id
    return f"{preferred_id}:{content_hash[:12]}"


def upsert_provision_text(connection: psycopg.Connection[Any], provision: ProvisionRecord) -> str:
    """Store a provision's text once, keyed by its hash, and return the key."""
    connection.execute(
        """
        insert into provision_texts (sha256, markdown, plain_text)
        values (%s, %s, %s)
        on conflict (sha256) do nothing
        """,
        (provision.text_sha256, provision.markdown, provision.text),
    )
    return provision.text_sha256


def upsert_storage_object(
    connection: psycopg.Connection[Any],
    stored_object: StoredObject,
    source_url: str | None,
) -> None:
    connection.execute(
        """
        insert into storage_objects (key, bucket, sha256, byte_size, content_type, source_url)
        values (%s, %s, %s, %s, %s, %s)
        on conflict(key) do update set
            sha256 = excluded.sha256,
            byte_size = excluded.byte_size,
            content_type = excluded.content_type,
            source_url = excluded.source_url
        """,
        (
            stored_object.key,
            stored_object.bucket,
            stored_object.sha256,
            stored_object.byte_size,
            stored_object.content_type,
            source_url,
        ),
    )


def insert_document_file(
    connection: psycopg.Connection[Any],
    document_id: str,
    version_id: str,
    file_kind: str,
    object_key: str | None,
    sha256: str | None,
    source_url: str | None,
    is_canonical: bool,
) -> None:
    connection.execute(
        """
        insert into document_files (
            document_id, version_id, file_kind, source_url, object_key, sha256, is_canonical
        )
        select %s, %s, %s, %s, %s, %s, %s
        where not exists (
            select 1
            from document_files
            where version_id = %s
              and file_kind = %s
              and coalesce(source_url, '') = coalesce(%s, '')
              and coalesce(object_key, '') = coalesce(%s, '')
        )
        """,
        (
            document_id,
            version_id,
            file_kind,
            source_url,
            object_key,
            sha256,
            is_canonical,
            version_id,
            file_kind,
            source_url,
            object_key,
        ),
    )


@dataclass
class VersionHashNormalizationReport:
    dry_run: bool = False
    backfill_scanned: int = 0
    backfilled: int = 0
    missing_markdown: int = 0
    duplicate_groups: int = 0
    merged_versions: int = 0


def backfill_canonical_hashes(
    connection: psycopg.Connection[Any],
    object_store: LocalObjectStore,
    report: VersionHashNormalizationReport,
    log: Callable[[str], None] | None = None,
    commit_interval: int = 5000,
) -> None:
    rows = connection.execute(
        """
        select id, markdown_object_key
        from document_versions
        where canonical_sha256 is null
        order by id
        """
    ).fetchall()
    _log(log, f"Backfilling canonical hashes for {len(rows)} versions")
    for version_id, markdown_object_key in rows:
        report.backfill_scanned += 1
        if not markdown_object_key or not object_store.exists(markdown_object_key):
            report.missing_markdown += 1
            continue
        canonical_sha256 = canonical_markdown_sha256(object_store.read_text(markdown_object_key))
        report.backfilled += 1
        if report.dry_run:
            continue
        connection.execute(
            "update document_versions set canonical_sha256 = %s where id = %s",
            (canonical_sha256, version_id),
        )
        if report.backfilled % commit_interval == 0:
            connection.commit()
            _log(log, f"Backfilled {report.backfilled} of {len(rows)} versions")
    if not report.dry_run:
        connection.commit()


def merge_duplicate_version_rows(
    connection: psycopg.Connection[Any],
    report: VersionHashNormalizationReport,
    log: Callable[[str], None] | None = None,
    commit_interval: int = 500,
) -> None:
    groups = connection.execute(
        """
        select document_id, version_kind, canonical_sha256,
               array_agg(id order by snapshot_date asc nulls last, created_at, id)
        from document_versions
        where canonical_sha256 is not null
        group by document_id, version_kind, canonical_sha256
        having count(*) > 1
        order by document_id
        """
    ).fetchall()
    _log(log, f"Found {len(groups)} duplicate version groups")
    for _document_id, _version_kind, _canonical_sha256, version_ids in groups:
        report.duplicate_groups += 1
        keeper_id, duplicate_ids = version_ids[0], version_ids[1:]
        report.merged_versions += len(duplicate_ids)
        if report.dry_run:
            continue
        for duplicate_id in duplicate_ids:
            # Move file links the keeper lacks; remaining duplicates and the
            # duplicate's provisions are removed by ON DELETE CASCADE below.
            connection.execute(
                """
                update document_files df set version_id = %s
                where df.version_id = %s
                  and not exists (
                    select 1 from document_files k
                    where k.version_id = %s
                      and k.file_kind = df.file_kind
                      and coalesce(k.source_url, '') = coalesce(df.source_url, '')
                      and coalesce(k.object_key, '') = coalesce(df.object_key, '')
                  )
                """,
                (keeper_id, duplicate_id, keeper_id),
            )
            connection.execute(
                "update fetch_observations set version_id = %s where version_id = %s",
                (keeper_id, duplicate_id),
            )
            connection.execute(
                "update documents set latest_version_id = %s where latest_version_id = %s",
                (keeper_id, duplicate_id),
            )
            connection.execute("delete from document_versions where id = %s", (duplicate_id,))
        if report.duplicate_groups % commit_interval == 0:
            connection.commit()
            _log(log, f"Merged {report.merged_versions} duplicate versions across {report.duplicate_groups} groups")
    if not report.dry_run:
        connection.commit()


@dataclass
class CompressionReport:
    scanned: int = 0
    compressed: int = 0
    already_compressed: int = 0
    missing_file: int = 0
    bytes_before: int = 0
    bytes_after: int = 0
    failures: list[str] = field(default_factory=list)


def compress_object_store(
    connection: psycopg.Connection[Any],
    object_store: LocalObjectStore,
    report: CompressionReport,
    limit: int | None = None,
    start_after: str | None = None,
    log: Callable[[str], None] | None = None,
    commit_interval: int = 500,
) -> str | None:
    """Gzip stored text objects in place, re-keying them to `.gz`.

    XML compresses about ten-fold, which is worth far more than the ~2% that
    deduplication could offer (whole-document objects embed their request date,
    so identical copies across snapshots are rare). The original is removed only
    after the compressed copy is written and verified to decode back to the same
    bytes. Returns the last key processed so an interrupted run can resume.
    """
    rows = connection.execute(
        f"""
        select key, content_type
        from storage_objects
        where key not like '%%.gz'
          and (%s::text is null or key > %s)
        order by key
        {"limit %s" if limit is not None else ""}
        """,  # noqa: S608 - limit clause is a fixed fragment; values are bound
        (start_after, start_after, limit) if limit is not None else (start_after, start_after),
    ).fetchall()
    _log(log, f"Compressing {len(rows)} candidate objects")

    last_key: str | None = None
    for key, content_type in rows:
        last_key = key
        report.scanned += 1
        resolved_type = content_type or guess_content_type(Path(key))
        if not is_compressible(resolved_type):
            report.already_compressed += 1
            continue

        source = object_store.path_for_key(key)
        if not source.exists():
            # Drained trees (PDFs, reports) live only in R2 by design.
            report.missing_file += 1
            continue

        try:
            original = source.read_bytes()
            stored = object_store.put_bytes(original, key=key, content_type=resolved_type)
            if object_store.read_bytes(stored.key) != original:
                raise ValueError("compressed object did not decode back to the original bytes")

            with connection.transaction():
                # storage_objects.key is referenced by two tables, so the new row
                # has to exist before the references move and the old row goes.
                connection.execute(
                    """
                    insert into storage_objects (key, bucket, sha256, byte_size, content_type, source_url)
                    select %s, bucket, sha256, %s, content_type, source_url
                    from storage_objects where key = %s
                    on conflict (key) do nothing
                    """,
                    (stored.key, stored.byte_size, key),
                )
                connection.execute(
                    "update document_versions set source_object_key = %s where source_object_key = %s",
                    (stored.key, key),
                )
                connection.execute(
                    "update document_versions set markdown_object_key = %s where markdown_object_key = %s",
                    (stored.key, key),
                )
                connection.execute(
                    "update document_files set object_key = %s where object_key = %s",
                    (stored.key, key),
                )
                connection.execute("delete from storage_objects where key = %s", (key,))
            source.unlink()
        except Exception as error:  # noqa: BLE001 - one bad object must not stop an overnight run
            report.failures.append(f"{key}: {error}")
            continue

        report.compressed += 1
        report.bytes_before += len(original)
        report.bytes_after += stored.byte_size
        if report.compressed % commit_interval == 0:
            connection.commit()
            saved = report.bytes_before - report.bytes_after
            _log(log, f"compressed {report.compressed} objects, saved {saved / 1e9:.2f} GB (last key {key})")

    connection.commit()
    return last_key


def render_compression_report(report: CompressionReport) -> str:
    ratio = report.bytes_before / report.bytes_after if report.bytes_after else 0
    lines = [
        f"Scanned {report.scanned}: compressed {report.compressed}, "
        f"{report.already_compressed} not compressible, {report.missing_file} not stored locally, "
        f"{len(report.failures)} failures",
        f"{report.bytes_before / 1e9:.2f} GB -> {report.bytes_after / 1e9:.2f} GB ({ratio:.1f}x)",
    ]
    lines.extend(f"- {failure}" for failure in report.failures[:20])
    return "\n".join(lines)


@dataclass
class RerenderReport:
    scanned: int = 0
    rerendered: int = 0
    unchanged: int = 0
    missing_xml: int = 0
    # Versions whose re-rendered text became identical to a sibling version;
    # normalize-version-hashes merges these afterwards.
    content_conflicts: int = 0
    failures: list[str] = field(default_factory=list)


def rerender_document_versions(
    connection: psycopg.Connection[Any],
    object_store: LocalObjectStore,
    document_id: str,
    report: RerenderReport,
    render: Callable[[bytes], str],
    log: Callable[[str], None] | None = None,
) -> None:
    """Re-render every stored version of a document with the current converter, in place.

    Rewrites the Markdown object under its existing key and refreshes the
    version row's hashes, word count, and provisions. Version identity and
    object keys are unchanged; run normalize-version-hashes afterwards to
    merge versions whose text became identical.
    """
    rows = connection.execute(
        """
        select dv.id, dv.version_kind, dv.snapshot_date, dv.source_object_key, dv.markdown_object_key,
               d.source_path
        from document_versions dv
        join documents d on d.id = dv.document_id
        where dv.document_id = %s and dv.source_object_key is not null and dv.markdown_object_key is not null
        order by dv.snapshot_date nulls first, dv.id
        """,
        (document_id,),
    ).fetchall()
    for version_id, version_kind, snapshot_date, source_key, markdown_key, source_path in rows:
        report.scanned += 1
        if not object_store.exists(source_key):
            report.missing_xml += 1
            continue
        try:
            markdown = render(object_store.read_bytes(source_key))
        except Exception as error:
            report.failures.append(f"{version_id}: {error}")
            continue

        ref = MarkdownDocumentRef(
            collection="point-in-time" if version_kind == "point_in_time" else "enacted",
            snapshot_date=snapshot_date.isoformat() if snapshot_date is not None else None,
            source_path=tuple(source_path),
            markdown_path=Path(markdown_key),
        )
        document = parse_markdown_document_text(ref, markdown)
        existing = connection.execute(
            "select markdown_sha256 from document_versions where id = %s", (version_id,)
        ).fetchone()
        if existing is not None and existing[0] == document.content_hash:
            report.unchanged += 1
            continue

        markdown_object = object_store.put_text(document.markdown, key=markdown_key, content_type="text/markdown")
        # A savepoint per version: re-rendering can make two versions of a
        # document identical (they differed only by text that is not in force,
        # or were rendered by different converter versions), which collides with
        # the content-uniqueness index. That is a merge for
        # normalize-version-hashes to resolve, not a reason to abort the run.
        try:
            with connection.transaction():
                _apply_rerendered_version(
                    connection,
                    document=document,
                    version_id=version_id,
                    document_id=document_id,
                    markdown_key=markdown_key,
                    markdown_object=markdown_object,
                )
        except psycopg.errors.UniqueViolation:
            report.content_conflicts += 1
            continue
        report.rerendered += 1
        if report.rerendered % 50 == 0:
            connection.commit()
            _log(log, f"Re-rendered {report.rerendered} versions ({report.scanned} scanned)")


def _apply_rerendered_version(
    connection: psycopg.Connection[Any],
    document: ParsedMarkdownDocument,
    version_id: str,
    document_id: str,
    markdown_key: str,
    markdown_object: StoredObject,
) -> None:
    upsert_storage_object(connection, markdown_object, source_url=None)
    connection.execute(
        """
        update document_versions
        set markdown_sha256 = %s, canonical_sha256 = %s, word_count = %s, is_metadata_only = %s
        where id = %s
        """,
        (
            document.content_hash,
            document.canonical_content_hash,
            document.word_count,
            document.is_metadata_only,
            version_id,
        ),
    )
    connection.execute(
        """
        update document_files set sha256 = %s
        where version_id = %s and file_kind = 'markdown' and object_key = %s
        """,
        (document.content_hash, version_id, markdown_key),
    )
    connection.execute("delete from provisions where version_id = %s", (version_id,))
    for provision in document.provisions:
        connection.execute(
            """
            insert into provisions (
                id, version_id, document_id, ordinal, provision_type, number,
                heading, anchor, text_sha256, extent
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                f"{version_id}:provision:{provision.ordinal}",
                version_id,
                document_id,
                provision.ordinal,
                _provision_type(provision),
                provision.number,
                provision.heading,
                provision.anchor,
                upsert_provision_text(connection, provision),
                provision.extent,
            ),
        )


def render_rerender_report(report: RerenderReport) -> str:
    lines = [
        f"Scanned {report.scanned} versions: re-rendered {report.rerendered}, "
        f"{report.unchanged} unchanged, {report.content_conflicts} now duplicate content, "
        f"{report.missing_xml} missing XML, {len(report.failures)} failures"
    ]
    lines.extend(f"- {failure}" for failure in report.failures[:20])
    return "\n".join(lines)


def render_version_hash_normalization_report(report: VersionHashNormalizationReport) -> str:
    action = "would backfill" if report.dry_run else "backfilled"
    merge_action = "would merge" if report.dry_run else "merged"
    return "\n".join(
        [
            f"Scanned {report.backfill_scanned} versions without a canonical hash: "
            f"{action} {report.backfilled}, {report.missing_markdown} missing local Markdown",
            f"Duplicate content groups: {report.duplicate_groups}; "
            f"{merge_action} {report.merged_versions} duplicate versions",
        ]
    )


def markdown_to_text(markdown: str) -> str:
    without_frontmatter = FRONTMATTER_RE.sub("", markdown, count=1)
    text = re.sub(r"```.*?```", " ", without_frontmatter, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~#>-]+", " ", text)
    return " ".join(text.split())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:120]


def render_publish_report(report: PublishReport) -> str:
    lines = [
        f"Published {report.published} Markdown documents to {report.database_path}",
        f"Created {report.created_versions} document versions; reused {report.reused_versions}",
        f"Scanned {report.scanned} files; {len(report.failures)} failures",
    ]
    if report.failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in report.failures[:20])
        if len(report.failures) > 20:
            lines.append(f"- ... {len(report.failures) - 20} more")
    return "\n".join(lines)


def source_xml_path_for_markdown_ref(ref: MarkdownDocumentRef, output_root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    if ref.collection == "enacted":
        return output_root / "xml" / "enacted" / Path(*ref.source_path) / "data.xml"
    if ref.snapshot_date is None:
        raise ValueError("Point-in-time Markdown requires a snapshot date.")
    return output_root / "xml" / "point-in-time" / ref.snapshot_date / Path(*ref.source_path) / "data.xml"


def source_xml_object_key(collection: str, source_path: tuple[str, ...], snapshot_date: str | None) -> str:
    if collection == "enacted":
        return (Path("xml") / "enacted" / Path(*source_path) / "data.xml").as_posix()
    if collection == "point-in-time":
        if snapshot_date is None:
            raise ValueError("Point-in-time XML objects require a snapshot date.")
        return (Path("xml") / "point-in-time" / snapshot_date / Path(*source_path) / "data.xml").as_posix()
    raise ValueError(f"Unknown collection: {collection}")


def markdown_object_key(collection: str, source_path: tuple[str, ...], snapshot_date: str | None) -> str:
    output_path = Path(*source_path[:-1]) / f"{source_path[-1]}.md"
    if collection == "enacted":
        return (Path("markdown") / "enacted" / output_path).as_posix()
    if collection == "point-in-time":
        if snapshot_date is None:
            raise ValueError("Point-in-time Markdown objects require a snapshot date.")
        return (Path("markdown") / "point-in-time" / snapshot_date / output_path).as_posix()
    raise ValueError(f"Unknown collection: {collection}")


def _validate_collection(collection: str, snapshot_date: str | None) -> None:
    if collection not in {"enacted", "point-in-time"}:
        raise ValueError(f"Unknown Markdown collection: {collection}")
    if collection == "point-in-time" and snapshot_date is None:
        raise ValueError("Point-in-time Markdown publishing requires a snapshot date.")
    if collection == "enacted" and snapshot_date is not None:
        raise ValueError("Enacted Markdown publishing cannot use a snapshot date.")


def _postgres_version_kind(collection: str) -> str:
    if collection == "enacted":
        return "enacted"
    if collection == "point-in-time":
        return "point_in_time"
    raise ValueError(f"Unknown Markdown collection: {collection}")


def _source_uri(document: ParsedMarkdownDocument) -> str | None:
    value = document.metadata.get("source_uri")
    if value:
        return str(value)
    if document.document_uri:
        return f"{document.document_uri.rstrip('/')}/data.xml"
    return None


def _storage_key(path: Path, output_root: Path = DEFAULT_OUTPUT_ROOT) -> str:
    try:
        return path.resolve().relative_to(output_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _provision_type(provision: ProvisionRecord) -> str:
    heading = provision.heading.lower()
    if heading.startswith("schedule"):
        return "schedule"
    if provision.number is not None:
        return "section"
    return "document"


def _heading_number(heading: str) -> str | None:
    # "SCHEDULE 5 Title" -> "5", so a schedule provision carries the number that
    # effects records reference ("Sch. 5 para. 3").
    schedule_match = SCHEDULE_HEADING_RE.match(heading)
    if schedule_match is not None:
        return schedule_match.group(1)
    match = re.match(r"^([A-Za-z]?\d+[A-Za-z]?|\([^)]+\))\b", heading)
    return match.group(1) if match else None


def _fallback_title(body_markdown: str) -> str | None:
    for line in body_markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _log(log: Callable[[str], None] | None, message: str) -> None:
    if log is not None:
        log(message)
