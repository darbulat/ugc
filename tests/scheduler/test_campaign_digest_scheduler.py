"""The production cutover never constructs the retired per-author sender."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ugc_bot import campaign_digest_scheduler as module
from ugc_bot.config import AppConfig
from ugc_bot.container import Container


@pytest.mark.asyncio
@pytest.mark.parametrize("feedback,digest", [(False, True), (True, False)])
async def test_disabled_runtime_never_constructs_transport(
    feedback, digest, monkeypatch
):
    config = SimpleNamespace(
        feedback=SimpleNamespace(
            feedback_enabled=feedback, campaign_digest_enabled=digest
        )
    )
    container = Mock()
    monkeypatch.setattr(
        module.aiohttp,
        "ClientSession",
        Mock(side_effect=AssertionError("disabled")),
    )
    await module.run_enabled(config, container, object(), max_iterations=1)
    assert not container.mock_calls


def test_default_off_factory_needs_no_database_or_transport():
    config = AppConfig.model_validate({"BOT_TOKEN": "synthetic"})
    assert config.feedback.campaign_digest_enabled is False
    assert Container(config).build_campaign_digest(object()) is None


@pytest.mark.asyncio
async def test_enabled_loop_owns_resources_and_safe_failure_logs(
    monkeypatch, caplog
):
    calls = []

    class Owned:
        async def __aenter__(self):
            calls.append("enter")
            return self

        async def __aexit__(self, *args):
            calls.append("exit")

    worker = SimpleNamespace(
        run_once=AsyncMock(side_effect=[RuntimeError("private recipient"), 0])
    )
    container = SimpleNamespace(build_campaign_digest=Mock(return_value=worker))
    config = SimpleNamespace(
        feedback=SimpleNamespace(
            feedback_enabled=True,
            campaign_digest_enabled=True,
            feedback_poll_interval_seconds=17,
        ),
        max_bot=SimpleNamespace(token="synthetic"),
    )
    monkeypatch.setattr(module.aiohttp, "ClientSession", Owned)
    sleep = AsyncMock()
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    await module.run_enabled(config, container, object(), max_iterations=2)
    assert worker.run_once.await_count == 2
    sleep.assert_awaited_once_with(17)
    assert calls == ["enter", "exit"]
    assert "private recipient" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("interval,iterations", [(0, 1), (-1, 1), (1, 0)])
async def test_invalid_bounds_never_start(interval, iterations):
    with pytest.raises(ValueError, match="digest_loop_bounds_invalid"):
        await module.run_loop(
            None, interval_seconds=interval, max_iterations=iterations
        )


@pytest.mark.asyncio
async def test_missing_worker_exits_and_enabled_factory_needs_database():
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic",
            "FEEDBACK_ENABLED": True,
            "CAMPAIGN_DIGEST_ENABLED": True,
        }
    )
    config.db.database_url = ""
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Container(config).build_campaign_digest(object())
    await module.run_enabled(
        config,
        SimpleNamespace(build_campaign_digest=Mock(return_value=None)),
        object(),
        max_iterations=1,
    )


@pytest.mark.parametrize(
    "limit,lease", [(0, 120), (1001, 120), (True, 120), (1, 0)]
)
@pytest.mark.asyncio
async def test_worker_rejects_unbounded_runs(limit, lease):
    from ugc_bot.application.services.campaign_digest_service import (
        CampaignDigestService,
    )

    service = CampaignDigestService(None, None, None, None, {}, lease)
    with pytest.raises(ValueError, match="digest_worker_bounds_invalid"):
        await service.run_once(limit=limit)
