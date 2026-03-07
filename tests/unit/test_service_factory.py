"""Tests for service_factory (stats collector deps, aiograpi fetcher)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ugc_bot.application.services.instagram_stats_collector_service import (
    InstagramStatsCollectorService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container.service_factory import (
    _build_aiograpi_fetcher,
    build_instagram_stats_collector_scheduler_deps,
)


def test_build_instagram_stats_collector_scheduler_deps_returns_deps() -> None:
    """Stats collector scheduler deps returns service and interval_seconds."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token",
            "DATABASE_URL": "sqlite:///:memory:",
        }
    )
    repos = {
        "blogger_repo": MagicMock(),
        "instagram_stats_repo": MagicMock(),
    }
    tm = MagicMock()
    stats_client = MagicMock()

    deps = build_instagram_stats_collector_scheduler_deps(
        config, repos, tm, stats_client
    )

    assert "instagram_stats_collector_service" in deps
    assert "interval_seconds" in deps
    assert isinstance(
        deps["instagram_stats_collector_service"],
        InstagramStatsCollectorService,
    )
    assert deps["interval_seconds"] == 86400


def test_build_aiograpi_fetcher_returns_none_when_no_credentials() -> None:
    """_build_aiograpi_fetcher returns None when username/password empty."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "db",
            "INSTAGRAM_STATS_AIOGRAPI_USERNAME": "",
            "INSTAGRAM_STATS_AIOGRAPI_PASSWORD": "",
        }
    )
    assert _build_aiograpi_fetcher(config) is None


def test_build_aiograpi_fetcher_returns_instance_when_patched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_aiograpi_fetcher returns fetcher when credentials set."""
    monkeypatch.setenv("INSTAGRAM_STATS_AIOGRAPI_USERNAME", "u")
    monkeypatch.setenv("INSTAGRAM_STATS_AIOGRAPI_PASSWORD", "p")
    config = AppConfig.model_validate({"BOT_TOKEN": "t", "DATABASE_URL": "db"})

    class FakeAiograpiFetcher:
        def __init__(
            self,
            instagram_username: str,
            instagram_password: str,
            session_path: Path | None = None,
        ) -> None:
            self.instagram_username = instagram_username
            self.instagram_password = instagram_password
            self.session_path = session_path

    mock_module = MagicMock()
    mock_module.AiograpiStatsFetcher = FakeAiograpiFetcher
    with patch.dict(
        sys.modules,
        {
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher": (
                mock_module
            ),
        },
    ):
        result = _build_aiograpi_fetcher(config)

    assert result is not None
    assert result.instagram_username == "u"
    assert result.instagram_password == "p"
    assert result.session_path is None


def test_build_aiograpi_fetcher_uses_session_path_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_aiograpi_fetcher passes session_path when configured."""
    monkeypatch.setenv("INSTAGRAM_STATS_AIOGRAPI_USERNAME", "u")
    monkeypatch.setenv("INSTAGRAM_STATS_AIOGRAPI_PASSWORD", "p")
    monkeypatch.setenv("INSTAGRAM_STATS_AIOGRAPI_SESSION_PATH", "/tmp/session")
    config = AppConfig.model_validate({"BOT_TOKEN": "t", "DATABASE_URL": "db"})

    class FakeAiograpiFetcher:
        def __init__(
            self,
            instagram_username: str,
            instagram_password: str,
            session_path: Path | None = None,
        ) -> None:
            self.session_path = session_path

    mock_module = MagicMock()
    mock_module.AiograpiStatsFetcher = FakeAiograpiFetcher
    with patch.dict(
        sys.modules,
        {
            "ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher": (
                mock_module
            ),
        },
    ):
        result = _build_aiograpi_fetcher(config)

    assert result is not None
    assert result.session_path == Path("/tmp/session")
