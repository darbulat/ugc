"""A failed recovery/startup must release resources and stay unready."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI

import ugc_bot.telegram_webhook_app as webhook


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["database_read", "worker_start"])
async def test_failed_startup_closes_acquired_resources(
    monkeypatch, failure_stage
):
    failure = RuntimeError("recovery dependency is unavailable")
    config = SimpleNamespace(
        log=SimpleNamespace(log_level="INFO", log_format="json"),
        webhook=SimpleNamespace(
            webhook_base_url="https://fixture.invalid",
            webhook_secret="fixture-only",
        ),
        bot=SimpleNamespace(bot_token="fixture-only"),
        max_bot=SimpleNamespace(token="fixture-only"),
        financial=SimpleNamespace(yookassa_browser_shop_id=None),
    )
    storage = SimpleNamespace(close=AsyncMock())
    # Cleanup errors must not hide the startup failure or skip later cleanup.
    container = SimpleNamespace(dispose=AsyncMock(side_effect=OSError()))
    exchange = SimpleNamespace(close=AsyncMock(side_effect=OSError()))
    texts = SimpleNamespace(
        load_from_db=AsyncMock(
            side_effect=failure if failure_stage == "database_read" else None
        )
    )
    dispatcher = {
        "container": container,
        "exchange_rate_service": exchange,
        "bot_texts_service": texts,
    }
    bot = SimpleNamespace(session=SimpleNamespace(close=AsyncMock()))
    bot_factory = Mock(return_value=bot)
    max_session = SimpleNamespace(close=AsyncMock())
    max_session_factory = Mock(return_value=max_session)
    register = AsyncMock()
    start_workers = Mock(side_effect=failure)
    monkeypatch.setattr(webhook, "load_config", lambda: config)
    monkeypatch.setattr(webhook, "configure_logging", Mock())
    monkeypatch.setattr(webhook, "log_startup_info", Mock())
    monkeypatch.setattr(
        webhook, "create_storage", AsyncMock(return_value=storage)
    )
    monkeypatch.setattr(
        webhook, "build_dispatcher", Mock(return_value=dispatcher)
    )
    monkeypatch.setattr(webhook, "Bot", bot_factory)
    monkeypatch.setattr(webhook, "_set_webhook_with_retry", register)
    monkeypatch.setattr(webhook, "start_checkout_runtime", start_workers)
    monkeypatch.setattr(webhook, "stop_checkout_runtime", AsyncMock())
    monkeypatch.setattr("aiohttp.ClientSession", max_session_factory)

    application = FastAPI()
    with pytest.raises(RuntimeError) as raised:
        async with webhook._lifespan(application):
            pytest.fail("A failed startup must never serve traffic")
    assert raised.value is failure
    storage.close.assert_awaited_once()
    container.dispose.assert_awaited_once()
    exchange.close.assert_awaited_once()
    if failure_stage == "database_read":
        bot_factory.assert_not_called()
        register.assert_not_awaited()
        start_workers.assert_not_called()
        max_session_factory.assert_not_called()
        assert not hasattr(application.state, "dispatcher")
    else:
        bot.session.close.assert_awaited_once()
        max_session.close.assert_awaited_once()
        register.assert_awaited_once()
        start_workers.assert_called_once()
