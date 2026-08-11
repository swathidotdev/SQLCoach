"""Unit tests for sqlcoach.config."""

from __future__ import annotations

import logging
import pytest
from pathlib import Path

from pydantic import json

from sqlcoach.config import Settings, load_settings
from sqlcoach.exceptions import ConfigError
from sqlcoach.logging_config import configure_logging


class TestDefaults:
    def test_defaults_when_no_file_and_no_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SQLCOACH_LOG_LEVEL", raising=False)
        monkeypatch.delenv("SQLCOACH_JSON_LOGS", raising=False)
        missing_path = tmp_path / "does_not_exist.toml"

        settings = load_settings(missing_path)

        assert settings.log_level == "INFO"
        assert settings.json_logs is False


class TestFileLoading:
    def test_loads_values_from_toml_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SQLCOACH_LOG_LEVEL", raising=False)
        monkeypatch.delenv("SQLCOACH_JSON_LOGS", raising=False)
        config_file = tmp_path / "sqlcoach.toml"
        config_file.write_text('log_level = "debug"\njson_logs = true\n')

        settings = load_settings(config_file)

        assert settings.log_level == "DEBUG"
        assert settings.json_logs is True

    def test_malformed_toml_raises_config_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sqlcoach.toml"
        config_file.write_text("this is not [ valid toml")

        with pytest.raises(ConfigError):
            load_settings(config_file)

    def test_invalid_log_level_raises_config_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SQLCOACH_LOG_LEVEL", raising=False)
        config_file = tmp_path / "sqlcoach.toml"
        config_file.write_text('log_level = "NOT_A_LEVEL"\n')

        with pytest.raises(ConfigError):
            load_settings(config_file)

    def test_unknown_key_raises_config_error(self, tmp_path: Path) -> None:
        config_file = tmp_path / "sqlcoach.toml"
        config_file.write_text('unknown_setting = "oops"\n')

        with pytest.raises(ConfigError):
            load_settings(config_file)


class TestEnvOverrides:
    def test_env_var_overrides_file_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "sqlcoach.toml"
        config_file.write_text('log_level = "warning"\n')
        monkeypatch.setenv("SQLCOACH_LOG_LEVEL", "error")
        monkeypatch.delenv("SQLCOACH_JSON_LOGS", raising=False)

        settings = load_settings(config_file)

        assert settings.log_level == "ERROR"

    @pytest.mark.parametrize(
        "raw_value,expected",
        [
            ("1", True),
            ("true", True),
            ("YES", True),
            ("0", False),
            ("false", False),
            ("", False),
        ],
    )
    def test_json_logs_env_var_truthy_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        raw_value: str,
        expected: bool,
    ) -> None:
        monkeypatch.delenv("SQLCOACH_LOG_LEVEL", raising=False)
        monkeypatch.setenv("SQLCOACH_JSON_LOGS", raw_value)
        missing_path = tmp_path / "does_not_exist.toml"

        settings = load_settings(missing_path)

        assert settings.json_logs is expected


class TestSettingsImmutability:
    def test_settings_is_frozen(self) -> None:
        settings = Settings()
        with pytest.raises(Exception):
            settings.log_level = "DEBUG"  # type: ignore[misc]

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