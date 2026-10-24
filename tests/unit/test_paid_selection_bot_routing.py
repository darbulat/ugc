"""Native confirmations never bypass the durable v1 contact queue."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.helpers.factories import create_test_order
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.application.services.offer_response_service import (
    OfferResponseResult,
    OfferResponseService,
)
from ugc_bot.domain.entities import OfferDispatch
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryOrderRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["telegram", "max"])
async def test_native_queued_interest_skips_untracked_contact_send(
    monkeypatch, host
):
    from ugc_bot.bot.max.handlers import offer_responses as max_module
    from ugc_bot.bot.telegram.handlers import offer_responses as tg_module

    creator = uuid4()
    order = await create_test_order(
        InMemoryOrderRepository(), uuid4(), status=OrderStatus.ACTIVE
    )
    result = OfferResponseResult(
        order,
        OfferDispatch(order.order_id, creator, order.created_at),
        1,
        False,
        None,
        True,
        delivery_queued=True,
        selection_assignment_id=uuid4(),
    )
    incoming = IncomingCallback(
        callback_id="synthetic",
        chat_id="100",
        message_id="1",
        data=f"offer_confirm:{order.order_id}",
        user=IncomingUser(
            external_id="101", messenger_type=MessengerType(host)
        ),
    )
    messenger, users, profiles, interaction = (AsyncMock() for _ in range(4))
    users.get_user.return_value = SimpleNamespace(
        user_id=creator, status=UserStatus.ACTIVE
    )
    profiles.get_blogger_profile.return_value = SimpleNamespace(confirmed=True)
    texts = AsyncMock()
    texts.get.side_effect = lambda key, locale: key
    texts.get_many.return_value = {}
    untracked = AsyncMock(side_effect=AssertionError("untracked delivery"))
    monkeypatch.setattr(tg_module, "_send_contact_immediately", untracked)
    monkeypatch.setattr(max_module, "_send_contact_immediately", untracked)
    if host == "telegram":
        await tg_module._reply_offer_response_result(
            incoming,
            result,
            creator,
            messenger,
            users,
            profiles,
            interaction,
            texts,
            "ru",
        )
    else:
        offers = AsyncMock()
        offers.respond_and_finalize.return_value = result
        await max_module.handle_offer_confirm(
            incoming,
            {
                "messenger_client": messenger,
                "user_role_service": users,
                "profile_service": profiles,
                "offer_response_service": offers,
                "interaction_service": interaction,
                "bot_texts_service": texts,
                "config": SimpleNamespace(
                    market=SimpleNamespace(currency_symbol="₽")
                ),
            },
        )
    untracked.assert_not_awaited()
    interaction.create_interaction.assert_not_awaited()
    sent = [call.kwargs["text"] for call in messenger.send_text.await_args_list]
    assert "msg_blogger_selection_interest_saved" in sent
    assert "msg_blogger_after_response_what_next" not in sent


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["telegram", "max"])
@pytest.mark.parametrize(
    "reason,expected",
    [
        ("financial_core_disabled", "msg_offer_response_unavailable"),
        (
            "selection_verified_creator_required",
            "msg_offer_response_verification_required",
        ),
        (
            "selection_identity_already_interested",
            "msg_offer_response_identity_used",
        ),
    ],
)
async def test_rejected_financial_interest_is_not_reported_as_closed(
    monkeypatch,
    host,
    reason,
    expected,
):
    from ugc_bot.bot.max.handlers import offer_responses as max_module
    from ugc_bot.bot.telegram.handlers import offer_responses as tg_module

    creator, order_id = uuid4(), uuid4()
    incoming = IncomingCallback(
        callback_id="synthetic",
        chat_id="100",
        message_id="1",
        data=f"offer_confirm:{order_id}",
        user=IncomingUser(
            external_id="101", messenger_type=MessengerType(host)
        ),
    )
    messenger, users, profiles, interaction, texts = (
        AsyncMock() for _ in range(5)
    )
    users.get_user.return_value = SimpleNamespace(
        user_id=creator, status=UserStatus.ACTIVE
    )
    profiles.get_blogger_profile.return_value = SimpleNamespace(confirmed=True)
    texts.get.side_effect = lambda key, locale: key
    texts.get_many.return_value = {}
    subject = OfferResponseService(
        order_repo=AsyncMock(),
        dispatch_repo=AsyncMock(),
        transaction_manager=SimpleNamespace(),
        paid_selection_service=SimpleNamespace(
            respond=AsyncMock(side_effect=ValueError(reason))
        ),
    )
    closed = AsyncMock()
    monkeypatch.setattr(
        tg_module, "_send_order_closed_and_remove_keyboard", closed
    )
    monkeypatch.setattr(
        max_module, "_send_order_closed_and_remove_keyboard", closed
    )
    config = SimpleNamespace(market=SimpleNamespace(currency_symbol="₽"))
    if host == "telegram":
        await tg_module.handle_offer_confirm(
            object(),
            AsyncMock(),
            users,
            profiles,
            subject,
            interaction,
            AsyncMock(),
            config,
            texts,
            messenger_client=messenger,
            event_adapter=SimpleNamespace(
                from_callback=lambda callback: incoming
            ),
        )
    else:
        await max_module.handle_offer_confirm(
            incoming,
            {
                "messenger_client": messenger,
                "user_role_service": users,
                "profile_service": profiles,
                "offer_response_service": subject,
                "interaction_service": interaction,
                "bot_texts_service": texts,
                "config": config,
            },
        )
    closed.assert_not_awaited()
    messenger.edit_reply_markup.assert_not_awaited()
    assert messenger.answer_callback.await_args.kwargs["text"] == expected
