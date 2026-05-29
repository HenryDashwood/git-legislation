"""Publish converted legislation Markdown into queryable databases."""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"
PUBLISH_LOG_INTERVAL = 500
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


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
    failures: list[str] = field(default_factory=list)
    database_path: str | None = None


def publish_markdown_to_sqlite(
    markdown_root: Path,
    database_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    collection: str = "point-in-time",
    snapshot_date: str | None = None,
    legislation_types: Iterable[str] | None = None,
    reset: bool = False,
    log: Callable[[str], None] | None = None,
) -> PublishReport:
    if collection not in {"enacted", "point-in-time"}:
        raise ValueError(f"Unknown Markdown collection: {collection}")
    if collection == "point-in-time" and snapshot_date is None:
        raise ValueError("Point-in-time Markdown publishing requires a snapshot date.")
    if collection == "enacted" and snapshot_date is not None:
        raise ValueError("Enacted Markdown publishing cannot use a snapshot date.")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    report = PublishReport(collection=collection, snapshot_date=snapshot_date, database_path=str(database_path))
    selected_types = set(legislation_types or [])

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        if reset:
            drop_sqlite_schema(connection)
        create_sqlite_schema(connection)

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
                upsert_markdown_document(connection, document)
            except Exception as error:
                report.failures.append(f"{markdown_path}: {error}")
            else:
                report.published += 1

            if index % PUBLISH_LOG_INTERVAL == 0:
                _log(
                    log,
                    f"Scanned {index} Markdown files: {report.published} published, {len(report.failures)} failures",
                )

        connection.commit()

    return report


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


def default_sqlite_database_path(output_root: Path) -> Path:
    return output_root / "publish" / "legislation.sqlite"


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
    markdown = ref.markdown_path.read_text()
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


def upsert_markdown_document(connection: sqlite3.Connection, document: ParsedMarkdownDocument) -> None:
    ref = document.ref
    source_path_json = json.dumps(list(ref.source_path))
    calendar_year = int(ref.year) if ref.year and ref.year.isdigit() else None

    connection.execute(
        """
        insert into documents (
            id, legislation_type, year, calendar_year, number, title, document_uri, status, extent, source_path_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
            legislation_type = excluded.legislation_type,
            year = excluded.year,
            calendar_year = excluded.calendar_year,
            number = excluded.number,
            title = excluded.title,
            document_uri = excluded.document_uri,
            status = excluded.status,
            extent = excluded.extent,
            source_path_json = excluded.source_path_json
        """,
        (
            ref.document_id,
            ref.legislation_type,
            ref.year,
            calendar_year,
            ref.number,
            document.title,
            document.document_uri,
            document.status,
            document.extent,
            source_path_json,
        ),
    )
    connection.execute("delete from provisions where version_id = ?", (ref.version_id,))
    connection.execute("delete from provision_search where version_id = ?", (ref.version_id,))
    connection.execute(
        """
        insert into versions (
            id, document_id, collection, snapshot_date, markdown_path, content_hash, word_count,
            is_metadata_only, pdf_alternatives_json, body_markdown
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
            markdown_path = excluded.markdown_path,
            content_hash = excluded.content_hash,
            word_count = excluded.word_count,
            is_metadata_only = excluded.is_metadata_only,
            pdf_alternatives_json = excluded.pdf_alternatives_json,
            body_markdown = excluded.body_markdown
        """,
        (
            ref.version_id,
            ref.document_id,
            ref.collection,
            ref.snapshot_date,
            str(ref.markdown_path),
            document.content_hash,
            document.word_count,
            int(document.is_metadata_only),
            json.dumps(list(document.pdf_alternatives)),
            document.body_markdown,
        ),
    )

    for provision in document.provisions:
        provision_id = f"{ref.version_id}:provision:{provision.ordinal}"
        connection.execute(
            """
            insert into provisions (
                id, version_id, document_id, ordinal, heading, number, anchor, markdown, text
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                provision_id,
                ref.version_id,
                ref.document_id,
                provision.ordinal,
                provision.heading,
                provision.number,
                provision.anchor,
                provision.markdown,
                provision.text,
            ),
        )
        connection.execute(
            """
            insert into provision_search (
                provision_id, version_id, document_id, title, heading, text
            ) values (?, ?, ?, ?, ?, ?)
            """,
            (provision_id, ref.version_id, ref.document_id, document.title, provision.heading, provision.text),
        )


def create_sqlite_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        pragma foreign_keys = on;

        create table if not exists documents (
            id text primary key,
            legislation_type text not null,
            year text,
            calendar_year integer,
            number text not null,
            title text not null,
            document_uri text,
            status text,
            extent text,
            source_path_json text not null
        );

        create table if not exists versions (
            id text primary key,
            document_id text not null references documents(id) on delete cascade,
            collection text not null,
            snapshot_date text,
            markdown_path text not null,
            content_hash text not null,
            word_count integer not null,
            is_metadata_only integer not null default 0,
            pdf_alternatives_json text not null default '[]',
            body_markdown text not null
        );

        create table if not exists provisions (
            id text primary key,
            version_id text not null references versions(id) on delete cascade,
            document_id text not null references documents(id) on delete cascade,
            ordinal integer not null,
            heading text not null,
            number text,
            anchor text not null,
            markdown text not null,
            text text not null
        );

        create index if not exists documents_type_year_idx on documents(legislation_type, calendar_year, number);
        create index if not exists versions_document_idx on versions(document_id, collection, snapshot_date);
        create index if not exists provisions_version_idx on provisions(version_id, ordinal);
        """
    )
    connection.execute(
        """
        create virtual table if not exists provision_search using fts5(
            provision_id unindexed,
            version_id unindexed,
            document_id unindexed,
            title,
            heading,
            text
        )
        """
    )


def drop_sqlite_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        drop table if exists provision_search;
        drop table if exists provisions;
        drop table if exists versions;
        drop table if exists documents;
        """
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
        f"Scanned {report.scanned} files; {len(report.failures)} failures",
    ]
    if report.failures:
        lines.append("Failures:")
        lines.extend(f"- {failure}" for failure in report.failures[:20])
        if len(report.failures) > 20:
            lines.append(f"- ... {len(report.failures) - 20} more")
    return "\n".join(lines)


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
