"""Comparison of two analyze runs (Sprint 10, FR-4.1).

Diffs a "before" and "after" `AnalyzeResult` into a `ComparisonResult`
so a developer can confirm an optimization actually helped.

The diff is a set difference over stable keys (anti-pattern and plan
findings by ``code on relation``; index recommendations by their table
and columns), producing sorted removed/added/unchanged tuples -- so the
structural output is deterministic for identical inputs (NFR-4.3).

Plan metrics are included only when *both* runs used a live database.
Estimated cost is deterministic and reported as the primary metric;
execution time is an observed measurement, reported for context but not
part of the deterministic contract. Plan shape (root node type) is shown
only when each side is a single query, where "the plan" is unambiguous.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from sqlcoach.reports.services import AnalyzeResult


class SetDiff(BaseModel):
    """The before/after difference of one set of keyed items."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    removed: tuple[str, ...] = Field(default_factory=tuple)
    added: tuple[str, ...] = Field(default_factory=tuple)
    unchanged: tuple[str, ...] = Field(default_factory=tuple)


class ComparisonResult(BaseModel):
    """The structured diff between two analyze runs.

    Attributes:
        anti_patterns: Anti-pattern findings removed / added / unchanged.
        plan_findings: Execution-plan findings removed / added / unchanged.
        index_recommendations: Index recommendations removed / added /
            unchanged.
        compared_against_database: True only when both runs used a live
            database; the plan-metric fields below are populated only then.
        estimated_cost_before / estimated_cost_after: Total planner cost
            summed across each run's queries. Deterministic.
        execution_time_ms_before / execution_time_ms_after: Total measured
            execution time. Observed, not part of the deterministic
            contract; None if any query lacked ANALYZE timing.
        plan_shape_before / plan_shape_after: Root node type, shown only
            when each run is a single query. None otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    anti_patterns: SetDiff
    plan_findings: SetDiff
    index_recommendations: SetDiff
    compared_against_database: bool
    estimated_cost_before: Optional[float] = None
    estimated_cost_after: Optional[float] = None
    execution_time_ms_before: Optional[float] = None
    execution_time_ms_after: Optional[float] = None
    plan_shape_before: Optional[str] = None
    plan_shape_after: Optional[str] = None


def _finding_key(finding) -> str:  # type: ignore[no-untyped-def]
    """Stable key for an anti-pattern or plan finding: ``code on relation``."""
    if finding.relation_name:
        return f"{finding.code} on {finding.relation_name}"
    return finding.code


def _index_key(rec) -> str:  # type: ignore[no-untyped-def]
    """Stable key for an index recommendation: ``table(cols)[ INCLUDE (...)]``."""
    key = f"{rec.table}({', '.join(rec.columns)})"
    if rec.included_columns:
        key += f" INCLUDE ({', '.join(rec.included_columns)})"
    return key


def _diff(before_keys: list[str], after_keys: list[str]) -> SetDiff:
    before, after = set(before_keys), set(after_keys)
    return SetDiff(
        removed=tuple(sorted(before - after)),
        added=tuple(sorted(after - before)),
        unchanged=tuple(sorted(before & after)),
    )


def _total_cost(result: AnalyzeResult) -> Optional[float]:
    if not result.plan_summaries:
        return None
    return sum(summary.estimated_cost for summary in result.plan_summaries)


def _total_time(result: AnalyzeResult) -> Optional[float]:
    times = [
        s.execution_time_ms
        for s in result.plan_summaries
        if s.execution_time_ms is not None
    ]
    if not result.plan_summaries or len(times) != len(result.plan_summaries):
        return None
    return sum(times)


def _single_shape(result: AnalyzeResult) -> Optional[str]:
    if len(result.plan_summaries) == 1:
        return result.plan_summaries[0].root_node_type
    return None


def compare_results(before: AnalyzeResult, after: AnalyzeResult) -> ComparisonResult:
    """Diff two analyze runs into a ComparisonResult.

    Structural diffs (anti-patterns, plan findings, index recommendations)
    are always computed. Plan cost/time/shape are included only when both
    runs used a live database.
    """
    both_against_database = (
        before.analyzed_against_database and after.analyzed_against_database
    )

    result_kwargs: dict = dict(
        anti_patterns=_diff(
            [_finding_key(f) for f in before.anti_pattern_findings],
            [_finding_key(f) for f in after.anti_pattern_findings],
        ),
        plan_findings=_diff(
            [_finding_key(f) for f in before.findings],
            [_finding_key(f) for f in after.findings],
        ),
        index_recommendations=_diff(
            [_index_key(r) for r in before.index_recommendations],
            [_index_key(r) for r in after.index_recommendations],
        ),
        compared_against_database=both_against_database,
    )

    if both_against_database:
        result_kwargs.update(
            estimated_cost_before=_total_cost(before),
            estimated_cost_after=_total_cost(after),
            execution_time_ms_before=_total_time(before),
            execution_time_ms_after=_total_time(after),
            plan_shape_before=_single_shape(before),
            plan_shape_after=_single_shape(after),
        )

    return ComparisonResult(**result_kwargs)