"""Unit tests for sqlcoach.logging_config."""

from __future__ import annotations

import json
import logging

import pytest

from sqlcoach.exceptions import ConfigError
from sqlcoach.logging_config import configure_logging


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Ensure each test starts from, and restores, a clean root logger."""
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    yield
    root_logger.handlers.clear()
    root_logger.handlers.extend(original_handlers)
    root_logger.setLevel(original_level)


class TestLevelHandling:
    def test_sets_root_logger_level(self) -> None:
        configure_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_level_is_case_insensitive(self) -> None:
        configure_logging(level="warning")
        assert logging.getLogger().level == logging.WARNING

    def test_invalid_level_raises_config_error(self) -> None:
        with pytest.raises(ConfigError):
            configure_logging(level="NOT_A_LEVEL")

    def test_invalid_level_raises_config_error(self) -> None:
        with pytest.raises(ConfigError):
            configure_logging(level="NOT_A_LEVEL")

class TestHandlerIdempotency:
    def test_repeated_calls_do_not_stack_handlers(self) -> None:
        configure_logging(level="INFO")
        first_count = len(logging.getLogger().handlers)
        configure_logging(level="INFO")
        second_count = len(logging.getLogger().handlers)
        assert first_count == second_count

    def test_does_not_remove_unrelated_handlers(self) -> None:
        root_logger = logging.getLogger()
        foreign_handler = logging.NullHandler()
        root_logger.addHandler(foreign_handler)
        try:
            configure_logging(level="INFO")
            assert foreign_handler in root_logger.handlers
        finally:
            root_logger.removeHandler(foreign_handler)


class TestOutputFormats:
    def test_human_readable_format_contains_level_and_message(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(level="INFO", json_output=False)
        logging.getLogger("sqlcoach.test").info("hello world")
        captured = capsys.readouterr()
        assert "INFO" in captured.err
        assert "hello world" in captured.err

    def test_json_format_emits_valid_json_with_expected_keys(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(level="INFO", json_output=True)
        logging.getLogger("sqlcoach.test").info("hello json")
        captured = capsys.readouterr()
        line = captured.err.strip().splitlines()[-1]
        payload = json.loads(line)
        assert payload["level"] == "INFO"
        assert payload["message"] == "hello json"
        assert payload["logger"] == "sqlcoach.test"
        assert "timestamp" in payload


class TestCredentialRedactionIsWiredIn:
    """Proves US2.5 end-to-end: a DSN password never reaches log output,
    through the real configure_logging() entry point, at DEBUG level,
    in both human-readable and JSON modes (NFR-2.5: "under any logging
    mode").
    """

    def test_password_is_redacted_in_human_readable_mode_at_debug_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(level="DEBUG", json_output=False)
        logging.getLogger("sqlcoach.database").debug(
            "Connecting with %s", "postgresql://alice:s3cr3t@localhost/mydb"
        )
        captured = capsys.readouterr()
        assert "s3cr3t" not in captured.err
        assert "***REDACTED***" in captured.err

    def test_password_is_redacted_in_json_mode_at_debug_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        configure_logging(level="DEBUG", json_output=True)
        logging.getLogger("sqlcoach.database").debug(
            "Connecting with %s", "postgresql://alice:s3cr3t@localhost/mydb"
        )
        captured = capsys.readouterr()
        assert "s3cr3t" not in captured.err
        payload = json.loads(captured.err.strip().splitlines()[-1])
        assert "s3cr3t" not in payload["message"]