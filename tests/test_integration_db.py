"""Integration tests against a real PostgreSQL (Sprint 12, US12.2).

Each test creates its fixtures inside the db_connection transaction, which
is rolled back afterward -- so tests never leave state behind. Skipped when
SQLCOACH_TEST_DB_URL is unset.
"""

from __future__ import annotations

import pytest

from sqlcoach.database.explain_runner import ExplainRunner
from sqlcoach.database.index_catalog import fetch_index_usage, fetch_indexes
from sqlcoach.database.pg_stat_statements import (
    fetch_top_queries,
    is_pg_stat_statements_available,
)
from sqlcoach.exceptions import MutatingStatementError
from sqlcoach.parser.plan_json_parser import parse_explain_json

pytestmark = pytest.mark.integration


@pytest.fixture()
def seeded(db_connection):
    """A 5,000-row table with no index on email, plus a redundant and an
    unused index -- exercises EXPLAIN, catalog reads, and hygiene detection.
    """
    with db_connection.cursor() as cur:
        cur.execute("CREATE TABLE users (id serial PRIMARY KEY, email text, status int)")
        cur.execute(
            "INSERT INTO users (email, status) "
            "SELECT 'u' || g || '@x.com', g % 3 FROM generate_series(1, 5000) g"
        )
        cur.execute("CREATE INDEX idx_users_status ON users (status)")
        # Makes idx_users_status a prefix-redundant subset of this composite.
        cur.execute("CREATE INDEX idx_users_status_id ON users (status, id)")
        # Never scanned within this transaction.
        cur.execute("CREATE INDEX idx_users_unused ON users (email)")
        cur.execute("ANALYZE users")
    return db_connection


class TestExplainRunner:
    def test_explain_analyze_produces_a_plan_with_timing(self, seeded) -> None:
        raw = ExplainRunner().explain(
            seeded, "SELECT * FROM users WHERE email = 'u1@x.com'"
        )
        plan = parse_explain_json(raw)
        assert plan.execution_time_ms is not None  # ANALYZE actually ran
        assert plan.root.node_type

    def test_mutating_statement_is_blocked(self, seeded) -> None:
        with pytest.raises(MutatingStatementError):
            ExplainRunner().explain(seeded, "DELETE FROM users WHERE id = 1")

    def test_confirmed_mutation_runs_then_rolls_back(self, seeded) -> None:
        before = _count(seeded)
        ExplainRunner().explain(
            seeded, "DELETE FROM users WHERE id = 1", confirm_mutations=True
        )
        # The delete really executed inside the transaction; the fixture's
        # rollback undoes it afterward, leaving the DB clean.
        assert _count(seeded) == before - 1


class TestPgStatStatements:
    def test_extension_is_available(self, db_connection) -> None:
        assert is_pg_stat_statements_available(db_connection) is True

    def test_fetch_top_queries_returns_query_objects(self, seeded) -> None:
        with seeded.cursor() as cur:
            cur.execute("SELECT count(*) FROM users WHERE status = 1")
        queries = fetch_top_queries(seeded, limit=50)
        assert isinstance(queries, list)
        for query in queries[:5]:
            assert query.text


class TestIndexCatalog:
    def test_fetch_indexes_reads_ordered_columns_and_pk_flag(self, seeded) -> None:
        indexes = {i.name: i for i in fetch_indexes(seeded)}
        assert indexes["idx_users_status"].columns == ("status",)
        assert indexes["idx_users_status_id"].columns == ("status", "id")
        assert any(i.is_primary and i.table == "users" for i in indexes.values())

    def test_fetch_index_usage_reports_scan_counts(self, seeded) -> None:
        with seeded.cursor() as cur:
            cur.execute("SET enable_seqscan = off")
            cur.execute("SELECT id FROM users WHERE status = 1 LIMIT 1")
        usage = {u.name: u.scan_count for u in fetch_index_usage(seeded)}
        assert "idx_users_unused" in usage  # present, with its (zero) scan count


def _count(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM users")
        return cursor.fetchone()[0]