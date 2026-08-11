"""SQLCoach exception hierarchy.

All errors raised across SQLCoach's public boundaries must be instances
of :class:`SQLCoachError` or one of its subclasses (NFR-X.3) — raw
third-party or stdlib exceptions must never propagate to the CLI layer.

This module defines a *flat* hierarchy: every domain error inherits
directly from :class:`SQLCoachError` rather than from each other. A
flat hierarchy keeps ``except`` clauses unambiguous and lets later
phases add new subclasses without ever needing to modify this file
(Open/Closed Principle, NFR-1.7).
"""

from __future__ import annotations

from typing import Any


class SQLCoachError(Exception):
    """Base class for all errors raised by SQLCoach.

    Attributes:
        message: Human-readable description of what went wrong.
        details: Optional structured context (e.g. a config key, a
            file path, a query snippet) useful for logging and
            debugging without parsing the message string.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}

    def __str__(self) -> str:
        if not self.details:
            return self.message
        rendered_details = ", ".join(f"{key}={value!r}" for key, value in self.details.items())
        return f"{self.message} ({rendered_details})"


class ConfigError(SQLCoachError):
    """Raised when configuration cannot be loaded or fails validation.

    Covers missing/unreadable config files, malformed TOML, and
    settings values that fail validation (FR-1.6). Introduced for use
    by US1.2 (Configuration System).
    """


class ValidationError(SQLCoachError):
    """Raised when a value fails domain-level validation outside of
    configuration, and no more specific subclass yet exists.
    """


class ParsingError(SQLCoachError):
    """Raised when a SQL file or PostgreSQL log excerpt cannot be
    parsed into `Query` objects.

    Reserved for Sprint 3 (SQL/log parsing); defined now per FR-1.8 so
    the hierarchy is stable before parser code depends on it.
    """


class DatabaseConnectionError(SQLCoachError):
    """Raised when a connection to PostgreSQL cannot be established,
    or a database operation fails in a way that must not leak a raw
    psycopg3/driver exception to callers.

    Reserved for Sprint 2 (database layer); defined now per FR-1.8.
    """
