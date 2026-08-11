"""Unit tests for sqlcoach.reports.services."""

from __future__ import annotations

import pytest

from sqlcoach.reports.services import (
    NotYetImplementedError,
    analyze_service,
    audit_service,
    compare_service,
    report_service,
)


class TestPlaceholderServicesRaiseNotYetImplemented:
    def test_analyze_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="analyze"):
            analyze_service(None)

    def test_audit_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="audit"):
            audit_service(None)

    def test_report_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="report"):
            report_service(None)

    def test_compare_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="compare"):
            compare_service(None, None)


class TestNotYetImplementedErrorType:
    def test_is_a_not_implemented_error_subclass(self) -> None:
        assert issubclass(NotYetImplementedError, NotImplementedError)