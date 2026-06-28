"""Read-only SQL repository for the API."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, LiteralString

import psycopg
from psycopg import sql

ConnectionFactory = Callable[[], AbstractContextManager[psycopg.Connection[Any]]]
ApiQuery = LiteralString | bytes | sql.SQL | sql.Composed


class PostgresRepository:
    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self.connection_factory = connection_factory

    def list_documents(
        self,
        *,
        legislation_type: str | None,
        year: int | None,
        q: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        clauses = [sql.SQL("1 = 1")]
        params: list[Any] = []
        if legislation_type is not None:
            clauses.append(sql.SQL("legislation_type = %s"))
            params.append(legislation_type)
        if year is not None:
            clauses.append(sql.SQL("calendar_year = %s"))
            params.append(year)
        if q is not None:
            clauses.append(sql.SQL("title ilike %s"))
            params.append(f"%{q}%")
        params.extend([limit, offset])
        query = sql.SQL("""
            select
                id,
                legislation_type,
                year,
                calendar_year,
                number,
                title,
                document_uri,
                status,
                extent,
                latest_version_id,
                created_at,
                updated_at
            from documents
            where {}
            order by calendar_year nulls last, legislation_type, number, id
            limit %s offset %s
        """).format(sql.SQL(" and ").join(clauses))
        with self.connection_factory() as connection:
            return _fetch_all(connection, query, params)

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connection_factory() as connection:
            document = _fetch_one(
                connection,
                """
                select
                    id,
                    legislation_type,
                    year,
                    calendar_year,
                    number,
                    title,
                    document_uri,
                    status,
                    extent,
                    latest_version_id,
                    created_at,
                    updated_at
                from documents
                where id = %s
                """,
                [document_id],
            )
            if document is None:
                return None
            document["latest_version"] = (
                self._get_version_with_connection(connection, str(document["latest_version_id"]))
                if document.get("latest_version_id") is not None
                else None
            )
            return document

    def list_versions(self, document_id: str) -> list[dict[str, Any]]:
        with self.connection_factory() as connection:
            return _fetch_all(
                connection,
                """
                select
                    id,
                    document_id,
                    version_kind,
                    snapshot_date,
                    source_uri,
                    source_object_key,
                    markdown_object_key,
                    word_count,
                    is_metadata_only,
                    created_at
                from document_versions
                where document_id = %s
                order by version_kind, snapshot_date nulls first, created_at, id
                """,
                [document_id],
            )

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        with self.connection_factory() as connection:
            return self._get_version_with_connection(connection, version_id)

    def list_provisions(self, version_id: str) -> list[dict[str, Any]]:
        with self.connection_factory() as connection:
            return _fetch_all(
                connection,
                """
                select
                    id,
                    version_id,
                    document_id,
                    ordinal,
                    provision_type,
                    number,
                    heading,
                    anchor
                from provisions
                where version_id = %s
                order by ordinal
                """,
                [version_id],
            )

    def get_provision(self, version_id: str, anchor: str) -> dict[str, Any] | None:
        with self.connection_factory() as connection:
            return _fetch_one(
                connection,
                """
                select
                    id,
                    version_id,
                    document_id,
                    ordinal,
                    provision_type,
                    number,
                    heading,
                    anchor,
                    markdown,
                    plain_text
                from provisions
                where version_id = %s and anchor = %s
                """,
                [version_id, anchor],
            )

    def list_files(self, version_id: str) -> list[dict[str, Any]]:
        with self.connection_factory() as connection:
            return _fetch_all(connection, _files_sql(sql.SQL("df.version_id = %s")), [version_id])

    def get_canonical_file(self, version_id: str, file_kind: str) -> dict[str, Any] | None:
        with self.connection_factory() as connection:
            return _fetch_one(
                connection,
                _files_sql(sql.SQL("df.version_id = %s and df.file_kind = %s and df.is_canonical = true")),
                [version_id, file_kind],
            )

    def _get_version_with_connection(
        self,
        connection: psycopg.Connection[Any],
        version_id: str,
    ) -> dict[str, Any] | None:
        return _fetch_one(
            connection,
            """
            select
                id,
                document_id,
                version_kind,
                snapshot_date,
                source_uri,
                source_object_key,
                markdown_object_key,
                word_count,
                is_metadata_only,
                created_at
            from document_versions
            where id = %s
            """,
            [version_id],
        )


def _files_sql(where_clause: sql.SQL) -> sql.Composed:
    return sql.SQL("""
        select
            df.id,
            df.document_id,
            df.version_id,
            df.file_kind,
            df.source_url,
            df.object_key,
            df.sha256,
            df.is_canonical,
            df.created_at,
            so.bucket,
            so.byte_size,
            so.content_type,
            so.sha256 as object_sha256
        from document_files df
        left join storage_objects so on so.key = df.object_key
        where {}
        order by df.is_canonical desc, df.file_kind, df.id
    """).format(where_clause)


def _fetch_one(connection: psycopg.Connection[Any], query: ApiQuery, params: list[Any]) -> dict[str, Any] | None:
    row = connection.execute(query, params).fetchone()
    return dict(row) if row is not None else None


def _fetch_all(connection: psycopg.Connection[Any], query: ApiQuery, params: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, params).fetchall()]
