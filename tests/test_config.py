"""Tests for configuration loading."""

import pytest

from ugc_bot.config import load_config


def test_load_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load config from environment variables."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    config = load_config()

    assert config.bot.bot_token == "token"
    assert config.log.log_level == "DEBUG"
    assert config.db.database_url == "postgresql://test"
