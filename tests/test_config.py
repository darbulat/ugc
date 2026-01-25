"""Tests for configuration loading."""

import pytest

from ugc_bot.config import AppConfig, load_config


def test_load_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load config from environment variables."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    config = load_config()

    assert config.bot_token == "token"
    assert config.log_level == "DEBUG"
    assert config.database_url == "postgresql://test"


def test_config_validate_bot_token_empty() -> None:
    """Validate that empty bot token raises error."""

    with pytest.raises(ValueError, match="BOT_TOKEN is required"):
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "   ",
                "DATABASE_URL": "postgresql://test",
            }
        )


def test_config_validate_bot_token_none() -> None:
    """Validate that missing bot token raises error."""

    with pytest.raises(ValueError):
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "",
                "DATABASE_URL": "postgresql://test",
            }
        )
