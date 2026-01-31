"""Tests for configuration loading."""

import pytest

from ugc_bot.config import AppConfig, load_config


def test_is_flat_dict_returns_false_for_non_dict() -> None:
    """_is_flat_dict returns False for non-dict (e.g. list)."""
    from ugc_bot.config import _is_flat_dict

    assert _is_flat_dict([]) is False
    assert _is_flat_dict(None) is False


def test_app_config_accepts_nested_dict() -> None:
    """AppConfig.model_validate accepts nested dict (not flat env-style)."""
    nested = {
        "bot": {"BOT_TOKEN": "token"},
        "log": {"LOG_LEVEL": "INFO", "LOG_FORMAT": "text"},
        "db": {"DATABASE_URL": "postgresql://localhost/db"},
        "admin": {"ADMIN_USERNAME": "a", "ADMIN_PASSWORD": "p", "ADMIN_SECRET": "s"},
        "kafka": {"KAFKA_ENABLED": "false"},
        "feedback": {"FEEDBACK_ENABLED": "false"},
        "role_reminder": {"ROLE_REMINDER_ENABLED": "false"},
        "redis": {"REDIS_URL": "redis://localhost", "USE_REDIS_STORAGE": "false"},
        "instagram": {
            "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "v",
            "INSTAGRAM_APP_SECRET": "s",
        },
        "docs": {"DOCS_OFFER_URL": "", "DOCS_PRIVACY_URL": "", "DOCS_CONSENT_URL": ""},
    }
    config = AppConfig.model_validate(nested)
    assert config.bot.bot_token == "token"
    assert config.db.database_url == "postgresql://localhost/db"


def test_load_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load config from environment variables."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    config = load_config()

    assert config.bot.bot_token == "token"
    assert config.log.log_level == "DEBUG"
    assert config.db.database_url == "postgresql://test"


def test_log_config_normalizes_log_level() -> None:
    """LogConfig normalizes log_level (strip and upper)."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "db",
            "LOG_LEVEL": "  warn  ",
            "LOG_FORMAT": "text",
        }
    )
    assert config.log.log_level == "WARN"
