"""Unit tests for sqlcoach.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from sqlcoach.config import Settings, load_settings
from sqlcoach.exceptions import ConfigError


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



class TestCoveringIndexSetting:
    def test_default(self) -> None:
        assert Settings().covering_index_max_included_columns == 3

    def test_rejects_negative(self) -> None:
        with pytest.raises(Exception):
            Settings(covering_index_max_included_columns=-1)

    def test_env_override(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        monkeypatch.setenv("SQLCOACH_COVERING_INDEX_MAX_INCLUDED_COLUMNS", "5")
        assert load_settings().covering_index_max_included_columns == 5



class TestNPlusOneSetting:
    def test_default(self) -> None:
        assert Settings().n_plus_one_min_occurrences == 5

    def test_rejects_below_two(self) -> None:
        with pytest.raises(Exception):
            Settings(n_plus_one_min_occurrences=1)

    def test_env_override(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        monkeypatch.setenv("SQLCOACH_N_PLUS_ONE_MIN_OCCURRENCES", "10")
        assert load_settings().n_plus_one_min_occurrences == 10