"""A retiring or failed replica must preserve the surviving bot's webhook."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI

from tests.unit.test_telegram_webhook_app import _test_config
from ugc_bot import telegram_webhook_app as webhook


@pytest.mark.asyncio
@pytest.mark.parametrize("second_fails", [False, True])
async def test_replica_cleanup_preserves_shared_registration(
    monkeypatch, second_fails
):
    shared = {"url": None}
    bots = []

    async def storage(config):
        return MemoryStorage()

    def dispatcher(config, storage):
        result = Dispatcher(storage=storage)
        result["bot_texts_service"] = MagicMock(load_from_db=AsyncMock())
        return result

    def bot_factory(**kwargs):
        bot = MagicMock()
        number = len(bots)

        async def register(url, **kwargs):
            if second_fails and number == 1:
                raise RuntimeError("New replica startup failed")
            shared["url"] = url

        async def delete():
            shared["url"] = None

        bot.set_webhook = AsyncMock(side_effect=register)
        bot.delete_webhook = AsyncMock(side_effect=delete)
        bot.session.close = AsyncMock()
        bots.append(bot)
        return bot

    monkeypatch.setattr(webhook, "load_config", _test_config)
    monkeypatch.setattr(webhook, "create_storage", storage)
    monkeypatch.setattr(webhook, "build_dispatcher", dispatcher)
    monkeypatch.setattr(webhook, "Bot", bot_factory)

    async with webhook._lifespan(FastAPI()):
        expected = shared["url"]
        assert expected == "https://test.example.com/webhook/telegram"
        if second_fails:
            with pytest.raises(RuntimeError, match="startup failed"):
                async with webhook._lifespan(FastAPI()):
                    pass
        else:
            async with webhook._lifespan(FastAPI()):
                assert shared["url"] == expected
        assert shared["url"] == expected
        bots[1].session.close.assert_awaited_once()
        bots[0].session.close.assert_not_awaited()

    assert shared["url"] == expected
    for bot in bots:
        bot.delete_webhook.assert_not_awaited()
        bot.session.close.assert_awaited_once()
