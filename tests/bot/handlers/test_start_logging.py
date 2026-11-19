"""Observe real /start routing and SDK acknowledgements without network IO."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.methods import SendMessage
from aiogram.types import Message, Update
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.helpers.fakes import FakeReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.start import router
from ugc_bot.bot.telegram.start_logging import (
    StartCommandLogging,
    StartReplyLogging,
    install_start_logging,
)
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.logging_setup import JSONFormatter

LOG_NAME = "ugc_bot.bot.telegram.start_logging"


def update(number=100, chat=71, text="/start private-deep-link"):
    return Update.model_validate(
        {
            "update_id": number,
            "message": {
                "message_id": 50,
                "date": int(datetime.now(timezone.utc).timestamp()),
                "chat": {"id": chat, "type": "private"},
                "from": {
                    "id": chat,
                    "is_bot": False,
                    "first_name": "Private name",
                },
                "text": text,
            },
        }
    )


@pytest_asyncio.fixture
async def bot():
    bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
    reply_counts = {}

    async def reply(bot, method, timeout=None):
        await asyncio.sleep(0)
        chat = int(method.chat_id)
        reply_counts[chat] = reply_counts.get(chat, 0) + 1
        return Message.model_validate(
            {
                "message_id": chat + 999 + reply_counts[chat],
                "date": int(datetime.now(timezone.utc).timestamp()),
                "chat": {"id": method.chat_id, "type": "private"},
                "text": getattr(method, "text", None),
            },
            context={"bot": bot},
        )

    bot.session.make_request = AsyncMock(side_effect=reply)
    bot.session.middleware(StartReplyLogging())
    yield bot
    await bot.session.close()


def events(caplog):
    return [r for r in caplog.records if r.name == LOG_NAME]


async def route(bot, item, **dependencies):
    # Reuse the real handlers and filters without attaching the global router
    # to another dispatcher used by unrelated tests.
    child = Router()
    child.message.handlers = router.message.handlers.copy()
    dispatcher = Dispatcher()
    dispatcher.include_router(child)
    bot.session.middleware.unregister(bot.session.middleware[0])
    install_start_logging(dispatcher, bot)
    try:
        return await dispatcher.feed_update(
            bot,
            item,
            event_adapter=TelegramEventAdapter(),
            messenger_client=TelegramMessengerClient(
                bot, retry_delay_seconds=0
            ),
            referral_service=FakeReferralService(),
            **dependencies,
        )
    finally:
        await dispatcher.fsm.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("choose_country", [False, True])
async def test_real_start_chain_has_api_ack_and_safe_json(
    bot, caplog, user_repo, config, bot_texts_service, choose_country
):
    caplog.set_level(logging.INFO, logger=LOG_NAME)
    country_repo = SimpleNamespace(
        list_enabled=AsyncMock(
            return_value=[
                SimpleNamespace(
                    code="RU", name_native="Russia", currency_symbol="RUB"
                )
            ]
            if choose_country
            else []
        )
    )
    await route(
        bot,
        update(),
        user_role_service=UserRoleService(user_repo=user_repo),
        config=config,
        bot_texts_service=bot_texts_service,
        country_repo=country_repo,
    )
    records = events(caplog)
    assert [r.event_type for r in records] == [
        "telegram.start.received",
        "telegram.start.reply_sent",
        "telegram.start.completed",
    ]
    assert [r.update_id for r in records] == [100, 100, 100]
    assert [r.reply_message_id for r in records] == [None, 1071, 1071]
    assert records[0].reply_message_ids == []
    assert records[-1].reply_message_ids == [1071]
    assert records[-1].outcome == "completed"
    assert records[-1].duration_ms >= 0
    assert records[1].api_method == "SendMessage"
    payload = "\n".join(JSONFormatter().format(r) for r in records)
    assert "private-deep-link" not in payload
    assert "Private name" not in payload
    assert bot.token not in payload
    assert "chat_id" not in payload
    assert json.loads(JSONFormatter().format(records[-1]))["update_id"] == 100


def data(item):
    return {
        "handler": SimpleNamespace(flags={"commands": [CommandStart()]}),
        "event_update": item,
    }


@pytest.mark.asyncio
async def test_rejected_send_never_logs_sent_or_success(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)
    bot.session.make_request.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=71, text="private"),
        message="sensitive refusal text",
    )

    async def handler(event, data):
        await bot.send_message(event.chat.id, "private")

    item = update()
    with pytest.raises(TelegramForbiddenError):
        await StartCommandLogging()(handler, item.message, data(item))
    records = events(caplog)
    assert [r.event_type for r in records] == [
        "telegram.start.received",
        "telegram.start.completed",
    ]
    assert records[-1].outcome == "failed"
    assert records[-1].error_type == "TelegramForbiddenError"
    assert records[-1].reply_message_id is None
    assert "sensitive refusal text" not in caplog.text


@pytest.mark.asyncio
async def test_failure_after_reply_preserves_ack_without_claiming_completion(
    bot, caplog
):
    caplog.set_level(logging.INFO, logger=LOG_NAME)

    async def handler(event, data):
        await bot.send_message(event.chat.id, "reply")
        raise ValueError("private payload")

    item = update()
    with pytest.raises(ValueError):
        await StartCommandLogging()(handler, item.message, data(item))
    records = events(caplog)
    assert len(records) == 3
    assert records[1].event_type == "telegram.start.reply_sent"
    assert records[-1].outcome == "failed"
    assert records[-1].reply_message_id == 1071
    assert "private payload" not in caplog.text


@pytest.mark.asyncio
async def test_retry_logs_only_successful_api_reply(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)
    make_reply = bot.session.make_request.side_effect
    response = await make_reply(bot, SendMessage(chat_id=71, text="reply"))
    bot.session.make_request.side_effect = [
        TelegramNetworkError(
            method=SendMessage(chat_id=71, text="reply"), message="timeout"
        ),
        response,
    ]
    client = TelegramMessengerClient(bot, retry_delay_seconds=0)

    async def handler(event, data):
        await client.send_text(chat_id=str(event.chat.id), text="reply")

    item = update()
    await StartCommandLogging()(handler, item.message, data(item))
    assert len(events(caplog)) == 3
    assert events(caplog)[-1].outcome == "completed"


@pytest.mark.asyncio
async def test_concurrent_commands_keep_separate_ids(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)

    async def handler(event, data):
        await bot.send_message(event.chat.id, "reply")
        await asyncio.sleep(0)
        await bot.send_message(999, "notification to another chat")

    async def run(number, chat):
        item = update(number, chat)
        await StartCommandLogging()(handler, item.message, data(item))

    await asyncio.gather(run(101, 71), run(102, 72))
    for number, reply_id in ((101, 1071), (102, 1072)):
        records = [r for r in events(caplog) if r.update_id == number]
        assert len(records) == 3
        assert records[-1].reply_message_ids == [reply_id]
    before = len(events(caplog))
    await bot.send_message(71, "unrelated message outside /start")
    assert len(events(caplog)) == before


@pytest.mark.asyncio
async def test_late_child_task_does_not_extend_finished_command(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)
    ready = asyncio.Event()
    tasks = []

    async def late_reply():
        await ready.wait()
        await bot.send_message(71, "late notification")

    async def handler(event, data):
        tasks.append(asyncio.create_task(late_reply()))

    item = update()
    await StartCommandLogging()(handler, item.message, data(item))
    ready.set()
    await asyncio.gather(*tasks)
    assert len(events(caplog)) == 2
    assert events(caplog)[-1].outcome == "no_reply"


@pytest.mark.asyncio
async def test_cancellation_resets_context(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)

    async def handler(event, data):
        raise asyncio.CancelledError()

    item = update()
    with pytest.raises(asyncio.CancelledError):
        await StartCommandLogging()(handler, item.message, data(item))
    assert events(caplog)[-1].error_type == "CancelledError"
    await bot.send_message(71, "outside cancelled command")
    assert len(events(caplog)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["unflagged", "ordinary_command", "no_update", "not_message"]
)
async def test_unrelated_events_are_unchanged(case, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)
    item = update()
    context = data(item)
    event = item.message
    if case == "unflagged":
        context["handler"].flags = {}
    elif case == "ordinary_command":
        context["handler"].flags = {"commands": [Command("manager")]}
    elif case == "no_update":
        context.pop("event_update")
    else:
        event = item
    handler = AsyncMock(return_value="unchanged")
    assert await StartCommandLogging()(handler, event, context) == "unchanged"
    assert not events(caplog)


@pytest.mark.asyncio
async def test_photo_reply_and_multiple_ids_are_recorded(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)

    async def handler(event, data):
        await bot.send_message(71, "welcome")
        await bot.send_photo(71, photo="synthetic-photo-id")
        await bot.send_invoice(
            71,
            title="Synthetic invoice",
            description="Synthetic description",
            payload="private-invoice-payload",
            currency="RUB",
            prices=[{"label": "Synthetic item", "amount": 100}],
        )

    item = update()
    await StartCommandLogging()(handler, item.message, data(item))
    records = events(caplog)
    assert [r.api_method for r in records[1:-1]] == [
        "SendMessage",
        "SendPhoto",
        "SendInvoice",
    ]
    assert records[-1].reply_message_ids == [1071, 1072, 1073]
    assert "private-invoice-payload" not in caplog.text


@pytest.mark.asyncio
async def test_non_send_method_does_not_claim_a_new_reply(bot, caplog):
    caplog.set_level(logging.INFO, logger=LOG_NAME)

    async def handler(event, data):
        await bot.edit_message_text("edit", chat_id=71, message_id=123)

    item = update()
    await StartCommandLogging()(handler, item.message, data(item))
    assert len(events(caplog)) == 2
    assert events(caplog)[-1].outcome == "no_reply"


@pytest.mark.asyncio
async def test_http_webhook_background_task_preserves_start_trace(
    bot, caplog, user_repo, config, bot_texts_service
):
    from ugc_bot.telegram_webhook_app import handle_webhook

    config = config.model_copy(
        update={
            "webhook": config.webhook.model_copy(
                update={"webhook_secret": "synthetic-webhook-secret"}
            )
        }
    )
    caplog.set_level(logging.INFO, logger=LOG_NAME)
    dispatcher = Dispatcher()
    child = Router()
    child.message.handlers = router.message.handlers.copy()
    dispatcher.include_router(child)
    dispatcher["user_role_service"] = UserRoleService(user_repo=user_repo)
    dispatcher["referral_service"] = FakeReferralService()
    dispatcher["bot_texts_service"] = bot_texts_service
    dispatcher["config"] = config
    dispatcher["messenger_client"] = TelegramMessengerClient(bot)
    dispatcher["event_adapter"] = TelegramEventAdapter()
    bot.session.middleware.unregister(bot.session.middleware[0])
    install_start_logging(dispatcher, bot)
    app = FastAPI()
    app.state.config = config
    app.state.dispatcher = dispatcher
    app.state.bot = bot
    app.state.webhook_semaphore = asyncio.Semaphore(2)
    app.post("/webhook/telegram")(handle_webhook)
    item = update(number=987)
    secret = config.webhook.webhook_secret
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/webhook/telegram",
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
                json=item.model_dump(mode="json", exclude_none=True),
            )
        assert response.status_code == 200
        for _ in range(30):
            if any(
                r.event_type == "telegram.start.completed"
                for r in events(caplog)
            ):
                break
            await asyncio.sleep(0)
        records = events(caplog)
        assert [r.event_type for r in records] == [
            "telegram.start.received",
            "telegram.start.reply_sent",
            "telegram.start.completed",
        ]
        assert {r.update_id for r in records} == {987}
        assert records[-1].reply_message_id == 1071
        assert records[-1].outcome == "completed"
    finally:
        await dispatcher.fsm.close()
