"""Unit tests for the compare diff logic and service (Sprint 10)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sqlcoach.advisor.anti_patterns.base import AntiPatternFinding
from sqlcoach.analyzer.base import Finding, Severity
from sqlcoach.config import Settings
from sqlcoach.exceptions import ValidationError
from sqlcoach.models.execution_plan import PlanSummary
from sqlcoach.models.index_recommendation import IndexKind, IndexRecommendation
from sqlcoach.models.recommendation import ConfidenceLevel
from sqlcoach.reports import services
from sqlcoach.reports.comparison import compare_results, compare_service
from sqlcoach.reports.services import AnalyzeResult


def _anti_pattern(code: str, relation: str | None = "users") -> AntiPatternFinding:
    return AntiPatternFinding(
        code=code,
        detector="d",
        severity=Severity.LOW,
        summary="s",
        source_location="q.sql:line 1",
        relation_name=relation,
    )


def _plan_finding(code: str, relation: str = "users") -> Finding:
    return Finding(
        code=code,
        detector="d",
        severity=Severity.HIGH,
        summary="s",
        node_type="X",
        relation_name=relation,
    )


def _index_rec(table: str = "users", columns: tuple[str, ...] = ("email",)) -> IndexRecommendation:
    return IndexRecommendation(
        table=table,
        columns=columns,
        kind=IndexKind.SINGLE_COLUMN,
        create_statement="CREATE INDEX x ON t (c);",
        rationale="r",
        confidence=ConfidenceLevel.HIGH,
        source_finding_code="SEQ_SCAN_LARGE_TABLE",
    )


def _plan(node: str = "Seq Scan", cost: float = 1000.0, time: float | None = None) -> PlanSummary:
    return PlanSummary(root_node_type=node, estimated_cost=cost, execution_time_ms=time)


def _result(
    *,
    analyzed_against_database: bool = False,
    anti_pattern_findings: tuple = (),
    findings: tuple = (),
    index_recommendations: tuple = (),
    plan_summaries: tuple = (),
) -> AnalyzeResult:
    return AnalyzeResult(
        queries_parsed=1,
        queries_analyzed=len(plan_summaries),
        analyzed_against_database=analyzed_against_database,
        anti_pattern_findings=anti_pattern_findings,
        findings=findings,
        index_recommendations=index_recommendations,
        plan_summaries=plan_summaries,
    )


class TestStaticDiff:
    def test_improvement_anti_pattern_removed(self) -> None:
        before = _result(
            anti_pattern_findings=(_anti_pattern("SELECT_STAR"), _anti_pattern("ORDER_BY_RANDOM"))
        )
        after = _result(anti_pattern_findings=(_anti_pattern("ORDER_BY_RANDOM"),))

        result = compare_results(before, after)

        assert result.anti_patterns.removed == ("SELECT_STAR on users",)
        assert result.anti_patterns.added == ()
        assert result.anti_patterns.unchanged == ("ORDER_BY_RANDOM on users",)

    def test_regression_anti_pattern_added(self) -> None:
        result = compare_results(
            _result(), _result(anti_pattern_findings=(_anti_pattern("SELECT_STAR"),))
        )
        assert result.anti_patterns.added == ("SELECT_STAR on users",)
        assert result.anti_patterns.removed == ()

    def test_no_change(self) -> None:
        both = (_anti_pattern("SELECT_STAR"),)
        result = compare_results(
            _result(anti_pattern_findings=both), _result(anti_pattern_findings=both)
        )
        assert result.anti_patterns.removed == ()
        assert result.anti_patterns.added == ()
        assert result.anti_patterns.unchanged == ("SELECT_STAR on users",)

    def test_static_compare_has_no_plan_metrics(self) -> None:
        result = compare_results(_result(), _result())
        assert result.compared_against_database is False
        assert result.estimated_cost_before is None
        assert result.plan_shape_before is None


class TestPlanDiff:
    def test_seq_scan_gone_with_cost_time_and_shape(self) -> None:
        before = _result(
            analyzed_against_database=True,
            findings=(_plan_finding("SEQ_SCAN_LARGE_TABLE"),),
            plan_summaries=(_plan("Seq Scan", 5000.0, 620.0),),
        )
        after = _result(
            analyzed_against_database=True,
            findings=(),
            plan_summaries=(_plan("Index Scan", 8.0, 15.0),),
        )

        result = compare_results(before, after)

        assert result.plan_findings.removed == ("SEQ_SCAN_LARGE_TABLE on users",)
        assert result.compared_against_database is True
        assert result.estimated_cost_before == 5000.0
        assert result.estimated_cost_after == 8.0
        assert result.execution_time_ms_before == 620.0
        assert result.execution_time_ms_after == 15.0
        assert result.plan_shape_before == "Seq Scan"
        assert result.plan_shape_after == "Index Scan"

    def test_index_recommendation_resolved(self) -> None:
        before = _result(
            analyzed_against_database=True,
            index_recommendations=(_index_rec(),),
            plan_summaries=(_plan(),),
        )
        after = _result(
            analyzed_against_database=True,
            index_recommendations=(),
            plan_summaries=(_plan("Index Scan", 8.0),),
        )

        result = compare_results(before, after)
        assert result.index_recommendations.removed == ("users(email)",)

    def test_multi_query_omits_shape_but_keeps_aggregate_cost(self) -> None:
        before = _result(
            analyzed_against_database=True,
            plan_summaries=(_plan("Seq Scan", 1000.0, 100.0), _plan("Sort", 500.0, 50.0)),
        )
        after = _result(
            analyzed_against_database=True,
            plan_summaries=(_plan("Index Scan", 10.0, 5.0), _plan("Sort", 500.0, 50.0)),
        )

        result = compare_results(before, after)
        assert result.plan_shape_before is None
        assert result.estimated_cost_before == 1500.0
        assert result.estimated_cost_after == 510.0
        assert result.execution_time_ms_before == 150.0

    def test_time_is_none_when_not_all_queries_have_it(self) -> None:
        before = _result(
            analyzed_against_database=True, plan_summaries=(_plan("Seq Scan", 1000.0, None),)
        )
        after = _result(
            analyzed_against_database=True, plan_summaries=(_plan("Seq Scan", 1000.0, 20.0),)
        )

        result = compare_results(before, after)
        assert result.execution_time_ms_before is None
        assert result.execution_time_ms_after == 20.0


class TestDeterminism:
    def test_output_is_deterministic_and_sorted(self) -> None:
        before = _result(
            anti_pattern_findings=(
                _anti_pattern("ORDER_BY_RANDOM"),
                _anti_pattern("SELECT_STAR"),
                _anti_pattern("N_PLUS_ONE", None),
            )
        )
        after = _result()

        first = compare_results(before, after)
        second = compare_results(before, after)

        assert first.anti_patterns.removed == second.anti_patterns.removed
        assert list(first.anti_patterns.removed) == sorted(first.anti_patterns.removed)


class TestCompareServiceEndToEnd:
    def _write(self, tmp_path, name: str, sql: str):
        path = tmp_path / name
        path.write_text(sql, encoding="utf-8")
        return path

    def test_static_compare_detects_resolved_anti_pattern(self, tmp_path) -> None:
        before = self._write(tmp_path, "before.sql", "SELECT * FROM users WHERE email = 'a';")
        after = self._write(tmp_path, "after.sql", "SELECT id, email FROM users WHERE email = 'a';")

        result = compare_service(before, after, settings=Settings())

        assert result.compared_against_database is False
        assert result.anti_patterns.removed == ("SELECT_STAR on users",)

    def test_missing_source_raises_validation_error(self, tmp_path) -> None:
        after = self._write(tmp_path, "after.sql", "SELECT id FROM t;")
        with pytest.raises(ValidationError):
            compare_service(None, after, settings=Settings())

    def test_live_compare_shows_plan_improvement(self, tmp_path, monkeypatch) -> None:
        before = self._write(tmp_path, "before.sql", "SELECT id FROM users WHERE email = 'a';")
        after = self._write(tmp_path, "after.sql", "SELECT id FROM users WHERE email = 'a';")

        seq_plan = [
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Total Cost": 5000.0,
                    "Plan Rows": 500000,
                    "Actual Rows": 500000,
                },
                "Execution Time": 620.0,
            }
        ]
        idx_plan = [
            {
                "Plan": {
                    "Node Type": "Index Scan",
                    "Relation Name": "users",
                    "Total Cost": 8.0,
                    "Plan Rows": 1,
                    "Actual Rows": 1,
                },
                "Execution Time": 15.0,
            }
        ]

        connection = MagicMock()
        db_cm = MagicMock()
        db_cm.__enter__.return_value = connection
        db_cm.__exit__.return_value = False
        monkeypatch.setattr(services, "DatabaseConnection", lambda **_: db_cm)

        runner = MagicMock()
        runner.explain.side_effect = [seq_plan, idx_plan]
        monkeypatch.setattr(services, "ExplainRunner", lambda: runner)

        result = compare_service(before, after, db_url="postgresql://x/y", settings=Settings())

        assert result.compared_against_database is True
        assert result.plan_shape_before == "Seq Scan"
        assert result.plan_shape_after == "Index Scan"
        assert result.estimated_cost_before == 5000.0
        assert result.estimated_cost_after == 8.0
        assert result.plan_findings.removed == ("SEQ_SCAN_LARGE_TABLE on users",)