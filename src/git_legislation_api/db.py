"""Database pool wiring for the read API."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def create_pool(database_url: str) -> ConnectionPool:
    return ConnectionPool(
        database_url,
        kwargs={"row_factory": dict_row},
        open=False,
    )


@contextmanager
def connection_from_pool(pool: ConnectionPool) -> Iterator[psycopg.Connection[Any]]:
    with pool.connection() as connection:
        yield connection
