"""Audit service (Sprint 11, US11.1, FR-4.2).

Runs a whole-database health check in one read-only pass: workload
analysis (top queries from pg_stat_statements -> plan analysis + index
advice + anti-patterns), duplicate-index detection, and unused-index
detection. Findings from every section flow through the recommendation
engine into one ranked report.

Each section is best-effort and independent (graceful degradation): a
missing prerequisite -- pg_stat_statements not enabled, a catalog read
that fails -- skips that section with a recorded reason rather than
failing the whole audit. Only a failure to connect at all aborts.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.advisor.anti_patterns.analyzer import (
    AntiPatternAnalyzer,
    default_detectors as default_anti_pattern_detectors,
)
from sqlcoach.advisor.duplicate_index_detector import DuplicateIndexDetector
from sqlcoach.advisor.index_advisor import IndexAdvisor
from sqlcoach.advisor.recommendation_engine import RecommendationEngine
from sqlcoach.advisor.unused_index_detector import UnusedIndexDetector
from sqlcoach.analyzer.base import AnalysisContext
from sqlcoach.config import Settings, load_settings
from sqlcoach.database.connection import DatabaseConnection
from sqlcoach.database.index_catalog import fetch_index_usage, fetch_indexes
from sqlcoach.database.pg_stat_statements import (
    fetch_top_queries,
    is_pg_stat_statements_available,
)
from sqlcoach.exceptions import SQLCoachError, ValidationError
from sqlcoach.models.recommendation import Recommendation
from sqlcoach.reports.services import _explain_and_analyze

logger = logging.getLogger(__name__)


class SkippedSection(BaseModel):
    """An audit section that couldn't run, with why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    reason: str


class AuditResult(BaseModel):
    """The outcome of an audit run, for the CLI to render.

    Attributes:
        recommendations: The unified, ranked recommendation list.
        sections_completed: Names of the sections that ran.
        sections_skipped: Sections that were skipped, each with a reason.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    recommendations: tuple[Recommendation, ...] = Field(default_factory=tuple)
    sections_completed: tuple[str, ...] = Field(default_factory=tuple)
    sections_skipped: tuple[SkippedSection, ...] = Field(default_factory=tuple)


def audit_service(
    db_url: Optional[str],
    *,
    confirm_mutations: bool = False,
    settings: Optional[Settings] = None,
) -> AuditResult:
    """Run a full, read-only database health check.

    Raises:
        ValidationError: If no database URL is given (audit requires one).
        DatabaseConnectionError: If the database cannot be connected to.
    """
    if db_url is None:
        raise ValidationError(
            "audit requires a database to inspect; pass --db-url",
            details={"db_url": None},
        )

    resolved_settings = settings if settings is not None else load_settings()
    context = AnalysisContext.from_settings(resolved_settings)
    advisor = IndexAdvisor(
        max_included_columns=resolved_settings.covering_index_max_included_columns
    )

    plan_findings: list = []
    index_recommendations: list = []
    anti_pattern_findings: list = []
    index_hygiene_findings: list = []
    completed: list[str] = []
    skipped: list[SkippedSection] = []

    with DatabaseConnection(dsn=db_url) as connection:
        # Section 1: live workload (needs pg_stat_statements).
        try:
            if is_pg_stat_statements_available(connection):
                queries = fetch_top_queries(connection)
                findings, _analyzed, recs, _summaries = _explain_and_analyze(
                    connection,
                    queries,
                    confirm_mutations=confirm_mutations,
                    context=context,
                    advisor=advisor,
                )
                plan_findings.extend(findings)
                index_recommendations.extend(recs)
                anti_pattern_findings.extend(
                    AntiPatternAnalyzer(
                        detectors=default_anti_pattern_detectors(
                            n_plus_one_min_occurrences=(
                                resolved_settings.n_plus_one_min_occurrences
                            )
                        )
                    ).analyze(queries)
                )
                completed.append("workload")
            else:
                skipped.append(
                    SkippedSection(
                        name="workload",
                        reason="pg_stat_statements extension is not enabled",
                    )
                )
        except SQLCoachError as exc:
            logger.warning("Audit workload section skipped: %s", exc)
            skipped.append(SkippedSection(name="workload", reason=str(exc)))

        # Sections 2 & 3: index hygiene (needs the catalog).
        indexes = None
        try:
            indexes = fetch_indexes(connection)
        except SQLCoachError as exc:
            logger.warning("Audit index-catalog read skipped: %s", exc)
            skipped.append(SkippedSection(name="index_catalog", reason=str(exc)))

        if indexes is not None:
            index_hygiene_findings.extend(DuplicateIndexDetector().detect(indexes))
            completed.append("duplicate_indexes")
            try:
                usage = fetch_index_usage(connection)
                index_hygiene_findings.extend(
                    UnusedIndexDetector(
                        max_scans=resolved_settings.unused_index_max_scans
                    ).detect(indexes, usage)
                )
                completed.append("unused_indexes")
            except SQLCoachError as exc:
                logger.warning("Audit unused-index section skipped: %s", exc)
                skipped.append(SkippedSection(name="unused_indexes", reason=str(exc)))

    recommendations = RecommendationEngine().generate(
        plan_findings=plan_findings,
        index_recommendations=index_recommendations,
        anti_pattern_findings=anti_pattern_findings,
        index_hygiene_findings=index_hygiene_findings,
    )
    return AuditResult(
        recommendations=tuple(recommendations),
        sections_completed=tuple(completed),
        sections_skipped=tuple(skipped),
    )