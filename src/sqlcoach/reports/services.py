"""Application services for CLI commands.

These functions are the seam between the CLI (`cli/main.py`) and the
domain layers (parser, database, analyzer, advisor). The CLI parses
arguments and renders output; a service does the actual orchestration
and returns plain data. Business logic never lives in the CLI
(NFR-X.2, FR-2.10).

`audit`, `report`, and `compare` remain placeholders until their
sprints (11, 9-HTML, and 10 respectively). `analyze` parses a `.sql`
file, always runs the static anti-pattern checks, optionally runs the
live-database plan analysis + index advisor, and unifies every source
into one ranked recommendation list via the recommendation engine.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.advisor.anti_patterns.analyzer import (
    AntiPatternAnalyzer,
    default_detectors as default_anti_pattern_detectors,
)
from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.advisor.index_advisor import IndexAdvisor
from sqlcoach.advisor.recommendation_engine import RecommendationEngine
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
from sqlcoach.models.execution_plan import PlanSummary
from sqlcoach.models.index_recommendation import IndexRecommendation
from sqlcoach.models.query import Query
from sqlcoach.models.recommendation import Recommendation
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
        queries_parsed: Number of statements successfully parsed.
        queries_analyzed: Number of queries run through EXPLAIN ANALYZE.
            Zero for a static-only run; may be less than queries_parsed
            when some were skipped (e.g. blocked mutating statements).
        analyzed_against_database: Whether a live database was used.
        anti_pattern_findings: Raw static anti-pattern findings. Always
            populated. Retained for inspection; the unified narrative is
            in `recommendations`.
        findings: Raw execution-plan findings. Empty for a static run.
        index_recommendations: Raw, deduped index recommendations.
            Empty for a static run.
        recommendations: The unified, deduplicated, ranked recommendation
            list built from all three sources -- the primary output.
        plan_summaries: One PlanSummary per analyzed query (root node
            type, estimated cost, execution time), used by the compare
            command. Empty for a static-only run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    queries_parsed: int = Field(ge=0)
    queries_analyzed: int = Field(ge=0)
    analyzed_against_database: bool
    anti_pattern_findings: tuple[AntiPatternFinding, ...] = Field(default_factory=tuple)
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    index_recommendations: tuple[IndexRecommendation, ...] = Field(default_factory=tuple)
    recommendations: tuple[Recommendation, ...] = Field(default_factory=tuple)
    plan_summaries: tuple[PlanSummary, ...] = Field(default_factory=tuple)


def analyze_service(
    source: Optional[Path],
    *,
    db_url: Optional[str] = None,
    confirm_mutations: bool = False,
    settings: Optional[Settings] = None,
) -> AnalyzeResult:
    """Parse a SQL file, detect issues from every available source, and
    return one ranked recommendation list.

    Anti-pattern analysis is static and always runs. Plan analysis and
    index advice run only when `db_url` is given. All findings are then
    unified and ranked by the recommendation engine.

    Args:
        source: Path to a `.sql` file to analyze.
        db_url: Optional PostgreSQL connection string.
        confirm_mutations: Must be True to let EXPLAIN ANALYZE execute
            statements that modify data or take locks (FR-3.2.2).
        settings: Validated settings; loaded from the default location
            when omitted (the CLI passes its already-loaded settings).

    Returns:
        An AnalyzeResult, including the ranked `recommendations`.

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

    # Static anti-pattern analysis always runs.
    anti_pattern_findings = AntiPatternAnalyzer(
        detectors=default_anti_pattern_detectors(
            n_plus_one_min_occurrences=resolved_settings.n_plus_one_min_occurrences
        )
    ).analyze(queries)

    # Plan analysis + index advice only with a live database.
    plan_findings: Sequence[Finding] = ()
    index_recommendations: Sequence[IndexRecommendation] = ()
    plan_summaries: Sequence[PlanSummary] = ()
    analyzed = 0
    analyzed_against_database = False
    if db_url is not None:
        plan_findings, analyzed, index_recommendations, plan_summaries = _analyze_against_database(
            queries,
            db_url=db_url,
            confirm_mutations=confirm_mutations,
            context=AnalysisContext.from_settings(resolved_settings),
            advisor=IndexAdvisor(
                max_included_columns=resolved_settings.covering_index_max_included_columns
            ),
        )
        analyzed_against_database = True

    recommendations = RecommendationEngine().generate(
        plan_findings=plan_findings,
        index_recommendations=index_recommendations,
        anti_pattern_findings=anti_pattern_findings,
    )

    return AnalyzeResult(
        queries_parsed=len(queries),
        queries_analyzed=analyzed,
        analyzed_against_database=analyzed_against_database,
        anti_pattern_findings=tuple(anti_pattern_findings),
        findings=tuple(plan_findings),
        index_recommendations=tuple(index_recommendations),
        recommendations=tuple(recommendations),
        plan_summaries=tuple(plan_summaries),
    )


def _analyze_against_database(
    queries: list[Query],
    *,
    db_url: str,
    confirm_mutations: bool,
    context: AnalysisContext,
    advisor: IndexAdvisor,
) -> tuple[list[Finding], int, list[IndexRecommendation], list[PlanSummary]]:
    """Run EXPLAIN ANALYZE + plan analysis for each query over one
    connection, dedupe index recommendations, and summarize each plan.

    Returns the flat findings list, the count actually analyzed, the
    deduplicated recommendations, and one PlanSummary per analyzed query.
    One connection is reused across all queries (NFR-3.2.2). A query that
    can't be explained -- a blocked mutating statement, or an EXPLAIN that
    errors -- is logged and skipped rather than aborting the whole run. A
    failure to open the connection propagates as a DatabaseConnectionError.
    """
    runner = ExplainRunner()
    analyzer = PlanAnalyzer()
    per_query: list[tuple[Query, list[Finding]]] = []
    plan_summaries: list[PlanSummary] = []

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
            per_query.append((query, analyzer.analyze(plan, context)))
            plan_summaries.append(
                PlanSummary(
                    root_node_type=plan.root.node_type,
                    estimated_cost=plan.root.estimated_cost,
                    execution_time_ms=plan.execution_time_ms,
                )
            )

    findings = [finding for _, query_findings in per_query for finding in query_findings]
    recommendations = advisor.recommend_for_workload(
        (query.text, query_findings) for query, query_findings in per_query
    )
    return findings, len(per_query), recommendations, plan_summaries


def audit_service(db_url: Optional[str]) -> None:
    """Placeholder for the `audit` command's business logic.

    Real implementation lands in Sprint 11.
    """
    raise NotYetImplementedError("audit")


def report_service(output: Optional[Path]) -> None:
    """Placeholder for the `report` command's business logic.

    Real implementation lands alongside HTML report generation.
    """
    raise NotYetImplementedError("report")


