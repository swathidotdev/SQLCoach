"""Unit tests for anti-pattern detection foundation + SELECT * (Sprint 8)."""

from __future__ import annotations

import sqlglot
import pytest
from sqlcoach.advisor.anti_patterns.leading_wildcard_like import LeadingWildcardLikeDetector
from sqlcoach.advisor.anti_patterns.n_plus_one import NPlusOneDetector
from sqlcoach.advisor.anti_patterns.order_by_random import OrderByRandomDetector
from sqlcoach.advisor.anti_patterns.analyzer import AntiPatternAnalyzer, default_detectors
from sqlcoach.advisor.anti_patterns.base import (
    AntiPatternDetector,
    AntiPatternFinding,
    ParsedQuery,
)
from sqlcoach.advisor.anti_patterns.select_star import SelectStarDetector
from sqlcoach.analyzer.base import Severity
from sqlcoach.models.query import Query, QuerySource


def _q(text: str, location: str = "q.sql:line 1") -> Query:
    return Query(text=text, source=QuerySource.SQL_FILE, source_location=location)

def _pq(sql: str) -> ParsedQuery:
    return ParsedQuery(_q(sql), sqlglot.parse_one(sql, read="postgres"))

class TestSelectStar:
    def test_flags_bare_star_with_details(self) -> None:
        statement = sqlglot.parse_one("SELECT * FROM users", read="postgres")
        findings = SelectStarDetector().detect(
            [ParsedQuery(_q("SELECT * FROM users"), statement)]
        )

        assert len(findings) == 1
        finding = findings[0]
        assert finding.code == "SELECT_STAR"
        assert finding.detector == "select_star"
        assert finding.severity is Severity.LOW
        assert finding.relation_name == "users"
        assert finding.source_location == "q.sql:line 1"

    def test_flags_via_analyzer(self) -> None:
        findings = AntiPatternAnalyzer().analyze([_q("SELECT * FROM users WHERE id = 1")])
        assert [f.code for f in findings] == ["SELECT_STAR"]

    def test_qualified_star_is_flagged(self) -> None:
        findings = AntiPatternAnalyzer().analyze([_q("SELECT o.* FROM orders o")])
        assert len(findings) == 1

    def test_union_arm_star_is_flagged(self) -> None:
        findings = AntiPatternAnalyzer().analyze(
            [_q("SELECT * FROM a UNION SELECT id FROM b")]
        )
        assert len(findings) == 1


class TestNoFalsePositives:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT id, name FROM users",
            "SELECT COUNT(*) FROM users",
            "SELECT max(amount) FROM orders",
            "SELECT id FROM (SELECT * FROM t) s",  # star only in a subquery
        ],
    )
    def test_clean_queries_are_not_flagged(self, sql: str) -> None:
        assert AntiPatternAnalyzer().analyze([_q(sql)]) == []

    def test_unparseable_query_is_skipped(self) -> None:
        assert AntiPatternAnalyzer().analyze([_q("SELCT broken !!")]) == []


class TestArchitecture:
    def test_default_registry_includes_select_star(self) -> None:
        assert "select_star" in {d.name for d in default_detectors()}

    def test_select_star_conforms_to_the_protocol(self) -> None:
        assert isinstance(SelectStarDetector(), AntiPatternDetector)

    def test_a_new_detector_needs_no_analyzer_change(self) -> None:
        # OCP: a brand-new detector runs through the unmodified analyzer.
        class TruncateDetector:
            name = "truncate"

            def detect(self, parsed_queries):
                findings = []
                for parsed in parsed_queries:
                    if parsed.statement is not None and "TRUNCATE" in parsed.query.text.upper():
                        findings.append(
                            AntiPatternFinding(
                                code="TRUNCATE",
                                detector=self.name,
                                severity=Severity.HIGH,
                                summary="truncate",
                            )
                        )
                return findings

        findings = AntiPatternAnalyzer(detectors=[TruncateDetector()]).analyze(
            [_q("TRUNCATE TABLE t")]
        )
        assert [f.code for f in findings] == ["TRUNCATE"]

    def test_the_ast_is_parsed_once_and_shared_across_detectors(self) -> None:
        # Two detectors both receive the same pre-parsed statement object,
        # proving parsing happens once in the analyzer, not per detector.
        seen = []

        class Spy:
            name = "spy"

            def detect(self, parsed_queries):
                seen.append(parsed_queries[0].statement)
                return []

        AntiPatternAnalyzer(detectors=[Spy(), Spy()]).analyze([_q("SELECT * FROM t")])
        assert seen[0] is seen[1]


class TestLeadingWildcardLike:
    def test_leading_wildcard_is_flagged(self) -> None:
        findings = LeadingWildcardLikeDetector().detect(
            [_pq("SELECT id FROM t WHERE name LIKE '%john'")]
        )
        assert len(findings) == 1
        assert findings[0].code == "LEADING_WILDCARD_LIKE"
        assert findings[0].detector == "leading_wildcard_like"
        assert findings[0].severity is Severity.MEDIUM

    def test_ilike_is_flagged(self) -> None:
        findings = LeadingWildcardLikeDetector().detect(
            [_pq("SELECT 1 FROM t WHERE a ILIKE '%x'")]
        )
        assert len(findings) == 1

    def test_trailing_wildcard_is_not_flagged(self) -> None:
        assert LeadingWildcardLikeDetector().detect(
            [_pq("SELECT 1 FROM t WHERE a LIKE 'john%'")]
        ) == []

    def test_parameterized_like_is_not_flagged(self) -> None:
        # The pattern is a bind parameter -- can't tell statically.
        assert LeadingWildcardLikeDetector().detect(
            [_pq("SELECT 1 FROM t WHERE a LIKE $1")]
        ) == []

    def test_two_columns_yield_two_findings(self) -> None:
        findings = LeadingWildcardLikeDetector().detect(
            [_pq("SELECT 1 FROM t WHERE a LIKE '%x' AND b LIKE '%y'")]
        )
        assert len(findings) == 2

    def test_same_column_is_deduped(self) -> None:
        findings = LeadingWildcardLikeDetector().detect(
            [_pq("SELECT 1 FROM t WHERE a LIKE '%x' OR a LIKE '%y'")]
        )
        assert len(findings) == 1


class TestOrderByRandom:
    def test_random_is_flagged(self) -> None:
        findings = OrderByRandomDetector().detect(
            [_pq("SELECT * FROM t ORDER BY RANDOM()")]
        )
        assert len(findings) == 1
        assert findings[0].code == "ORDER_BY_RANDOM"
        assert findings[0].severity is Severity.MEDIUM

    def test_lowercase_random_with_limit_is_flagged(self) -> None:
        assert len(
            OrderByRandomDetector().detect([_pq("SELECT * FROM t ORDER BY random() LIMIT 5")])
        ) == 1

    def test_ordinary_order_by_is_not_flagged(self) -> None:
        assert OrderByRandomDetector().detect(
            [_pq("SELECT * FROM t ORDER BY created_at DESC")]
        ) == []


class TestCombinedAndNegativeFixture:
    def test_all_three_detectors_fire_on_one_query(self) -> None:
        codes = {
            f.code
            for f in AntiPatternAnalyzer().analyze(
                [_q("SELECT * FROM users WHERE name LIKE '%x' ORDER BY RANDOM()")]
            )
        }
        assert codes == {"SELECT_STAR", "LEADING_WILDCARD_LIKE", "ORDER_BY_RANDOM"}

    def test_clean_workload_produces_zero_findings(self) -> None:
        # The DoD's negative-fixture bar: no false positives on clean SQL.
        clean = [
            "SELECT id, name FROM users WHERE email = 'a@b.com'",
            "SELECT COUNT(*) FROM orders WHERE user_id = 5",
            "SELECT id FROM t WHERE name LIKE 'john%'",
            "SELECT id FROM t ORDER BY created_at DESC",
            "SELECT o.id FROM orders o JOIN users u ON u.id = o.user_id WHERE o.status = 1",
        ]
        assert AntiPatternAnalyzer().analyze([_q(s) for s in clean]) == []

    def test_registry_has_all_detectors(self) -> None:
        assert {d.name for d in default_detectors()} == {
            "select_star",
            "leading_wildcard_like",
            "order_by_random",
            "n_plus_one",
        }


class TestNPlusOne:
    def test_flags_repeated_near_identical_queries(self) -> None:
        detector = NPlusOneDetector(min_occurrences=5)
        findings = detector.detect(
            [_pq(f"SELECT * FROM orders WHERE user_id = {i}") for i in range(1, 6)]
        )

        assert len(findings) == 1
        finding = findings[0]
        assert finding.code == "N_PLUS_ONE"
        assert finding.detector == "n_plus_one"
        assert finding.severity is Severity.MEDIUM
        assert finding.metrics["occurrences"] == 5
        assert finding.relation_name == "orders"

    def test_below_threshold_is_not_flagged(self) -> None:
        detector = NPlusOneDetector(min_occurrences=5)
        assert (
            detector.detect(
                [_pq(f"SELECT * FROM orders WHERE user_id = {i}") for i in range(1, 5)]
            )
            == []
        )

    def test_formatting_and_value_variance_still_clusters(self) -> None:
        detector = NPlusOneDetector(min_occurrences=2)
        findings = detector.detect(
            [
                _pq("SELECT * FROM orders WHERE user_id = 1"),
                _pq("select   *  from orders  where user_id = 2"),
            ]
        )
        assert len(findings) == 1

    def test_structurally_different_queries_do_not_cluster(self) -> None:
        detector = NPlusOneDetector(min_occurrences=2)
        assert (
            detector.detect(
                [
                    _pq("SELECT * FROM a WHERE x = 1"),
                    _pq("SELECT * FROM b WHERE y = 2"),
                    _pq("SELECT id FROM c"),
                ]
            )
            == []
        )

    def test_configurable_threshold_via_registry(self) -> None:
        analyzer = AntiPatternAnalyzer(
            detectors=default_detectors(n_plus_one_min_occurrences=3)
        )
        codes = {
            f.code
            for f in analyzer.analyze(
                [_q(f"SELECT name FROM users WHERE id = {i}") for i in range(3)]
            )
        }
        assert "N_PLUS_ONE" in codes

    def test_registry_includes_n_plus_one(self) -> None:
        assert "n_plus_one" in {d.name for d in default_detectors()}