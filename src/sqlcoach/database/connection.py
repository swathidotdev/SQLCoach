"""Database connection layer.

Wraps psycopg3 with a small, repository-friendly interface so the
analyzer, advisor, and CLI layers never need to import psycopg
themselves (FR-2.6). Connection failures are always raised as
DatabaseConnectionError, never a raw psycopg exception (FR-2.7).

Credential redaction for logging is deliberately out of scope here --
it is delivered as its own story (US2.5) since it touches the logging
layer as much as this one.
"""

from __future__ import annotations

from types import TracebackType
from typing import Optional

import psycopg

from sqlcoach.exceptions import DatabaseConnectionError

DEFAULT_CONNECT_TIMEOUT_SECONDS = 10
DEFAULT_PORT = 5432


class DatabaseConnection:
    """A managed PostgreSQL connection usable as a context manager.

    Construct with either a full DSN string, or discrete connection
    parameters (host/port/user/password/dbname). Exactly one of `dsn`
    or `host` must be provided.

    Example:
        with DatabaseConnection(dsn="postgresql://user@localhost/mydb") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

        with DatabaseConnection(host="localhost", dbname="mydb", user="alice") as conn:
            ...
    """

    def __init__(
        self,
        *,
        dsn: Optional[str] = None,
        host: Optional[str] = None,
        port: int = DEFAULT_PORT,
        user: Optional[str] = None,
        password: Optional[str] = None,
        dbname: Optional[str] = None,
        sslmode: Optional[str] = None,
        connect_timeout_seconds: int = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        if bool(dsn) == bool(host):
            raise ValueError(
                "Provide exactly one of `dsn` or `host` (with discrete params), not both or neither."
            )

        self._connect_kwargs: dict[str, object]
        if dsn is not None:
            self._connect_kwargs = {
                "conninfo": dsn,
                "connect_timeout": connect_timeout_seconds,
            }
        else:
            self._connect_kwargs = {
                "host": host,
                "port": port,
                "user": user,
                "password": password,
                "dbname": dbname,
                "connect_timeout": connect_timeout_seconds,
            }
            if sslmode is not None:
                self._connect_kwargs["sslmode"] = sslmode

        self._connection: Optional[psycopg.Connection] = None

    def __enter__(self) -> psycopg.Connection:
        try:
            self._connection = psycopg.connect(**self._connect_kwargs)
        except psycopg.Error as exc:
            raise DatabaseConnectionError(
                "Could not connect to PostgreSQL",
                details={"reason": str(exc)},
            ) from exc
        return self._connection

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None