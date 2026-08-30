"""pg_stat_statements integration.

Reads workload-level query statistics from the `pg_stat_statements`
extension when it's enabled, without re-executing any queries
(FR-3.3). Treated as optional throughout: a database without the
extension enabled degrades gracefully rather than raising, per the
program-level risk noted in requirements.md ("pg_stat_statements may
not be enabled on target databases").

Assumes PostgreSQL 13+ column names (total_exec_time/mean_exec_time,
introduced in PG13; earlier versions used total_time/mean_time).
"""

from __future__ import annotations

import logging
from typing import Optional

import psycopg
import sqlglot
from sqlglot.errors import ParseError as SqlglotParseError

from sqlcoach.exceptions import DatabaseConnectionError
from sqlcoach.models.query import Query, QuerySource
from sqlcoach.parser.sql_ast_utils import extract_tables, statement_type

logger = logging.getLogger(__name__)

_DIALECT = "postgres"
DEFAULT_TOP_N_LIMIT = 50


def is_pg_stat_statements_available(connection: psycopg.Connection) -> bool:
    """Return True if the pg_stat_statements extension is installed on
    the connected database.

    Raises:
        DatabaseConnectionError: If the catalog check itself fails
            (e.g. connection dropped mid-query).
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_extension WHERE extname = %s",
                ("pg_stat_statements",),
            )
            return cursor.fetchone() is not None
    except psycopg.Error as exc:
        raise DatabaseConnectionError(
            "Could not check pg_stat_statements availability",
            details={"reason": str(exc)},
        ) from exc


def _try_enrich_with_parse(sql_text: str) -> tuple[Optional[str], tuple[str, ...]]:
    """Best-effort statement_type/referenced_tables extraction, mirroring
    LogParser's approach: a parse failure here (e.g. pg_stat_statements'
    normalized query text using unusual placeholder syntax) is a minor
    enrichment miss, not something that should block the row.
    """
    try:
        statement = sqlglot.parse_one(sql_text, read=_DIALECT)
    except SqlglotParseError:
        return None, ()
    return statement_type(statement), extract_tables(statement)


def fetch_top_queries(
    connection: psycopg.Connection, *, limit: int = DEFAULT_TOP_N_LIMIT
) -> list[Query]:
    """Fetch the top `limit` queries by total execution time from
    pg_stat_statements, mapped to Query objects.

    Returns an empty list -- rather than raising -- if the extension
    is not enabled, since this is documented as an optional (SHOULD)
    capability the tool must degrade gracefully without.

    Args:
        connection: An open connection, e.g. from
            `DatabaseConnection.__enter__()`.
        limit: Maximum number of rows to fetch (NFR-3.3.1). Must be
            at least 1.

    Raises:
        ValueError: If `limit` is less than 1.
        DatabaseConnectionError: If the query fails for a reason other
            than the extension being absent (e.g. insufficient
            privileges).
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1 (got {limit})")

    if not is_pg_stat_statements_available(connection):
        logger.warning(
            "pg_stat_statements extension is not enabled on this database; "
            "skipping workload statistics and falling back to plan-only analysis"
        )
        return []

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT query, calls, total_exec_time, mean_exec_time
                FROM pg_stat_statements
                ORDER BY total_exec_time DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cursor.fetchall()
    except psycopg.Error as exc:
        raise DatabaseConnectionError(
            "Failed to query pg_stat_statements",
            details={"reason": str(exc)},
        ) from exc

    queries: list[Query] = []
    for query_text, calls, _total_exec_time, mean_exec_time in rows:
        if not query_text or not query_text.strip():
            logger.debug("Skipping pg_stat_statements row with empty query text")
            continue
        resolved_statement_type, referenced_tables = _try_enrich_with_parse(query_text)
        queries.append(
            Query(
                text=query_text,
                source=QuerySource.PG_STAT_STATEMENTS,
                execution_time_ms=mean_exec_time,
                call_count=calls,
                statement_type=resolved_statement_type,
                referenced_tables=referenced_tables,
            )
        )
    return queries