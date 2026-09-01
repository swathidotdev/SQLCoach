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

import psycopg

from sqlcoach.exceptions import DatabaseConnectionError, ValidationError
from sqlcoach.models.query import Query, QuerySource
from sqlcoach.parser.sql_ast_utils import describe_sql

logger = logging.getLogger(__name__)

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


def fetch_top_queries(
    connection: psycopg.Connection, *, limit: int = DEFAULT_TOP_N_LIMIT
) -> list[Query]:
    """Fetch the top `limit` queries by total execution time from
    pg_stat_statements, mapped to Query objects.

    Both timing figures are preserved: `mean_exec_time` becomes
    `Query.execution_time_ms` (cost of one execution) and
    `total_exec_time` becomes `Query.total_execution_time_ms` (cost to
    the workload as a whole). The latter is the ranking key here, and
    is what impact estimation should prioritize by -- a cheap query
    called constantly can dominate a database's total load.

    Returns an empty list -- rather than raising -- if the extension
    is not enabled, since this is documented as an optional (SHOULD)
    capability the tool must degrade gracefully without.

    Args:
        connection: An open connection, e.g. from
            `DatabaseConnection.__enter__()`.
        limit: Maximum number of rows to fetch (NFR-3.3.1). Must be
            at least 1.

    Raises:
        ValidationError: If `limit` is less than 1.
        DatabaseConnectionError: If the query fails for a reason other
            than the extension being absent (e.g. insufficient
            privileges).
    """
    if limit < 1:
        raise ValidationError(
            "limit must be at least 1",
            details={"limit": limit},
        )

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
    for query_text, calls, total_exec_time, mean_exec_time in rows:
        if not query_text or not query_text.strip():
            logger.debug("Skipping pg_stat_statements row with empty query text")
            continue
        if calls is None or calls < 1:
            # Defensive: a statistics reset racing this read can in
            # principle surface a row with no recorded calls, which
            # would fail Query's call_count >= 1 validation and leak a
            # raw pydantic error out of the database layer.
            logger.debug(
                "Skipping pg_stat_statements row with non-positive call count %r", calls
            )
            continue
        metadata = describe_sql(query_text)
        queries.append(
            Query(
                text=query_text,
                normalized_text=metadata.normalized_text,
                source=QuerySource.PG_STAT_STATEMENTS,
                execution_time_ms=mean_exec_time,
                total_execution_time_ms=total_exec_time,
                call_count=calls,
                statement_type=metadata.statement_type,
                referenced_tables=metadata.referenced_tables,
            )
        )
    return queries