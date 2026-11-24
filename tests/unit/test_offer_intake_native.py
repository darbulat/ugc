"""Native legacy cards and already-open price forms obey the same cutoff."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeUser,
)
from ugc_bot.application.errors import PaidSelectionResponseError
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.bot.max.handlers import offer_responses as max_handlers
from ugc_bot.bot.telegram.handlers import offer_responses as telegram_handlers
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryUserRepository,
)


@pytest.fixture
def native_offer():
    now = datetime.now(timezone.utc)
    order = Order(
        uuid4(),
        uuid4(),
        OrderType.UGC_ONLY,
        "test",
        "Offer",
        None,
        500,
        1,
        OrderStatus.ACTIVE,
        now,
        offer_reserve_until=now + timedelta(hours=72),
    )
    user = User(
        uuid4(),
        MessengerType.TELEGRAM,
        "Creator",
        UserStatus.ACTIVE,
        0,
        now,
        telegram_id="42",
        max_id="42",
        max_chat_id="42",
    )
    users = AsyncMock()
    users.get_user.return_value = user
    users.update_telegram.return_value = user
    profiles = AsyncMock()
    profiles.get_blogger_profile.return_value = SimpleNamespace(confirmed=True)
    limiter = AsyncMock()
    limiter.allow_async.return_value = True
    return SimpleNamespace(
        order=order, user=user, users=users, profiles=profiles, limiter=limiter
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
async def test_price_form_expiring_after_bounds_read_does_not_record_response(
    native_offer,
    channel,
    monkeypatch,
    messenger_client,
    event_adapter,
    bot_texts_service,
    config,
):
    env = native_offer
    orders, offers = (
        InMemoryOrderRepository(),
        InMemoryOfferDispatchRepository(),
    )
    outbox = InMemoryOutboxRepository()
    await orders.save(env.order)
    await offers.record_sent(env.order.order_id, env.user.user_id)
    service = OfferDispatchService(
        InMemoryUserRepository(),
        InMemoryBloggerProfileRepository(),
        orders,
        offers,
        InMemoryInteractionRepository(),
        outbox_repo=outbox,
    )
    original = OfferDispatchService.get_order_price_bounds

    async def bounds_then_expire(self, order_id):
        bounds = await original(self, order_id)
        await orders.save(
            replace(env.order, offer_reserve_until=datetime.now(timezone.utc))
        )
        return bounds

    monkeypatch.setattr(
        OfferDispatchService, "get_order_price_bounds", bounds_then_expire
    )
    state = FakeFSMContext()
    await state.update_data(order_id=str(env.order.order_id))
    if channel == MessengerType.TELEGRAM:
        await telegram_handlers.handle_desired_price(
            FakeMessage("5000", user=FakeUser(42)),
            state,
            env.users,
            service,
            bot_texts_service,
            config,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
    else:
        await max_handlers.handle_desired_price(
            IncomingMessage("42", IncomingUser("42", channel), text="5000"),
            dict(
                messenger_client=messenger_client,
                user_role_service=env.users,
                offer_dispatch_service=service,
                bot_texts_service=bot_texts_service,
                state_store=state,
                config=config,
            ),
        )
    assert "Набор завершён" in messenger_client.sent_text[-1]["text"]
    assert await state.get_data() == {}
    assert not await offers.exists_responded(
        env.order.order_id, env.user.user_id
    )
    assert await outbox.get_pending_events() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
async def test_legacy_reserve_confirmation_discloses_no_guaranteed_place(
    native_offer,
    channel,
    messenger_client,
    event_adapter,
    bot_texts_service,
    config,
):
    env = native_offer
    orders = InMemoryOrderRepository()
    await orders.save(env.order)
    dispatch = AsyncMock(spec=OfferDispatchService)
    if channel == MessengerType.TELEGRAM:
        await telegram_handlers.handle_offer_response(
            FakeCallback(
                data=f"offer:{env.order.order_id}",
                user=FakeUser(42),
                message=FakeMessage(),
            ),
            FakeFSMContext(),
            env.users,
            env.profiles,
            orders,
            env.limiter,
            config,
            bot_texts_service,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
            offer_dispatch_service=dispatch,
        )
    else:
        await max_handlers.handle_offer_response(
            IncomingCallback(
                "cb",
                "42",
                IncomingUser("42", channel),
                data=f"offer:{env.order.order_id}",
                message_id="1",
            ),
            dict(
                messenger_client=messenger_client,
                user_role_service=env.users,
                profile_service=env.profiles,
                order_repo=orders,
                offer_dispatch_service=dispatch,
                offer_response_rate_limiter=env.limiter,
                bot_texts_service=bot_texts_service,
                config=config,
            ),
        )
    dispatch.record_response_started.assert_awaited_once_with(
        env.order.order_id, env.user.user_id
    )
    confirmation = messenger_client.sent_text[-1]
    assert "Основной состав набран" in confirmation["text"]
    assert "Участие не гарантировано" in confirmation["text"]
    assert (
        confirmation["keyboard"].rows[0][0].callback_data
        == f"offer_confirm:{env.order.order_id}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
async def test_legacy_confirm_race_removes_buttons_when_backend_rejects(
    native_offer,
    channel,
    messenger_client,
    event_adapter,
    bot_texts_service,
    config,
):
    env = native_offer
    responses = AsyncMock()
    responses.respond_and_finalize.side_effect = PaidSelectionResponseError(
        "offer_intake_closed"
    )
    if channel == MessengerType.TELEGRAM:
        await telegram_handlers.handle_offer_confirm(
            FakeCallback(
                data=f"offer_confirm:{env.order.order_id}",
                user=FakeUser(42),
                message=FakeMessage(),
            ),
            FakeFSMContext(),
            env.users,
            env.profiles,
            responses,
            AsyncMock(),
            env.limiter,
            config,
            bot_texts_service,
            messenger_client=messenger_client,
            event_adapter=event_adapter,
        )
    else:
        await max_handlers.handle_offer_confirm(
            IncomingCallback(
                "cb",
                "42",
                IncomingUser("42", channel),
                data=f"offer_confirm:{env.order.order_id}",
                message_id="1",
            ),
            dict(
                messenger_client=messenger_client,
                user_role_service=env.users,
                profile_service=env.profiles,
                offer_response_service=responses,
                offer_response_rate_limiter=env.limiter,
                bot_texts_service=bot_texts_service,
                config=config,
            ),
        )
    assert "Набор завершён" in messenger_client.sent_text[-1]["text"]
    assert messenger_client.edited_reply_markups[-1]["keyboard"] is None
    assert len(messenger_client.answered_callbacks) == 1
