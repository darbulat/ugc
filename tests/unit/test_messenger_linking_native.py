"""Only trusted native private messages yield operational linking proposals."""

import importlib
import importlib.util
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.types import Update


def adapter():
    name = "ugc_bot.infrastructure.messenger.telegram.messenger_linking"
    assert importlib.util.find_spec(name) is not None, (
        "reserved native interception missing"
    )
    return importlib.import_module(name)


def update(text="/start lk1_" + "A" * 43, **change):
    message = {
        "message_id": 20,
        "date": int(datetime.now(timezone.utc).timestamp()),
        "chat": {"id": 777, "type": "private"},
        "from": {
            "id": 777,
            "is_bot": False,
            "first_name": "<Actual>",
            "last_name": "Person",
            "username": "actual",
        },
        "text": text,
    }
    message.update(change)
    return Update.model_validate({"update_id": 100, "message": message})


@pytest.mark.asyncio
async def test_native_uses_actual_sender_bot_before_reply():
    module = adapter()
    bot = Bot("123:" + "A" * 35)
    calls = []
    service = SimpleNamespace(
        propose_native=AsyncMock(side_effect=lambda value: calls.append(value))
    )
    bot.send_message = AsyncMock(
        side_effect=lambda *a, **k: calls.append("reply")
    )
    try:
        assert await module.intercept_reserved_link(update(), bot, service)
        native = calls[0]
        assert native.bot_id == 123 and native.sender_id == "777"
        assert native.update_id == "100" and native.message_id == "20"
        assert native.display_name == "<Actual> Person"
        assert native.username == "actual"
        assert calls[1] == "reply"
    finally:
        await bot.session.close()


@pytest.mark.parametrize(
    "text",
    [
        "/start lk1_",
        "/start lk1_!",
        "/start lk1_" + "A" * 43 + " extra",
        "/start@another_bot lk1_!",
        "/start lk1_" + "x" * 500,
    ],
)
@pytest.mark.asyncio
async def test_every_reserved_malformed_start_is_consumed_even_without_service(
    text,
):
    module = adapter()
    bot = SimpleNamespace(
        id=123, token="123:" + "A" * 35, send_message=AsyncMock()
    )
    assert await module.intercept_reserved_link(update(text), bot, None)


@pytest.mark.parametrize(
    "change",
    [
        {"chat": {"id": -77, "type": "group"}},
        {"from": {"id": 777, "is_bot": True, "first_name": "Bot"}},
        {"from": None},
        {"chat": {"id": 999, "type": "private"}},
    ],
)
@pytest.mark.asyncio
async def test_untrusted_private_sender_never_proposes(change):
    module = adapter()
    service = SimpleNamespace(propose_native=AsyncMock())
    bot = SimpleNamespace(
        id=123, token="123:" + "A" * 35, send_message=AsyncMock()
    )
    assert await module.intercept_reserved_link(update(**change), bot, service)
    service.propose_native.assert_not_awaited()


@pytest.mark.asyncio
async def test_normal_start_and_nonmessage_updates_remain_ordinary():
    module = adapter()
    for value in [
        update("/start"),
        update("/start ref_123"),
        Update(update_id=10),
    ]:
        assert not await module.intercept_reserved_link(value, object(), None)


@pytest.mark.asyncio
async def test_reply_failure_does_not_retry_or_erase_committed_proposal(caplog):
    module = adapter()
    service = SimpleNamespace(propose_native=AsyncMock())
    bot = SimpleNamespace(
        id=123,
        token="123:" + "A" * 35,
        send_message=AsyncMock(side_effect=RuntimeError("lk1_" + "A" * 43)),
    )
    assert await module.intercept_reserved_link(update(), bot, service)
    service.propose_native.assert_awaited_once()
    assert "lk1_" not in caplog.text


@pytest.mark.asyncio
async def test_commit_failure_is_not_acknowledged_or_logged_with_token():
    module = adapter()
    from fastapi import HTTPException

    service = SimpleNamespace(
        propose_native=AsyncMock(side_effect=RuntimeError("private-bearer"))
    )
    bot = SimpleNamespace(
        id=123, token="123:" + "A" * 35, send_message=AsyncMock()
    )
    with pytest.raises(HTTPException) as failure:
        await module.intercept_reserved_link(update(), bot, service)
    assert failure.value.status_code == 503
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_fallback_uses_same_reserved_interceptor():
    name = "ugc_bot.bot.telegram.handlers.messenger_linking"
    assert importlib.util.find_spec(name) is not None, (
        "native dispatcher guard missing"
    )
    handler = importlib.import_module(name)
    value = update("/start lk1_!")
    assert await handler.reserved_start(value.message, SimpleNamespace(), value)


@pytest.mark.parametrize(
    "language,fragment",
    [
        ("ru", "Вернитесь"),
        ("en", "Return"),
        ("kk", "оралыңыз"),
        ("be", "Вярніцеся"),
        ("uz", "qayting"),
        ("fr", "Вернитесь"),
    ],
)
@pytest.mark.asyncio
async def test_native_reply_is_localized_without_owner_or_token(
    language, fragment
):
    module = adapter()
    service = SimpleNamespace(propose_native=AsyncMock())
    bot = SimpleNamespace(
        id=123, token="123:" + "A" * 35, send_message=AsyncMock()
    )
    value = update(
        **{
            "from": {
                "id": 777,
                "is_bot": False,
                "first_name": "Actual",
                "language_code": language,
            }
        }
    )
    assert await module.intercept_reserved_link(value, bot, service)
    text = bot.send_message.await_args.args[1]
    assert fragment in text
    assert "lk1_" not in text and "12345" not in text


@pytest.mark.parametrize(
    "bot_id,token", [(124, "123:" + "A" * 35), (123, "invalid-token")]
)
@pytest.mark.asyncio
async def test_bad_bot_scope_consumes_without_claim_or_signup(bot_id, token):
    module = adapter()
    service = SimpleNamespace(propose_native=AsyncMock())
    bot = SimpleNamespace(id=bot_id, token=token)
    assert await module.intercept_reserved_link(update(), bot, service)
    service.propose_native.assert_not_awaited()
