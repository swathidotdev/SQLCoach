"""Unit tests for sqlcoach.analyzer.base."""

from __future__ import annotations

import pytest

from sqlcoach.analyzer.base import AnalysisContext, Finding, PlanDetector, Severity
from sqlcoach.config import Settings
from sqlcoach.models.execution_plan import PlanNode


class TestFinding:
    def test_metrics_preserve_int_and_float_types(self) -> None:
        finding = Finding(
            code="X",
            detector="d",
            severity=Severity.HIGH,
            summary="s",
            node_type="Seq Scan",
            metrics={"rows_scanned": 500_000, "ratio": 12.5},
        )
        assert finding.metrics["rows_scanned"] == 500_000
        assert isinstance(finding.metrics["rows_scanned"], int)
        assert isinstance(finding.metrics["ratio"], float)

    def test_is_frozen(self) -> None:
        finding = Finding(
            code="X", detector="d", severity=Severity.LOW, summary="s", node_type="Sort"
        )
        with pytest.raises(Exception):
            finding.code = "Y"  # type: ignore[misc]


class TestAnalysisContext:
    def test_from_settings_maps_threshold(self) -> None:
        settings = Settings(seq_scan_row_threshold=25_000)
        context = AnalysisContext.from_settings(settings)
        assert context.seq_scan_row_threshold == 25_000

    def test_rejects_threshold_below_one(self) -> None:
        with pytest.raises(Exception):
            AnalysisContext(seq_scan_row_threshold=0)


class TestPlanDetectorProtocol:
    def test_a_conforming_object_satisfies_the_protocol(self) -> None:
        class Dummy:
            name = "dummy"

            def detect(self, node: PlanNode, context: AnalysisContext) -> list[Finding]:
                return []

        assert isinstance(Dummy(), PlanDetector)