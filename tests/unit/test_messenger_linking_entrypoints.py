"""Behavioral REDs at the current production routes, without PostgreSQL."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from tests.unit.test_miniapp_auth import _make_valid_init_data
from ugc_bot.miniapp.api import router
from ugc_bot.telegram_webhook_app import app as webhook_app


@pytest.mark.asyncio
async def test_signed_challenge_route_exists_without_auto_registration():
    application = FastAPI()
    application.include_router(router, prefix="/miniapp")
    roles = SimpleNamespace(set_user=AsyncMock())
    application.state.dispatcher = {"user_role_service": roles}
    application.state.config = SimpleNamespace()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/miniapp/api/messenger-links/telegram/challenge",
            json={
                "platform": "max",
                "init_data": _make_valid_init_data("max-token", 321),
                "operation_key": "first",
            },
        )
    assert response.status_code == 503, response.text
    roles.set_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserved_malformed_start_never_reaches_ordinary_dispatch(
    monkeypatch,
):
    class Dispatcher(dict):
        feed_update = AsyncMock()

    dispatcher = Dispatcher()
    for name, value in {
        "config": SimpleNamespace(
            webhook=SimpleNamespace(webhook_secret="synthetic-secret")
        ),
        "dispatcher": dispatcher,
        "bot": SimpleNamespace(
            id=123, token="123:synthetic_token", send_message=AsyncMock()
        ),
        "webhook_semaphore": asyncio.Semaphore(1),
    }.items():
        monkeypatch.setattr(webhook_app.state, name, value, raising=False)
    data = {
        "update_id": 12345,
        "message": {
            "message_id": 1,
            "date": 1792800000,
            "chat": {"id": 7654321, "type": "private"},
            "from": {"id": 7654321, "is_bot": False, "first_name": "New"},
            "text": "/start lk1_!",
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=webhook_app, raise_app_exceptions=False
        ),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/webhook/telegram",
            json=data,
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
        )
        await asyncio.sleep(0)
    assert response.status_code == 200
    dispatcher.feed_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_update_with_reserved_bearer_is_400_without_input_logging(
    monkeypatch, caplog
):
    bearer = "lk1_" + "Q" * 43
    monkeypatch.setattr(
        webhook_app.state,
        "config",
        SimpleNamespace(
            webhook=SimpleNamespace(webhook_secret="synthetic-secret")
        ),
        raising=False,
    )
    monkeypatch.setattr(webhook_app.state, "dispatcher", {}, raising=False)
    monkeypatch.setattr(
        webhook_app.state, "bot", SimpleNamespace(), raising=False
    )
    data = {
        "update_id": 20,
        "message": {"text": "/start " + bearer, "chat": {"id": "invalid"}},
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=webhook_app, raise_app_exceptions=False
        ),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/webhook/telegram",
            json=data,
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
        )
    assert response.status_code == 400
    assert bearer not in caplog.text + response.text


@pytest.mark.parametrize(
    "payload", ["lk1_!", "lk1_" + "A" * 43, "lk1_" + "A" * 43 + " extra"]
)
@pytest.mark.asyncio
async def test_expected_negative_with_real_configured_service_acknowledges_once(
    monkeypatch, payload
):
    from tests.application.services.test_messenger_linking_service import setup

    service, repo, _, _, _ = setup()
    dispatcher = {"messenger_linking_service": service}
    bot = SimpleNamespace(
        id=123, token="123:" + "A" * 35, send_message=AsyncMock()
    )
    for name, value in {
        "config": SimpleNamespace(
            webhook=SimpleNamespace(webhook_secret="synthetic-secret")
        ),
        "dispatcher": dispatcher,
        "bot": bot,
        "webhook_semaphore": asyncio.Semaphore(1),
    }.items():
        monkeypatch.setattr(webhook_app.state, name, value, raising=False)
    data = {
        "update_id": 99,
        "message": {
            "message_id": 20,
            "date": 1792800000,
            "chat": {"id": 777, "type": "private"},
            "from": {"id": 777, "is_bot": False, "first_name": "New"},
            "text": "/start " + payload,
        },
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=webhook_app, raise_app_exceptions=False
        ),
        base_url="http://test",
    ) as client:
        first = await client.post(
            "/webhook/telegram",
            json=data,
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
        )
        replay = await client.post(
            "/webhook/telegram",
            json=data,
            headers={"X-Telegram-Bot-Api-Secret-Token": "synthetic-secret"},
        )
    assert first.status_code == replay.status_code == 200
    assert len(repo.native_attempts) == len(repo.native_results) == 1
    assert len(repo.users) == 1 and not repo.claims


@pytest.mark.parametrize("reserved", [True, False])
@pytest.mark.asyncio
async def test_actual_dispatcher_reserved_precedes_locale_and_pay_stays_native(
    monkeypatch, reserved
):
    from unittest.mock import MagicMock
    from uuid import uuid4

    from aiogram import Bot, Router
    from aiogram.types import Update

    import ugc_bot.app as app_module
    import ugc_bot.bot.telegram.handlers.payments as payments
    from tests.application.services.test_messenger_linking_service import setup
    from ugc_bot.config import AppConfig

    service, repo, actor, _, _ = setup()
    user = repo.users[actor.user_id]
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=user),
        update_telegram=AsyncMock(),
        set_user=AsyncMock(),
    )
    profile = SimpleNamespace(
        get_advertiser_profile=AsyncMock(return_value=SimpleNamespace())
    )
    checkout_boundary = AsyncMock(return_value=True)
    monkeypatch.setattr(payments, "send_checkout_if_v1", checkout_boundary)
    services = {
        "metrics_collector": MagicMock(),
        "messenger_linking_service": service,
        "user_role_service": roles,
        "profile_service": profile,
        "payment_service": SimpleNamespace(),
        "bot_texts_service": SimpleNamespace(
            get_many=AsyncMock(return_value={})
        ),
    }
    monkeypatch.setattr(
        app_module,
        "Container",
        lambda _: SimpleNamespace(build_bot_services=lambda: services),
    )
    # Clone real handlers without changing global Router parents.
    for name, original in list(vars(app_module).items()):
        if name.endswith("_router") and isinstance(original, Router):
            fresh = Router()
            for observer, value in original.observers.items():
                fresh.observers[observer].handlers.extend(value.handlers)
            monkeypatch.setattr(app_module, name, fresh)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "123:" + "A" * 35,
            "DATABASE_URL": "sqlite:///unused-linking-routing",
            "KAFKA_ENABLED": False,
        }
    )
    dispatcher = app_module.build_dispatcher(config)
    bot = Bot(config.bot.bot_token)
    bot.send_message = AsyncMock()
    context = dispatcher.fsm.get_context(bot=bot, chat_id=777, user_id=777)
    await context.set_state("Support:waiting_for_message")
    text = "/start lk1_!" if reserved else "/start pay_" + str(uuid4())
    value = Update.model_validate(
        {
            "update_id": 787,
            "message": {
                "message_id": 22,
                "date": 1792800000,
                "chat": {"id": 777, "type": "private"},
                "from": {
                    "id": 777,
                    "is_bot": False,
                    "first_name": "Actual",
                    "username": "changed",
                },
                "text": text,
            },
        }
    )
    try:
        await dispatcher.feed_update(bot, value)
        roles.set_user.assert_not_awaited()
        if reserved:
            roles.get_user.assert_not_awaited()
            roles.update_telegram.assert_not_awaited()
            assert len(repo.native_attempts) == 1
            assert await context.get_state() == "Support:waiting_for_message"
            checkout_boundary.assert_not_awaited()
        else:
            checkout_boundary.assert_awaited_once()
            assert not repo.native_attempts
    finally:
        await dispatcher.storage.close()
        await bot.session.close()
