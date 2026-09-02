"""Configuration system for SQLCoach.

Configuration precedence (lowest to highest): built-in defaults ->
`sqlcoach.toml` file -> environment variables. This matches common CLI
tool conventions and satisfies FR-1.4 and FR-1.5.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError as PydanticValidationError,
    field_validator,
)

from sqlcoach.exceptions import ConfigError

DEFAULT_CONFIG_FILENAME = "sqlcoach.toml"

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

_ENV_VAR_PREFIX = "SQLCOACH_"

# Analyzer threshold defaults, named so both Settings (user-facing
# defaults) and AnalysisContext (test-convenience defaults) reference
# one source of truth rather than duplicating literals.
DEFAULT_SEQ_SCAN_ROW_THRESHOLD = 10_000
DEFAULT_NESTED_LOOP_ROW_THRESHOLD = 10_000
DEFAULT_CARDINALITY_MISESTIMATION_RATIO = 10.0
DEFAULT_CARDINALITY_MIN_ROWS = 100


class Settings(BaseModel):
    """SQLCoach runtime configuration.

    Attributes:
        log_level: Minimum log level to emit. One of DEBUG, INFO,
            WARNING, ERROR, CRITICAL.
        json_logs: When True, emit structured JSON log lines instead
            of human-readable text (mirrors the CLI's --json-logs
            flag; a file/env value lets it be set without the flag).
        seq_scan_row_threshold: A sequential scan returning at least
            this many rows is flagged by the execution-plan analyzer as
            a candidate for indexing (FR-3.4.1). Must be at least 1.
        nested_loop_row_threshold: A nested-loop join whose outer side
            drives at least this many inner-side iterations is flagged
            as a likely bottleneck (FR-3.4.2). Must be at least 1.
        cardinality_misestimation_ratio: A plan node whose estimated and
            actual row counts differ by at least this factor (in either
            direction) is flagged as a cardinality misestimation
            (FR-3.4.4). Must be greater than 1.
        cardinality_min_rows: A cardinality misestimation is only
            flagged when the larger of the estimated/actual row counts
            reaches at least this value, suppressing noise from tiny
            absolute counts (e.g. 1 vs 12 rows). Set to 0 to disable the
            floor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    log_level: str = "INFO"
    json_logs: bool = False
    seq_scan_row_threshold: int = Field(default=DEFAULT_SEQ_SCAN_ROW_THRESHOLD, ge=1)
    nested_loop_row_threshold: int = Field(default=DEFAULT_NESTED_LOOP_ROW_THRESHOLD, ge=1)
    cardinality_misestimation_ratio: float = Field(
        default=DEFAULT_CARDINALITY_MISESTIMATION_RATIO, gt=1.0
    )
    cardinality_min_rows: int = Field(default=DEFAULT_CARDINALITY_MIN_ROWS, ge=0)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in _VALID_LOG_LEVELS:
            valid = ", ".join(sorted(_VALID_LOG_LEVELS))
            raise ValueError(f"log_level must be one of: {valid} (got {value!r})")
        return normalized


def _read_toml_file(path: Path) -> dict[str, Any]:
    """Read and parse a TOML config file, raising ConfigError on failure."""
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"Config file at {path} is not valid TOML",
            details={"path": str(path), "parse_error": str(exc)},
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"Config file at {path} could not be read",
            details={"path": str(path), "os_error": str(exc)},
        ) from exc


def _read_env_overrides() -> dict[str, Any]:
    """Collect environment variable overrides for known Settings fields.

    Recognized variables: SQLCOACH_LOG_LEVEL, SQLCOACH_JSON_LOGS,
    SQLCOACH_SEQ_SCAN_ROW_THRESHOLD, SQLCOACH_NESTED_LOOP_ROW_THRESHOLD,
    SQLCOACH_CARDINALITY_MISESTIMATION_RATIO, SQLCOACH_CARDINALITY_MIN_ROWS.
    """
    overrides: dict[str, Any] = {}

    raw_log_level = os.environ.get(f"{_ENV_VAR_PREFIX}LOG_LEVEL")
    if raw_log_level is not None:
        overrides["log_level"] = raw_log_level

    raw_json_logs = os.environ.get(f"{_ENV_VAR_PREFIX}JSON_LOGS")
    if raw_json_logs is not None:
        overrides["json_logs"] = raw_json_logs.strip().lower() in {"1", "true", "yes", "on"}

    raw_seq_scan_threshold = os.environ.get(f"{_ENV_VAR_PREFIX}SEQ_SCAN_ROW_THRESHOLD")
    if raw_seq_scan_threshold is not None:
        # Passed through as-is; Pydantic coerces and validates it, and a
        # bad value surfaces as a ConfigError via load_settings' handler.
        overrides["seq_scan_row_threshold"] = raw_seq_scan_threshold

    raw_nested_loop_threshold = os.environ.get(
        f"{_ENV_VAR_PREFIX}NESTED_LOOP_ROW_THRESHOLD"
    )
    if raw_nested_loop_threshold is not None:
        overrides["nested_loop_row_threshold"] = raw_nested_loop_threshold

    raw_cardinality_ratio = os.environ.get(
        f"{_ENV_VAR_PREFIX}CARDINALITY_MISESTIMATION_RATIO"
    )
    if raw_cardinality_ratio is not None:
        overrides["cardinality_misestimation_ratio"] = raw_cardinality_ratio

    raw_cardinality_min_rows = os.environ.get(
        f"{_ENV_VAR_PREFIX}CARDINALITY_MIN_ROWS"
    )
    if raw_cardinality_min_rows is not None:
        overrides["cardinality_min_rows"] = raw_cardinality_min_rows

    return overrides


def load_settings(config_path: Path | None = None) -> Settings:
    """Load SQLCoach settings with defaults < file < environment precedence.

    Args:
        config_path: Explicit path to a TOML config file. If omitted,
            defaults to `./sqlcoach.toml`. If the file does not exist,
            it is silently skipped (defaults apply) -- this is expected
            usage, not an error (FR-1.4).

    Returns:
        A validated, immutable Settings instance.

    Raises:
        ConfigError: If the config file exists but is unreadable or
            malformed, or if the resulting values fail validation.
    """
    path = config_path or Path(DEFAULT_CONFIG_FILENAME)

    file_values: dict[str, Any] = {}
    if path.exists():
        file_values = _read_toml_file(path)

    env_values = _read_env_overrides()
    merged = {**file_values, **env_values}

    try:
        return Settings(**merged)
    except PydanticValidationError as exc:
        raise ConfigError(
            "Invalid configuration values",
            details={"errors": exc.errors(include_url=False)},
        ) from exc