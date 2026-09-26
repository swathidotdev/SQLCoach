"""Unit tests for the index advisor (US7.1, single-column)."""

from __future__ import annotations

import pytest

from sqlcoach.advisor.index_advisor import IndexAdvisor
from sqlcoach.analyzer.base import AnalysisContext, Finding, Severity
from sqlcoach.analyzer.plan_analyzer import PlanAnalyzer
from sqlcoach.config import Settings
from sqlcoach.models.index_recommendation import IndexKind
from sqlcoach.models.recommendation import ConfidenceLevel
from sqlcoach.parser.plan_json_parser import parse_explain_json


@pytest.fixture
def advisor() -> IndexAdvisor:
    return IndexAdvisor()


def _seq_scan_finding(
    relation: str, *, severity: Severity = Severity.HIGH
) -> Finding:
    return Finding(
        code="SEQ_SCAN_LARGE_TABLE",
        detector="sequential_scan",
        severity=severity,
        summary="big scan",
        node_type="Seq Scan",
        relation_name=relation,
    )


class TestSingleColumnRecommendation:
    def test_recommends_index_on_equality_filter_column(
        self, advisor: IndexAdvisor
    ) -> None:
        recs = advisor.recommend_for_query(
            "SELECT * FROM users WHERE email = 'a@b.com'",
            [_seq_scan_finding("users")],
        )

        assert len(recs) == 1
        rec = recs[0]
        assert rec.table == "users"
        assert rec.columns == ("email",)
        assert rec.kind is IndexKind.SINGLE_COLUMN
        assert rec.create_statement == "CREATE INDEX idx_users_email ON users (email);"
        assert rec.confidence is ConfidenceLevel.HIGH
        assert rec.source_finding_code == "SEQ_SCAN_LARGE_TABLE"

    def test_recommends_on_a_range_column_when_it_is_the_only_predicate(
        self, advisor: IndexAdvisor
    ) -> None:
        recs = advisor.recommend_for_query(
            "SELECT id FROM events WHERE created_at > NOW() - INTERVAL '1 day'",
            [_seq_scan_finding("events")],
        )
        assert len(recs) == 1
        assert recs[0].columns == ("created_at",)

    def test_estimate_only_finding_yields_medium_confidence(
        self, advisor: IndexAdvisor
    ) -> None:
        recs = advisor.recommend_for_query(
            "SELECT * FROM users WHERE email = 'a@b.com'",
            [_seq_scan_finding("users", severity=Severity.MEDIUM)],
        )
        assert recs[0].confidence is ConfidenceLevel.MEDIUM


class TestScopingAndFalsePositives:
    def test_no_recommendation_without_a_seq_scan_finding(
        self, advisor: IndexAdvisor
    ) -> None:
        # An index-scan finding, or no finding at all, means no evidence
        # the table needs an index. Nothing is recommended.
        recs = advisor.recommend_for_query(
            "SELECT * FROM users WHERE email = 'a@b.com'", []
        )
        assert recs == []

    def test_ignores_non_seq_scan_findings(self, advisor: IndexAdvisor) -> None:
        other = Finding(
            code="SORT_SPILLED_TO_DISK",
            detector="expensive_sort",
            severity=Severity.HIGH,
            summary="spill",
            node_type="Sort",
        )
        recs = advisor.recommend_for_query(
            "SELECT * FROM users WHERE email = 'a@b.com'", [other]
        )
        assert recs == []


    def test_unfiltered_scan_yields_no_recommendation(
        self, advisor: IndexAdvisor
    ) -> None:
        # A seq scan with no attributable predicate on the table: an
        # index can't help a full unfiltered scan.
        recs = advisor.recommend_for_query(
            "SELECT * FROM users", [_seq_scan_finding("users")]
        )
        assert recs == []


class TestEndToEndWithRealDetector:
    def test_real_seq_scan_finding_flows_into_a_recommendation(
        self, advisor: IndexAdvisor
    ) -> None:
        # Guards against the advisor's expected finding code drifting
        # away from what the detector actually emits: the finding here is
        # produced by the real analyzer, not hand-built.
        payload = [
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Relation Name": "users",
                    "Total Cost": 5000.0,
                    "Plan Rows": 480_000,
                    "Actual Rows": 500_000,
                },
                "Execution Time": 620.0,
            }
        ]
        findings = PlanAnalyzer().analyze(
            parse_explain_json(payload), AnalysisContext.from_settings(Settings())
        )

        recs = advisor.recommend_for_query(
            "SELECT * FROM users WHERE email = 'abc@gmail.com'", findings
        )

        assert len(recs) == 1
        assert recs[0].create_statement == "CREATE INDEX idx_users_email ON users (email);"



class TestCoveringRecommendation:
    def test_covering_index_with_include(self, advisor: IndexAdvisor) -> None:
        recs = advisor.recommend_for_query(
            "SELECT id, total FROM orders WHERE user_id = 20",
            [_seq_scan_finding("orders")],
        )

        assert len(recs) == 1
        rec = recs[0]
        assert rec.kind is IndexKind.COVERING
        assert rec.columns == ("user_id",)
        assert rec.included_columns == ("id", "total")
        assert rec.create_statement == (
            "CREATE INDEX idx_orders_user_id ON orders (user_id) INCLUDE (id, total);"
        )

    def test_composite_covering(self, advisor: IndexAdvisor) -> None:
        recs = advisor.recommend_for_query(
            "SELECT id, total FROM orders WHERE user_id = 20 AND status = 1",
            [_seq_scan_finding("orders")],
        )
        rec = recs[0]
        assert rec.kind is IndexKind.COVERING
        assert rec.columns == ("user_id", "status")
        assert rec.included_columns == ("id", "total")

    def test_select_star_yields_no_covering(self, advisor: IndexAdvisor) -> None:
        recs = advisor.recommend_for_query(
            "SELECT * FROM orders WHERE user_id = 20", [_seq_scan_finding("orders")]
        )
        assert recs[0].included_columns == ()
        assert recs[0].kind is IndexKind.SINGLE_COLUMN

    def test_count_star_yields_no_covering(self, advisor: IndexAdvisor) -> None:
        recs = advisor.recommend_for_query(
            "SELECT COUNT(*) FROM orders WHERE user_id = 20",
            [_seq_scan_finding("orders")],
        )
        assert recs[0].included_columns == ()

    def test_selected_columns_already_in_key_need_no_include(
        self, advisor: IndexAdvisor
    ) -> None:
        recs = advisor.recommend_for_query(
            "SELECT user_id FROM orders WHERE user_id = 20",
            [_seq_scan_finding("orders")],
        )
        assert recs[0].included_columns == ()
        assert recs[0].kind is IndexKind.SINGLE_COLUMN

    def test_oversized_include_falls_back_to_plain_index(
        self, advisor: IndexAdvisor
    ) -> None:
        # More selected columns than the default cap (3): an oversized
        # INCLUDE isn't worth it, so no covering.
        recs = advisor.recommend_for_query(
            "SELECT a, b, c, d, e FROM orders WHERE user_id = 20",
            [_seq_scan_finding("orders")],
        )
        assert recs[0].included_columns == ()
        assert recs[0].kind is IndexKind.SINGLE_COLUMN

    def test_covering_can_be_disabled(self) -> None:
        advisor = IndexAdvisor(max_included_columns=0)
        recs = advisor.recommend_for_query(
            "SELECT id FROM orders WHERE user_id = 20", [_seq_scan_finding("orders")]
        )
        assert recs[0].included_columns == ()


class TestWorkloadDedup:
    def test_identical_indexes_collapse_keeping_max_confidence(
        self, advisor: IndexAdvisor
    ) -> None:
        workload = [
            ("SELECT * FROM users WHERE email = 'a'", [_seq_scan_finding("users")]),
            (
                "SELECT * FROM users WHERE email = 'b'",
                [_seq_scan_finding("users", severity=Severity.MEDIUM)],
            ),
            ("SELECT * FROM users WHERE email = 'c'", [_seq_scan_finding("users")]),
        ]

        recs = advisor.recommend_for_workload(workload)

        assert len(recs) == 1
        assert recs[0].confidence is ConfidenceLevel.HIGH

    def test_distinct_indexes_are_kept_separately(self, advisor: IndexAdvisor) -> None:
        workload = [
            ("SELECT * FROM users WHERE email = 'a'", [_seq_scan_finding("users")]),
            ("SELECT * FROM orders WHERE user_id = 1", [_seq_scan_finding("orders")]),
        ]

        recs = advisor.recommend_for_workload(workload)

        assert {rec.table for rec in recs} == {"users", "orders"}

    def test_different_include_sets_are_distinct_recommendations(
        self, advisor: IndexAdvisor
    ) -> None:
        # Same key column, different covering sets -> two recommendations.
        workload = [
            ("SELECT id FROM orders WHERE user_id = 1", [_seq_scan_finding("orders")]),
            ("SELECT total FROM orders WHERE user_id = 1", [_seq_scan_finding("orders")]),
        ]

        recs = advisor.recommend_for_workload(workload)

        assert len(recs) == 2

    def test_empty_workload_yields_nothing(self, advisor: IndexAdvisor) -> None:
        assert advisor.recommend_for_workload([]) == []