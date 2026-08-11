"""Placeholder application services for CLI commands.

These functions are the seam between the CLI (`cli/main.py`) and real
business logic. Right now each one only signals "not implemented yet";
concrete implementations land in later sprints as noted per function.
Keeping this indirection in place now -- rather than having the CLI
print a literal string directly -- means Sprint 3+ can replace a
function body here without ever touching the CLI layer (NFR-X.2,
FR-2.10).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class NotYetImplementedError(NotImplementedError):
    """Raised by a placeholder service to signal a command whose real
    logic has not been implemented yet.

    The CLI layer catches this and turns it into a clean, user-facing
    message rather than a stack trace. Deliberately a subclass of the
    stdlib `NotImplementedError` rather than `SQLCoachError`: this
    condition is temporary scaffolding, not a genuine domain error.
    """


def analyze_service(source: Optional[Path]) -> None:
    """Placeholder for the `analyze` command's business logic.

    Real implementation lands across Sprints 3-9 (parsing, plan
    analysis, index advisor, anti-patterns, recommendation engine).
    """
    raise NotYetImplementedError("analyze")


def audit_service(db_url: Optional[str]) -> None:
    """Placeholder for the `audit` command's business logic.

    Real implementation lands in Sprint 11.
    """
    raise NotYetImplementedError("audit")


def report_service(output: Optional[Path]) -> None:
    """Placeholder for the `report` command's business logic.

    Real implementation lands alongside the recommendation engine
    (Sprint 9) and HTML report generation.
    """
    raise NotYetImplementedError("report")


def compare_service(before: Optional[Path], after: Optional[Path]) -> None:
    """Placeholder for the `compare` command's business logic.

    Real implementation lands in Sprint 10.
    """
    raise NotYetImplementedError("compare")