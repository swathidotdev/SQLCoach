"""Unit tests for anti-pattern detection foundation + SELECT * (Sprint 8)."""

from __future__ import annotations

import sqlglot
import pytest

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