"""EXPLAIN ANALYZE execution.

Runs `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` against a live
PostgreSQL connection (FR-3.2.1), guarding against accidentally
executing a mutating statement for real (FR-3.2.2) -- per the
program-level risk noted in requirements.md: "EXPLAIN ANALYZE executes
queries for real, which can be dangerous on production data for
write-heavy statements."
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
import sqlglot
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.exceptions import DatabaseConnectionError, MutatingStatementError

logger = logging.getLogger(__name__)

_DIALECT = "postgres"
_READ_ONLY_STATEMENT_TYPES = frozenset({"SELECT", "UNION", "INTERSECT", "EXCEPT"})
DEFAULT_STATEMENT_TIMEOUT_SECONDS = 30


def is_mutating_statement(sql: str) -> bool:
    """Return True if `sql` is anything other than a recognized
    read-only query.

    Deliberately an allowlist, not a denylist: only statement types
    positively identified as read-only (SELECT and set operations over
    SELECTs) are treated as safe. Everything else -- INSERT/UPDATE/
    DELETE, DDL, unsupported syntax that sqlglot falls back to a
    generic "Command" node for, and outright unparseable text -- is
    conservatively treated as mutating. A denylist of "known mutating
    types" was tried first and rejected: sqlglot's lenient grammar can
    silently reinterpret garbled SQL as some other valid-looking
    expression type that a denylist wouldn't recognize, which would
    have let unrecognized input through as a false "safe".
    """
    try:
        statement = sqlglot.parse_one(sql, read=_DIALECT)
    except SqlglotParseError:
        return True
    return type(statement).__name__.upper() not in _READ_ONLY_STATEMENT_TYPES


class ExplainRunner:
    """Executes EXPLAIN ANALYZE against a live PostgreSQL connection.

    A single instance can be reused across multiple `explain()` calls
    against the same `psycopg.Connection` (NFR-3.2.2) -- the connection
    itself is supplied per call rather than owned by this class, so
    callers control connection lifecycle via Sprint 2's
    `DatabaseConnection` context manager.
    """

    def __init__(
        self, statement_timeout_seconds: int = DEFAULT_STATEMENT_TIMEOUT_SECONDS
    ) -> None:
        self._statement_timeout_seconds = statement_timeout_seconds

    def explain(
        self,
        connection: psycopg.Connection,
        sql: str,
        *,
        confirm_mutations: bool = False,
    ) -> list[dict[str, Any]]:
        """Run EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) for `sql`.

        Args:
            connection: An open connection, e.g. from
                `DatabaseConnection.__enter__()`.
            sql: The statement to explain.
            confirm_mutations: Must be True to allow EXPLAIN ANALYZE to
                run against a statement detected as mutating
                (FR-3.2.2). Defaults to False (blocked).

        Returns:
            The parsed JSON payload from Postgres (a list containing
            one dict with "Plan", "Planning Time", and "Execution
            Time" keys) -- psycopg3 decodes the `json` column
            automatically, so no manual `json.loads()` is needed.

        Raises:
            MutatingStatementError: If `sql` is a mutating statement
                and `confirm_mutations` is not True. Nothing is
                executed against the database in this case.
            DatabaseConnectionError: If execution fails for any
                database-level reason.
        """
        if is_mutating_statement(sql) and not confirm_mutations:
            raise MutatingStatementError(
                "Refusing to run EXPLAIN ANALYZE on a statement that appears to "
                "modify data; pass confirm_mutations=True (CLI: --confirm-mutations) "
                "to proceed anyway.",
                details={"sql": sql},
            )

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SET statement_timeout = {self._statement_timeout_seconds * 1000}"
                )
                cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}")
                row = cursor.fetchone()
        except psycopg.Error as exc:
            raise DatabaseConnectionError(
                "EXPLAIN ANALYZE execution failed",
                details={"reason": str(exc)},
            ) from exc

        if row is None:
            raise DatabaseConnectionError("EXPLAIN ANALYZE returned no result")

        return row[0]