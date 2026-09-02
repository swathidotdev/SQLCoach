"""Unit tests for sqlcoach.reports.services."""

from __future__ import annotations

import pytest

from sqlcoach.config import Settings
from sqlcoach.exceptions import ValidationError
from sqlcoach.reports.services import (
    NotYetImplementedError,
    analyze_service,
    audit_service,
    compare_service,
    report_service,
)


class TestPlaceholderServicesRaiseNotYetImplemented:
    # analyze_service is implemented as of Sprint 6 and is covered by
    # tests/test_analyze_service.py; the remaining placeholders still
    # signal not-yet-implemented until their sprints.

    def test_audit_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="audit"):
            audit_service(None)

    def test_report_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="report"):
            report_service(None)

    def test_compare_service(self) -> None:
        with pytest.raises(NotYetImplementedError, match="compare"):
            compare_service(None, None)


class TestAnalyzeServiceIsImplemented:
    def test_missing_source_raises_validation_error_not_placeholder(self) -> None:
        # Proves analyze is no longer a placeholder: it validates input
        # rather than raising NotYetImplementedError.
        with pytest.raises(ValidationError):
            analyze_service(None, settings=Settings())


class TestNotYetImplementedErrorType:
    def test_is_a_not_implemented_error_subclass(self) -> None:
        assert issubclass(NotYetImplementedError, NotImplementedError)