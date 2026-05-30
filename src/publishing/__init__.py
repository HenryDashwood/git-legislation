"""Publish converted legislation Markdown into queryable databases."""

import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import yaml

from object_store import DEFAULT_OBJECT_STORE_ROOT, LocalObjectStore, StoredObject

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"
PUBLISH_LOG_INTERVAL = 1000
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
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
        provisions.append(
            ProvisionRecord(
                ordinal=index,
                heading=heading,
                number=_heading_number(heading),
                anchor=slugify(heading) or f"provision-{index}",
                markdown=markdown,
                text=markdown_to_text(markdown),
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
    version_id = existing_content_version_id(
        connection,
        document_id=ref.document_id,
        version_kind=version_kind,
        source_sha256=source_sha256,
        markdown_sha256=document.content_hash,
    )
    created_version = version_id is None
    if version_id is None:
        version_id = available_version_id(connection, preferred_id=ref.version_id, content_hash=document.content_hash)

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
                markdown_object_key, source_sha256, markdown_sha256, word_count, is_metadata_only
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict(id) do update set
                source_uri = excluded.source_uri,
                source_object_key = excluded.source_object_key,
                markdown_object_key = excluded.markdown_object_key,
                source_sha256 = excluded.source_sha256,
                markdown_sha256 = excluded.markdown_sha256,
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
                heading, anchor, markdown, plain_text
            ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict(id) do update set
                provision_type = excluded.provision_type,
                number = excluded.number,
                heading = excluded.heading,
                anchor = excluded.anchor,
                markdown = excluded.markdown,
                plain_text = excluded.plain_text
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
                provision.markdown,
                provision.text,
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
    source_sha256: str,
    markdown_sha256: str,
) -> str | None:
    row = connection.execute(
        """
        select id
        from document_versions
        where document_id = %s
          and version_kind = %s
          and source_sha256 = %s
          and markdown_sha256 = %s
        order by created_at, id
        limit 1
        """,
        (document_id, version_kind, source_sha256, markdown_sha256),
    ).fetchone()
    return str(row[0]) if row is not None else None


def available_version_id(connection: psycopg.Connection[Any], preferred_id: str, content_hash: str) -> str:
    row = connection.execute("select 1 from document_versions where id = %s", (preferred_id,)).fetchone()
    if row is None:
        return preferred_id
    return f"{preferred_id}:{content_hash[:12]}"


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
