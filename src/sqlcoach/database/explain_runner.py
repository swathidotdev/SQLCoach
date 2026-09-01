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
from sqlglot import exp
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.exceptions import (
    DatabaseConnectionError,
    MutatingStatementError,
    ValidationError,
)
from sqlcoach.parser.sql_ast_utils import DIALECT

logger = logging.getLogger(__name__)

_READ_ONLY_STATEMENT_TYPES = frozenset({"SELECT", "UNION", "INTERSECT", "EXCEPT"})

#: Node types that write data wherever they appear in the tree. A
#: statement whose *root* is a harmless SELECT can still contain one of
#: these in a data-modifying CTE, e.g.
#: ``WITH d AS (DELETE FROM t RETURNING *) SELECT * FROM d`` -- which
#: PostgreSQL executes for real under EXPLAIN ANALYZE.
_WRITE_NODE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
)

DEFAULT_STATEMENT_TIMEOUT_SECONDS = 30


def is_mutating_statement(sql: str) -> bool:
    """Return True if `sql` is anything other than a provably read-only query.

    Two independent checks must both pass for a statement to be
    treated as safe:

    1. The root node type is on the read-only allowlist (SELECT and
       set operations over SELECTs). This is deliberately an allowlist,
       not a denylist: INSERT/UPDATE/DELETE, DDL, unsupported syntax
       that sqlglot falls back to a generic node for, and outright
       unparseable text are all conservatively treated as mutating. A
       denylist of "known mutating types" was tried first and
       rejected -- sqlglot's lenient grammar can silently reinterpret
       garbled SQL as some other valid-looking expression type that a
       denylist wouldn't recognize, letting unrecognized input through
       as a false "safe".
    2. No write node appears anywhere in the tree, and the statement
       takes no row locks. A root-type check alone is not sufficient:
       a data-modifying CTE parses as a `Select`, and
       ``SELECT ... FOR UPDATE`` locks rows for the duration of the
       transaction. Both are blocked by default.

    Note that this cannot detect a volatile function that writes as a
    side effect (``SELECT my_writing_function()``) -- no static check
    can. The confirmation gate remains the backstop for that case.
    """
    try:
        statement = sqlglot.parse_one(sql, read=DIALECT)
    except SqlglotParseError:
        return True

    if statement is None:
        return True

    if type(statement).__name__.upper() not in _READ_ONLY_STATEMENT_TYPES:
        return True

    if any(True for _ in statement.find_all(*_WRITE_NODE_TYPES)):
        return True

    return any(True for _ in statement.find_all(exp.Lock))


class ExplainRunner:
    """Executes EXPLAIN ANALYZE against a live PostgreSQL connection.

    A single instance can be reused across multiple `explain()` calls
    against the same `psycopg.Connection` (NFR-3.2.2) -- the connection
    itself is supplied per call rather than owned by this class, so
    callers control connection lifecycle via Sprint 2's
    `DatabaseConnection` context manager.

    Transaction semantics: this class never commits. psycopg3 opens an
    implicit transaction on first execute, so when the caller closes
    the connection without committing, any write performed by a
    confirmed mutating statement is rolled back. That is a useful
    safety net, but it is the *caller's* transaction -- a caller that
    commits for its own reasons will make those writes permanent.
    """

    def __init__(
        self, statement_timeout_seconds: int = DEFAULT_STATEMENT_TIMEOUT_SECONDS
    ) -> None:
        if statement_timeout_seconds < 1:
            # PostgreSQL reads `statement_timeout = 0` as "no timeout",
            # the exact opposite of what passing 0 here would imply.
            raise ValidationError(
                "statement_timeout_seconds must be at least 1 second",
                details={"statement_timeout_seconds": statement_timeout_seconds},
            )
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
                "modify data or take row locks; pass confirm_mutations=True "
                "(CLI: --confirm-mutations) to proceed anyway.",
                details={"sql": sql},
            )

        if confirm_mutations:
            logger.warning(
                "Running EXPLAIN ANALYZE with mutations confirmed; any writes will "
                "execute for real unless the surrounding transaction is rolled back"
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