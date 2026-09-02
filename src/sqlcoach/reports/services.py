"""Application services for CLI commands.

These functions are the seam between the CLI (`cli/main.py`) and the
domain layers (parser, database, analyzer). The CLI parses arguments
and renders output; a service does the actual orchestration and returns
plain data. Business logic never lives in the CLI (NFR-X.2, FR-2.10).

`audit`, `report`, and `compare` remain placeholders until their
sprints (11, 9, and 10 respectively). `analyze` is implemented here as
of Sprint 6: it parses a `.sql` file into queries and, when a database
URL is supplied, runs each query through EXPLAIN ANALYZE and the plan
analyzer, returning the detected findings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.analyzer.base import AnalysisContext, Finding
from sqlcoach.analyzer.plan_analyzer import PlanAnalyzer
from sqlcoach.config import Settings, load_settings
from sqlcoach.database.connection import DatabaseConnection
from sqlcoach.database.explain_runner import ExplainRunner
from sqlcoach.exceptions import (
    DatabaseConnectionError,
    MutatingStatementError,
    ValidationError,
)
from sqlcoach.models.query import Query
from sqlcoach.parser.plan_json_parser import parse_explain_json
from sqlcoach.parser.sql_file_parser import SqlFileParser

logger = logging.getLogger(__name__)


class NotYetImplementedError(NotImplementedError):
    """Raised by a placeholder service to signal a command whose real
    logic has not been implemented yet.

    The CLI layer catches this and turns it into a clean, user-facing
    message rather than a stack trace. Deliberately a subclass of the
    stdlib `NotImplementedError` rather than `SQLCoachError`: this
    condition is temporary scaffolding, not a genuine domain error.
    """


class AnalyzeResult(BaseModel):
    """The outcome of an `analyze` run, for the CLI to render.

    Attributes:
        queries_parsed: Number of statements successfully parsed from
            the source file.
        queries_analyzed: Number of queries actually run through EXPLAIN
            ANALYZE and inspected. Zero when no database URL was given
            (static parse only), and may be less than `queries_parsed`
            when some queries were skipped (e.g. mutating statements
            without confirmation).
        analyzed_against_database: Whether a live database was used.
        findings: All plan findings, across every analyzed query, in
            deterministic order.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    queries_parsed: int = Field(ge=0)
    queries_analyzed: int = Field(ge=0)
    analyzed_against_database: bool
    findings: tuple[Finding, ...] = Field(default_factory=tuple)


def analyze_service(
    source: Optional[Path],
    *,
    db_url: Optional[str] = None,
    confirm_mutations: bool = False,
    settings: Optional[Settings] = None,
) -> AnalyzeResult:
    """Parse a SQL file and, if a database URL is given, analyze each
    query's execution plan.

    Args:
        source: Path to a `.sql` file to analyze.
        db_url: Optional PostgreSQL connection string. When provided,
            each parsed query is run through EXPLAIN ANALYZE and its
            plan inspected by the analyzer. When omitted, only static
            parsing is performed -- there is no execution plan to
            analyze without a live database.
        confirm_mutations: Passed through to the EXPLAIN runner; must be
            True to let EXPLAIN ANALYZE execute statements that modify
            data or take locks (FR-3.2.2).
        settings: Validated settings supplying analyzer thresholds. When
            omitted, loaded from the default location -- but the CLI
            always passes the settings it already loaded, so the file
            precedence honored there is preserved.

    Returns:
        An AnalyzeResult with parsed/analyzed counts and any findings.

    Raises:
        ValidationError: If no source is given.
        DatabaseConnectionError: If the database cannot be connected to.
    """
    if source is None:
        raise ValidationError(
            "analyze requires a path to a .sql file",
            details={"source": None},
        )

    resolved_settings = settings if settings is not None else load_settings()

    queries = SqlFileParser().parse(source)
    logger.info("Parsed %d queries from %s", len(queries), source)

    if db_url is None:
        return AnalyzeResult(
            queries_parsed=len(queries),
            queries_analyzed=0,
            analyzed_against_database=False,
            findings=(),
        )

    findings, analyzed = _analyze_against_database(
        queries,
        db_url=db_url,
        confirm_mutations=confirm_mutations,
        context=AnalysisContext.from_settings(resolved_settings),
    )
    return AnalyzeResult(
        queries_parsed=len(queries),
        queries_analyzed=analyzed,
        analyzed_against_database=True,
        findings=tuple(findings),
    )


def _analyze_against_database(
    queries: list[Query],
    *,
    db_url: str,
    confirm_mutations: bool,
    context: AnalysisContext,
) -> tuple[list[Finding], int]:
    """Run EXPLAIN ANALYZE + plan analysis for each query over one
    connection, returning the findings and the count actually analyzed.

    One connection is reused across all queries (NFR-3.2.2). A single
    query that can't be explained -- a blocked mutating statement, or an
    EXPLAIN that errors -- is logged and skipped rather than aborting
    the whole run, mirroring the parser's per-statement resilience. A
    failure to open the connection is not caught here and propagates as
    a DatabaseConnectionError.
    """
    runner = ExplainRunner()
    analyzer = PlanAnalyzer()
    findings: list[Finding] = []
    analyzed = 0

    with DatabaseConnection(dsn=db_url) as connection:
        for query in queries:
            try:
                raw_plan = runner.explain(
                    connection, query.text, confirm_mutations=confirm_mutations
                )
            except MutatingStatementError:
                logger.warning(
                    "Skipping a statement that modifies data or takes locks; "
                    "pass --confirm-mutations to analyze it (%s)",
                    query.source_location or "unknown location",
                )
                continue
            except DatabaseConnectionError as exc:
                logger.warning(
                    "Skipping a query whose EXPLAIN failed (%s): %s",
                    query.source_location or "unknown location",
                    exc,
                )
                continue

            plan = parse_explain_json(raw_plan)
            findings.extend(analyzer.analyze(plan, context))
            analyzed += 1

    return findings, analyzed


def audit_service(db_url: Optional[str]) -> None:
    """Placeholder for the `audit` command's business logic.

    Real implementation lands in Sprint 11.
    """
    raise NotYetImplementedError("audit")


def report_service(output: Optional[Path]) -> None:
    """Placeholder for the `report` command's business logic.

    Real implementation lands alongside the recommendation engine
    (Sprint 9) and HTML report generation.
    """
    raise NotYetImplementedError("report")


def compare_service(before: Optional[Path], after: Optional[Path]) -> None:
    """Placeholder for the `compare` command's business logic.

    Real implementation lands in Sprint 10.
    """
    raise NotYetImplementedError("compare")