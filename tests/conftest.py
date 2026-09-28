"""Shared pytest fixtures and markers for SQLCoach's test suite.

Integration tests connect to a real PostgreSQL only when
SQLCOACH_TEST_DB_URL is set; otherwise they skip, so the default unit
run stays green and network-free (NFR-5.1). Performance tests run only
when SQLCOACH_RUN_PERF is set.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_DB_URL_ENV = "SQLCOACH_TEST_DB_URL"
_PERF_ENV = "SQLCOACH_RUN_PERF"


def _test_db_url() -> str | None:
    return os.environ.get(_DB_URL_ENV)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip marked tests when their prerequisites aren't present."""
    db_url = _test_db_url()
    run_perf = os.environ.get(_PERF_ENV)

    skip_integration = pytest.mark.skip(
        reason=f"set {_DB_URL_ENV} to run integration tests"
    )
    skip_performance = pytest.mark.skip(
        reason=f"set {_PERF_ENV}=1 to run performance tests"
    )

    for item in items:
        if "integration" in item.keywords and db_url is None:
            item.add_marker(skip_integration)
        if "performance" in item.keywords and not run_perf:
            item.add_marker(skip_performance)


@pytest.fixture(scope="session")
def db_url() -> str:
    """The integration-test database URL (guaranteed set for tests that
    reach this fixture, since they're skipped otherwise)."""
    url = _test_db_url()
    if url is None:  # pragma: no cover - guarded by the skip above
        pytest.skip(f"{_DB_URL_ENV} is not set")
    return url


@pytest.fixture()
def db_connection(db_url: str) -> Iterator["object"]:
    """A live psycopg connection for one test, always cleaned up.

    Each test runs inside a transaction that is rolled back at the end,
    so tests never leave state behind and never see each other's data.
    """
    import psycopg

    connection = psycopg.connect(db_url)
    try:
        connection.autocommit = False
        yield connection
        connection.rollback()
    finally:
        connection.close()