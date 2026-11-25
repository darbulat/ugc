"""The paid offer flow keeps one creator message and one contact delivery."""

import asyncio
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_paid_selection_delivery import (
    capture_env,
    delivery_env,
    rows,
)
from ugc_bot.application.creator_offer_cards import CALLBACK_PREFIX
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.bot.creator_offer_card_flow import CreatorOfferCardFlow
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.kafka_consumer import _send_public_offer

__all__ = ["capture_env", "delivery_env"]


@pytest.mark.asyncio
async def test_response_start_is_recorded_for_a_legacy_send(delivery_env):
    env = delivery_env
    dispatch = env["container"].build_offer_dispatch_service()
    order_id, blogger_id = env["order"], env["other_creator"]
    await dispatch.record_offer_sent(order_id, blogger_id)
    await dispatch.record_response_started(order_id, blogger_id)
    receipt = next(
        row
        for row in rows(env, "offer_channel_attribution")
        if row["blogger_id"] == blogger_id
    )
    assert receipt["response_started_at"] is not None
    assert receipt["telegram_sent_at"] is None
    assert receipt["max_sent_at"] is None
    assert receipt["response_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_receipt", [False, True])
async def test_paid_card_navigation_response_and_contact_delivery(
    delivery_env, lost_receipt
):
    env = delivery_env
    await env["worker"].run_once()
    baseline = len(env["bot"].calls)
    assert baseline == 1
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == env["order"])
            .values(
                creator_offer_card={
                    "title": "Тестовая съёмка",
                    "task": "Покажи один день с приложением",
                    "deadline": "7 дней после согласования",
                    "usage": "Соцсети заказчика",
                    "contact": "@synthetic_client",
                }
            )
        )
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["other_creator"])
            .values(telegram="synthetic_creator")
        )
    container = env["container"]
    repos = container.build_repos()
    services = container.build_bot_services()
    order = await repos["order_repo"].get_by_id(env["order"])
    creator = await repos["user_repo"].get_by_id(env["other_creator"])
    provider = AsyncMock()
    provider.send_photo.return_value = SimpleNamespace(message_id=321)
    if lost_receipt:
        provider.send_photo.side_effect = TimeoutError
    messenger = TelegramMessengerClient(provider)
    dispatch = services["offer_dispatch_service"]
    control = repos["dispatch_control"]
    async with container.transaction_manager.transaction() as db:
        assert await control.start(order.order_id, session=db) == 1
        assert await control.prepare_audience(
            order.order_id, [creator.user_id], 1, session=db
        ) == {creator.user_id}
        assert (
            await control.claim(order.order_id, creator.user_id, 1, session=db)
            == "claimed"
        )
    sent = await _send_public_offer(
        order,
        creator,
        [(creator.telegram_id, messenger, "telegram")],
        dispatch,
        "ru",
    )
    assert sent is (None if lost_receipt else True)
    flow = CreatorOfferCardFlow(
        repos["order_repo"],
        dispatch,
        services["offer_response_service"],
        services["user_role_service"],
        services["profile_service"],
        services["bot_texts_service"],
        messenger,
        "ru",
    )

    callback_ids = count()

    async def click(action, callback_id=None):
        return await flow.handle(
            IncomingCallback(
                callback_id=callback_id or f"synthetic-{next(callback_ids)}",
                chat_id=creator.telegram_id,
                user=IncomingUser(creator.telegram_id, MessengerType.TELEGRAM),
                message_id="321",
                data=f"{CALLBACK_PREFIX}{action}:{order.order_id}",
            )
        )

    def creator_receipt():
        return next(
            row
            for row in rows(env, "offer_channel_attribution")
            if row["blogger_id"] == creator.user_id
        )

    await dispatch.record_response_started(order.order_id, order.advertiser_id)
    assert all(
        row["blogger_id"] != order.advertiser_id
        for row in rows(env, "offer_channel_attribution")
    )
    for action in ("brief", "open", "safe", "open", "confirm"):
        assert await click(action) is None
        assert (creator_receipt()["response_started_at"] is not None) == (
            action == "confirm"
        )
        current = provider.edit_message_caption.call_args.kwargs
        assert current["message_id"] == 321
        assert "synthetic_client" not in current["caption"]
        assert not any(
            button.url
            for row in current["reply_markup"].inline_keyboard
            for button in row
        )
    started_at = creator_receipt()["response_started_at"]
    assert creator_receipt()["response_at"] is None
    await asyncio.gather(click("confirm"), click("confirm"))
    assert creator_receipt()["response_started_at"] == started_at
    await asyncio.gather(click("done"), click("done"))
    assert creator_receipt()["response_started_at"] == started_at
    assert creator_receipt()["response_at"] is not None
    provider.send_photo.assert_awaited_once()
    provider.send_message.assert_not_awaited()
    saved = provider.edit_message_caption.call_args.kwargs
    assert "Отклик отправлен" in saved["caption"]
    assert saved["reply_markup"].inline_keyboard[1][0].url == (
        "https://t.me/synthetic_client"
    )
    await asyncio.gather(click("full", "duplicate"), click("full", "duplicate"))
    displayed = provider.edit_message_caption.call_args.kwargs
    assert "ТЗ и правила работы" in displayed["caption"]
    actions = rows(env, "offer_card_action_events")
    assert sum(row["action"] == "full" for row in actions) == 1
    assert any(row["action"] == "brief" for row in actions)
    assert len(rows(env, "paid_selection_interests")) == 2
    assert len(rows(env, "paid_selection_delivery_jobs")) == 2
    original_send = env["bot"].send_message

    async def next_receipt(**payload):
        result = await original_send(**payload)
        result.message_id = 8
        return result

    env["bot"].send_message = next_receipt
    env["worker"].clock.at = max(
        env["worker"].clock.at,
        max(
            row["confirmed_at"] for row in rows(env, "paid_selection_interests")
        ),
    )
    await env["worker"].run_once()
    await click("done")
    await env["worker"].run_once()
    assert len(env["bot"].calls) == baseline + 1
    contact = env["bot"].calls[-1]
    assert contact["text"].startswith("Новый отклик\nТестовая съёмка")
    assert contact["reply_markup"].inline_keyboard[0][0].url == (
        "https://t.me/synthetic_creator"
    )
    assert len(rows(env, "paid_selection_accepted_deliveries")) == 2
    provider.send_photo.assert_awaited_once()
    provider.send_message.assert_not_awaited()
