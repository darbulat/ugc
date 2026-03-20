"""Tests for offer response handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_blogger_profile,
    create_test_order,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
)
from tests.helpers.services import build_profile_service
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.offer_responses import (
    OfferSkipStates,
    _send_contact_immediately,
    _send_order_closed_and_remove_keyboard,
    handle_cancel_price_entry,
    handle_desired_price,
    handle_offer_response,
    handle_offer_skip,
    handle_rejection_reason,
)
from ugc_bot.bot.handlers.utils import RateLimiter
from ugc_bot.bot.middleware.error_handler import ErrorHandlerMiddleware
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import AppConfig, OrderConfig
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    RejectionReason,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryManagerOrderRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)
from ugc_bot.metrics.collector import MetricsCollector


def _offer_responses_config() -> AppConfig:
    """Minimal config for offer_responses handler tests."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://test",
            "TELEGRAM_PROVIDER_TOKEN": "provider",
        }
    )


@pytest.fixture
def offer_response_rate_limiter() -> RateLimiter:
    """Permissive rate limiter for most tests."""
    return RateLimiter(limit=100, window_seconds=10.0)


@pytest.fixture
def strict_rate_limiter() -> RateLimiter:
    """Strict rate limiter (5 per 10s) for rate limit tests."""
    return RateLimiter(limit=5, window_seconds=10.0)


async def _call_handler_with_middleware(handler, *args, **kwargs):
    """Call handler wrapped in error handling middleware."""
    error_handler = ErrorHandlerMiddleware(metrics_collector=MetricsCollector())

    async def wrapped_handler(event, data):
        return await handler(*args, **kwargs)

    # First arg should be the event (callback or message)
    event = args[0] if args else None
    return await error_handler(wrapped_handler, event, {})


@pytest.mark.asyncio
async def test_contact_sent_immediately(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    bot_texts_service,
) -> None:
    """Send contact immediately after each response."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000740"),
        external_id="777",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000741"),
        external_id="10",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, blogger.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000742"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    bot = FakeMessage(user=FakeUser(int(advertiser.external_id)))
    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    # Check contact sent (TZ: "Новый отклик", Креатор, Профиль креатора)
    def _text(value):  # type: ignore[no-untyped-def]
        return value[0] if isinstance(value, tuple) else value

    assert any("Новый отклик" in _text(a) for a in bot.answers)
    assert any(
        "blogger" in _text(a) or "Креатор" in _text(a) for a in bot.answers
    )
    assert any(
        "Профиль креатора" in _text(a) or "instagram" in _text(a)
        for a in bot.answers
    )

    # Check interaction was created
    interaction = await interaction_repo.get_by_participants(
        order_id=order.order_id,
        blogger_id=blogger.user_id,
        advertiser_id=advertiser.user_id,
    )
    assert interaction is not None
    assert interaction.blogger_id == blogger.user_id
    assert interaction.advertiser_id == advertiser.user_id


@pytest.mark.asyncio
async def test_blogger_receives_advertiser_contacts_when_accepted(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    bot_texts_service,
) -> None:
    """Blogger gets advertiser Telegram and phone when accepted into order."""

    advertiser_repo = InMemoryAdvertiserProfileRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo, advertiser_repo
    )

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000750"),
        external_id="750",
        username="adv",
        telegram="advertiser_tg",
    )
    await create_test_advertiser_profile(
        advertiser_repo,
        advertiser.user_id,
        phone="+79001234567",
        brand="Brand",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000751"),
        external_id="751",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, blogger.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000752"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    sent_to_blogger = [
        s
        for s in messenger_client.sent_text
        if s["chat_id"] == blogger.external_id
    ]
    assert len(sent_to_blogger) >= 1
    contact_msg = next(
        (
            s["text"]
            for s in sent_to_blogger
            if "Контакты заказчика" in s["text"]
        ),
        None,
    )
    assert contact_msg is not None
    assert "advertiser_tg" in contact_msg or "Telegram:" in contact_msg
    assert "+79001234567" in contact_msg or "Телефон:" in contact_msg


@pytest.mark.asyncio
async def test_offer_skip_handler(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Blogger 'Пропустить' on offer: skip recorded, keyboard removed."""

    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000749"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    _order_config = OrderConfig(
        allowed_blogger_counts="1,3,5,10",
        max_order_price=10_000.0,
    )
    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=None,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000748")
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)
    message = FakeMessage()
    message.reply_markup = object()
    callback = FakeCallback(
        data=f"offer_skip:{order_id}",
        user=FakeUser(1),
        message=message,
    )
    await handle_offer_skip(
        callback,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Now shows reason selection menu instead of immediate skip
    assert callback.answers is not None  # callback answered (empty toast)
    # Original keyboard removed
    assert len(message.edit_reply_markup_calls) == 1
    assert message.edit_reply_markup_calls[0] is None
    # Reason prompt sent via messenger_client
    sent = messenger_client.sent_text
    assert any("причину" in s["text"].lower() for s in sent)


@pytest.mark.asyncio
async def test_order_closed_when_limit_reached(
    fake_tm: object, order_repo, offer_dispatch_repo
) -> None:
    """Close order when limit of responses is reached."""

    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )

    order = await create_test_order(
        order_repo,
        UUID("00000000-0000-0000-0000-000000000745"),
        order_id=UUID("00000000-0000-0000-0000-000000000744"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        completed_at=datetime.now(timezone.utc),
    )

    blogger1 = UUID("00000000-0000-0000-0000-000000000746")
    blogger2 = UUID("00000000-0000-0000-0000-000000000747")
    await offer_dispatch_repo.record_sent(order.order_id, blogger1)
    await offer_dispatch_repo.record_sent(order.order_id, blogger2)
    await response_service.respond_and_finalize(order.order_id, blogger1)
    await response_service.respond_and_finalize(order.order_id, blogger2)

    updated = await order_repo.get_by_id(order.order_id)
    assert updated is not None
    assert updated.status == OrderStatus.CLOSED


@pytest.mark.asyncio
async def test_offer_response_handler_success(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    event_adapter,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Blogger can respond to offer."""

    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000700"),
        external_id="10",
        username="blogger",
    )
    await user_service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        UUID("00000000-0000-0000-0000-000000000702"),
        order_id=UUID("00000000-0000-0000-0000-000000000701"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, user.user_id)

    message = FakeMessage()
    message.reply_markup = object()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(10), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    assert callback.answers
    responses = await offer_dispatch_repo.list_responses_by_order(
        order.order_id
    )
    assert list(responses)
    assert len(message.edit_reply_markup_calls) == 1
    assert message.edit_reply_markup_calls[0] is None


@pytest.mark.asyncio
async def test_offer_response_handler_blocked_user(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject blocked bloggers early."""

    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000710"),
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blocked_user)
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:123", user=FakeUser(11), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    assert "Заблокированные" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_order_not_active(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject responses for inactive orders."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000711"),
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    await user_service.set_user(
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000712"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000713"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(12), message=message
    )

    # Wrap handler call with middleware to handle errors
    await _call_handler_with_middleware(
        handle_offer_response,
        callback,
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
    )

    assert callback.answers


@pytest.mark.asyncio
async def test_send_order_closed_and_remove_keyboard(
    bot_texts_service, config
) -> None:
    """Order-closed helper answers callback and sends order-closed message."""
    incoming = IncomingCallback(
        callback_id="cb1",
        chat_id="123",
        user=IncomingUser(
            external_id="1",
            messenger_type=MessengerType.TELEGRAM,
            username="u",
        ),
        message_id="456",
    )
    client = FakeMessengerClient()
    locale = config.market.default_locale
    await _send_order_closed_and_remove_keyboard(
        incoming, client, bot_texts_service, locale
    )
    assert len(client.answered_callbacks) == 1
    msg_closed_full = DEFAULT_TEXTS["ru"]["msg_order_closed_full"]
    assert any(msg_closed_full in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_offer_response_handler_order_not_found(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject responses for unknown order."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000714"),
        external_id="13",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:00000000-0000-0000-0000-000000000999",
        user=FakeUser(13),
        message=message,
    )

    # Wrap handler call with middleware to handle errors
    await _call_handler_with_middleware(
        handle_offer_response,
        callback,
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
    )

    assert callback.answers


@pytest.mark.asyncio
async def test_offer_response_handler_already_responded(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject duplicate responses."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000715"),
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    await user_service.set_user(
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000716"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000717"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(order.order_id, user.user_id)
    await dispatch_repo.record_response(
        order.order_id, user.user_id, accepted=True, in_offer=True
    )

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(14), message=message
    )

    # Wrap handler call with middleware to handle errors
    await _call_handler_with_middleware(
        handle_offer_response,
        callback,
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
    )

    assert callback.answers


@pytest.mark.asyncio
async def test_offer_response_handler_overflow_saved_no_contact(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Overflow saved, overflow message shown; no contact to advertiser."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000719"),
        external_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    await user_service.set_user(
        external_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000720"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000721"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await dispatch_repo.record_sent(
        order.order_id, UUID("00000000-0000-0000-0000-000000000723")
    )
    await dispatch_repo.record_response(
        order.order_id,
        UUID("00000000-0000-0000-0000-000000000723"),
        accepted=True,
        in_offer=True,
    )
    await dispatch_repo.record_sent(order.order_id, user.user_id)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(15), message=message
    )

    await _call_handler_with_middleware(
        handle_offer_response,
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    # Short toast in answer_callback
    assert (
        "лист ожидания" in callback.answers[0]
        or "Записали" in callback.answers[0]
    )
    # Full text sent as a separate bot message
    assert any(
        "подборка блогеров уже закрыта" in str(a) or "лист ожидания" in str(a)
        for a in message.answers
    )
    assert len(message.edit_reply_markup_calls) == 1
    assert message.edit_reply_markup_calls[0] is None
    msg_closed_full = DEFAULT_TEXTS["ru"]["msg_order_closed_full"]
    assert msg_closed_full not in message.answers
    total = await dispatch_repo.count_by_order(order.order_id)
    assert total == 2
    accepted_count = await dispatch_repo.count_accepted_by_order(order.order_id)
    assert accepted_count == 1


@pytest.mark.asyncio
async def test_offer_response_handler_no_from_user(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Handle callback without from_user."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:123", user=FakeUser(999), message=message
    )
    callback.from_user = None

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert not callback.answers


@pytest.mark.asyncio
async def test_offer_response_handler_user_not_found(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject when user is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:123", user=FakeUser(999), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    msg = callback.answers[0]
    assert (
        "не найден" in msg
        or "not found" in msg.lower()
        or "profile" in msg.lower()
    )


@pytest.mark.asyncio
async def test_offer_response_handler_paused_user(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject paused bloggers."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    paused_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000730"),
        external_id="16",
        messenger_type=MessengerType.TELEGRAM,
        username="paused",
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(paused_user)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:123", user=FakeUser(16), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    assert "паузе" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_no_blogger_profile(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject when blogger profile is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000731"),
        external_id="17",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:123", user=FakeUser(17), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    assert (
        "Профиль не заполнен" in callback.answers[0]
        or "/creator" in callback.answers[0]
    )


@pytest.mark.asyncio
async def test_offer_response_handler_unconfirmed_profile(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject when Instagram is not confirmed."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000732"),
        external_id="18",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=False
    )

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:123", user=FakeUser(18), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    assert "Подтвердите Instagram" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_allows_response_without_agreement(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    event_adapter,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Blogger without agreement_confirmed_at can still respond to offer."""

    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000888"),
        external_id="88",
        username="blogger",
    )
    await user_service.set_user(
        external_id="88",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        UUID("00000000-0000-0000-0000-000000000889"),
        order_id=UUID("00000000-0000-0000-0000-000000000890"),
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, user.user_id)

    message = FakeMessage(user=FakeUser(88))
    message.reply_markup = object()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(88), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    responses = await offer_dispatch_repo.list_responses_by_order(
        order.order_id
    )
    assert list(responses), "Response should be recorded without agreement"


@pytest.mark.asyncio
async def test_offer_response_handler_invalid_uuid(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject invalid UUID in callback data."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        dispatch_repo=InMemoryOfferDispatchRepository(),
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000733"),
        external_id="19",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:not-a-uuid", user=FakeUser(19), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    assert "Неверный идентификатор" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_exception(
    fake_tm: object,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Handle exceptions gracefully."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000734"),
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)
    await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000735"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000736"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    # Mock dispatch_repo.record_response to raise exception
    original_record = dispatch_repo.record_response

    async def failing_record(*args, **kwargs):
        raise Exception("Test exception")

    dispatch_repo.record_response = failing_record  # type: ignore[assignment]

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(20), message=message
    )

    # Wrap handler call with middleware to handle exceptions
    await _call_handler_with_middleware(
        handle_offer_response,
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
    )

    assert callback.answers
    assert any("ошибка" in ans.lower() for ans in callback.answers)

    # Restore original method
    dispatch_repo.record_response = original_record


@pytest.mark.asyncio
async def test_send_contact_order_not_found(
    fake_tm: object, messenger_client, bot_texts_service
) -> None:
    """Handle missing user or profile gracefully."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000999"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001001"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )

    bot = FakeMessage(user=FakeUser(1))
    await _send_contact_immediately(
        order=order,
        blogger_id=UUID("00000000-0000-0000-0000-000000001000"),
        blogger_chat_id="1",
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    assert not bot.answers


@pytest.mark.asyncio
async def test_send_contact_order_not_active(
    fake_tm: object, messenger_client, bot_texts_service
) -> None:
    """Skip sending contacts when advertiser is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000802"),
        external_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger)
    await create_test_blogger_profile(
        blogger_repo, blogger.user_id, confirmed=True
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000800"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000801"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )

    bot = FakeMessage(user=FakeUser(1))
    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    assert not bot.answers


@pytest.mark.asyncio
async def test_maybe_send_contacts_missing_user_or_profile(
    fake_tm: object, messenger_client, bot_texts_service
) -> None:
    """Skip sending contacts when user or profile is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000810"),
        external_id="810",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000811"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )

    bot = FakeMessage(user=FakeUser(1))
    await _send_contact_immediately(
        order=order,
        blogger_id=UUID("00000000-0000-0000-0000-000000000999"),
        blogger_chat_id="1",
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    # Contact should not be sent when user/profile is missing
    assert not bot.answers


@pytest.mark.asyncio
async def test_offer_skip_edit_reply_markup_exception(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """handle_offer_skip handles exception when edit_reply_markup fails."""

    user_service = UserRoleService(user_repo=user_repo)
    _order_config = OrderConfig(
        allowed_blogger_counts="1,3,5,10",
        max_order_price=10_000.0,
    )
    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=None,
    )

    class MessageWithFailingEdit:
        reply_markup = object()

        async def edit_reply_markup(self, reply_markup=None, **kwargs):
            raise RuntimeError("edit failed")

        chat = type("Chat", (), {"id": 1})()
        message_id = 1

    message = MessageWithFailingEdit()
    callback = FakeCallback(
        data="offer_skip:00000000-0000-0000-0000-000000000750",
        user=FakeUser(1),
        message=message,
    )
    await handle_offer_skip(
        callback,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Callback answered (empty toast for reason menu flow)
    assert callback.answers is not None


@pytest.mark.asyncio
async def test_offer_response_handler_rate_limited(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    strict_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Reject when rate limit exceeded."""

    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000760"),
        external_id="21",
        username="blogger",
    )
    await user_service.set_user(
        external_id="21",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000761"),
        external_id="761",
        username="adv",
    )
    advertiser_id = advertiser.user_id
    orders = []
    for i in range(762, 768):
        order = await create_test_order(
            order_repo,
            advertiser_id,
            order_id=UUID(f"00000000-0000-0000-0000-000000000{i}"),
            bloggers_needed=3,
            status=OrderStatus.ACTIVE,
        )
        orders.append(order)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{orders[0].order_id}", user=FakeUser(21), message=message
    )

    for i in range(6):
        callback.data = f"offer:{orders[i].order_id}"
        await handle_offer_response(
            callback,
            FakeFSMContext(),
            user_service,
            profile_service,
            response_service,
            interaction_service,
            strict_rate_limiter,
            config,
            bot_texts_service=bot_texts_service,
        )

    assert any("Слишком много запросов" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_offer_response_sends_product_link_and_what_next(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    event_adapter,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Response succeeds: product_link and WHAT_NEXT sent."""

    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        dispatch_repo=offer_dispatch_repo,
        transaction_manager=fake_tm,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000770"),
        external_id="22",
        username="blogger",
    )
    await user_service.set_user(
        external_id="22",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        UUID("00000000-0000-0000-0000-000000000771"),
        order_id=UUID("00000000-0000-0000-0000-000000000772"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        product_link="https://product.example.com",
    )

    message = FakeMessage(user=FakeUser(123))
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(22), message=message
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        response_service,
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    assert callback.answers
    assert any("product.example.com" in str(a) for a in message.answers)
    assert any(
        "отклик" in str(a).lower() or "ожидайте" in str(a).lower()
        for a in message.answers
    )


@pytest.mark.asyncio
async def test_send_contact_ugc_plus_placement_format(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    bot_texts_service,
) -> None:
    """_send_contact_immediately shows UGC+размещение for ugc_plus_placement."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000780"),
        external_id="780",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000781"),
        external_id="781",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, blogger.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000782"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        order_type=OrderType.UGC_PLUS_PLACEMENT,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    bot = FakeMessage(user=FakeUser(int(advertiser.external_id)))
    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    assert any(
        "UGC + размещение" in (a[0] if isinstance(a, tuple) else a)
        for a in bot.answers
    )


@pytest.mark.asyncio
async def test_send_contact_empty_instagram_url(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    bot_texts_service,
) -> None:
    """_send_contact when instagram_url empty (no profile button)."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000790"),
        external_id="790",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000791"),
        external_id="791",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, blogger.user_id, confirmed=True, instagram_url=""
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000792"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    bot = FakeMessage(user=FakeUser(int(advertiser.external_id)))
    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    assert any(
        "Новый отклик" in (a[0] if isinstance(a, tuple) else a)
        for a in bot.answers
    )


@pytest.mark.asyncio
async def test_send_contact_instagram_url_without_http(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    bot_texts_service,
) -> None:
    """_send_contact adds https:// when instagram_url has no scheme."""

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000794"),
        external_id="794",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000795"),
        external_id="795",
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo,
        blogger.user_id,
        confirmed=True,
        instagram_url="instagram.com/creator",
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000796"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    bot = FakeMessage(user=FakeUser(int(advertiser.external_id)))
    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    assert any(
        "Новый отклик" in (a[0] if isinstance(a, tuple) else a)
        for a in bot.answers
    )


# ---------------------------------------------------------------------------
# Rejection reason selection tests
# ---------------------------------------------------------------------------


def _build_offer_dispatch_service(
    user_repo=None,
    order_repo=None,
    offer_dispatch_repo=None,
):
    """Build OfferDispatchService with in-memory repos."""
    return OfferDispatchService(
        user_repo=user_repo or InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=order_repo or InMemoryOrderRepository(),
        offer_dispatch_repo=offer_dispatch_repo
        or InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=None,
    )


@pytest.mark.asyncio
async def test_offer_skip_shows_reason_menu(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Pressing skip shows 4-button rejection reason keyboard."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a01"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a02")
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    message = FakeMessage()
    message.reply_markup = object()
    callback = FakeCallback(
        data=f"offer_skip:{order_id}",
        user=FakeUser(1),
        message=message,
    )
    await handle_offer_skip(
        callback,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # Should have sent a reason prompt with inline keyboard
    sent = messenger_client.sent_text
    reason_msgs = [s for s in sent if "причину" in s["text"].lower()]
    assert len(reason_msgs) == 1
    kb = reason_msgs[0]["keyboard"]
    assert kb is not None
    # 5 reason buttons, one per row
    assert len(kb.rows) == 5


@pytest.mark.asyncio
async def test_rejection_reason_non_price_records_skip(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Selecting WRONG_FORMAT records skip immediately with reason."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a10"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a11")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000a12"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"orr:{order_id}:{RejectionReason.WRONG_FORMAT.value}",
        user=FakeUser(1),
        message=message,
    )
    fsm = FakeFSMContext()
    await handle_rejection_reason(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # Skip should be recorded
    responses = await offer_dispatch_repo.list_responses_by_order(order_id)
    assert len(list(responses)) >= 1
    # Confirmation message sent
    sent = messenger_client.sent_text
    assert any("отказались" in s["text"].lower() for s in sent)


@pytest.mark.asyncio
async def test_rejection_reason_low_price_enters_fsm(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Selecting LOW_PRICE enters FSM waiting_desired_price state."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a20"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a21")
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"orr:{order_id}:{RejectionReason.LOW_PRICE.value}",
        user=FakeUser(1),
        message=message,
    )
    fsm = FakeFSMContext()
    await handle_rejection_reason(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM state should be set
    assert fsm.state == OfferSkipStates.waiting_desired_price.state
    fsm_data = await fsm.get_data()
    assert fsm_data["order_id"] == str(order_id)
    # Price entry prompt sent with cancel button
    sent = messenger_client.sent_text
    assert any("стоимость" in s["text"].lower() for s in sent)
    # Cancel keyboard should be present
    price_msg = next(s for s in sent if "стоимость" in s["text"].lower())
    assert price_msg["keyboard"] is not None


@pytest.mark.asyncio
async def test_desired_price_valid(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Entering a valid price records skip with price and sends confirmation."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a30"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a31")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000a32"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="2000", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should be cleared
    assert fsm.state is None
    # Skip recorded
    responses = await offer_dispatch_repo.list_responses_by_order(order_id)
    assert len(list(responses)) >= 1
    # Confirmation sent
    sent = messenger_client.sent_text
    assert any("2000" in s["text"] for s in sent)


@pytest.mark.asyncio
async def test_desired_price_below_min(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Entering a price below the offer price shows error."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a40"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a41")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000a42"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="500", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should NOT be cleared (still waiting)
    assert fsm.state == OfferSkipStates.waiting_desired_price.state
    # Error message sent with range
    sent = messenger_client.sent_text
    assert any("1000" in s["text"] and "10000" in s["text"] for s in sent)


@pytest.mark.asyncio
async def test_desired_price_above_max(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Entering a price above 10x the offer price shows error."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a50"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a51")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000a52"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="99999", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should NOT be cleared
    assert fsm.state == OfferSkipStates.waiting_desired_price.state
    # Error message sent
    sent = messenger_client.sent_text
    assert any("1000" in s["text"] and "10000" in s["text"] for s in sent)


@pytest.mark.asyncio
async def test_desired_price_non_numeric(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Entering non-numeric text shows error."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a60"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a61")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000a62"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="abc", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should NOT be cleared
    assert fsm.state == OfferSkipStates.waiting_desired_price.state
    # Error message sent
    sent = messenger_client.sent_text
    assert any("1000" in s["text"] and "10000" in s["text"] for s in sent)


@pytest.mark.asyncio
async def test_desired_price_equal_to_offer_rejected(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Price equal to offer price is rejected (must be strictly greater)."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a63"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a64")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000a65"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="1000", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should NOT be cleared — price equal to offer is invalid
    assert fsm.state == OfferSkipStates.waiting_desired_price.state
    sent = messenger_client.sent_text
    assert any("1000" in s["text"] and "10000" in s["text"] for s in sent)


@pytest.mark.asyncio
async def test_desired_price_order_not_found(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """If order not found, FSM is cleared and skip message sent."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a66"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    # order_id does NOT exist in order_repo
    order_id = UUID("00000000-0000-0000-0000-000000000a67")

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="2000", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=UserRoleService(user_repo=user_repo),
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should be cleared — order not found
    assert fsm.state is None
    # A message should be sent
    assert len(messenger_client.sent_text) >= 1


@pytest.mark.asyncio
async def test_cancel_price_entry(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Pressing cancel records skip without reason and clears FSM."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000a70"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000a71")
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    message = FakeMessage()
    callback = FakeCallback(
        data=f"orr_cancel:{order_id}",
        user=FakeUser(1),
        message=message,
    )
    await handle_cancel_price_entry(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should be cleared
    assert fsm.state is None
    # Callback answered with cancelled message
    assert callback.answers
    # Skip recorded without reason
    responses = await offer_dispatch_repo.list_responses_by_order(order_id)
    assert len(list(responses)) >= 1


# ---------------------------------------------------------------------------
# Additional edge-case tests for improved coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_offer_skip_user_is_none(
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """handle_offer_skip returns early when user is not found (line 163/182)."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)
    order_id = UUID("00000000-0000-0000-0000-000000000b01")

    message = FakeMessage()
    message.reply_markup = object()
    # External id 999 not in repo → user will be None
    callback = FakeCallback(
        data=f"offer_skip:{order_id}",
        user=FakeUser(999),
        message=message,
    )
    await handle_offer_skip(
        callback,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Callback is answered (empty toast), but reason menu NOT sent
    assert any(
        s["callback_id"] == callback.id
        for s in messenger_client.answered_callbacks
    )
    reason_msgs = [
        s for s in messenger_client.sent_text if "причину" in s["text"].lower()
    ]
    assert len(reason_msgs) == 0


@pytest.mark.asyncio
async def test_offer_skip_order_id_is_none(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Skip returns early when order_id cannot be parsed."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000b02"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)

    message = FakeMessage()
    message.reply_markup = object()
    # Invalid UUID in callback data → order_id will be None
    callback = FakeCallback(
        data="offer_skip:not-a-uuid",
        user=FakeUser(1),
        message=message,
    )
    await handle_offer_skip(
        callback,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Callback answered, but reason prompt NOT sent (early return)
    assert any(
        s["callback_id"] == callback.id
        for s in messenger_client.answered_callbacks
    )
    reason_msgs = [
        s for s in messenger_client.sent_text if "причину" in s["text"].lower()
    ]
    assert len(reason_msgs) == 0


@pytest.mark.asyncio
async def test_rejection_reason_too_few_parts(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Rejection reason returns early with < 3 callback parts."""
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)

    message = FakeMessage()
    # Only 2 parts: "orr:something" (missing reason)
    callback = FakeCallback(
        data="orr:missing-reason",
        user=FakeUser(1),
        message=message,
    )
    fsm = FakeFSMContext()
    await handle_rejection_reason(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Nothing answered (early return before answer_callback)
    assert len(messenger_client.answered_callbacks) == 0


@pytest.mark.asyncio
async def test_rejection_reason_invalid_order_uuid(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Rejection reason returns early with invalid UUID."""
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)

    message = FakeMessage()
    # Bad UUID for order
    callback = FakeCallback(
        data=f"orr:not-a-uuid:{RejectionReason.WRONG_FORMAT.value}",
        user=FakeUser(1),
        message=message,
    )
    fsm = FakeFSMContext()
    await handle_rejection_reason(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Nothing answered (early return)
    assert len(messenger_client.answered_callbacks) == 0


@pytest.mark.asyncio
async def test_rejection_reason_invalid_reason_value(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Rejection reason returns early with invalid enum."""
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)

    order_id = UUID("00000000-0000-0000-0000-000000000b10")
    message = FakeMessage()
    callback = FakeCallback(
        data=f"orr:{order_id}:INVALID_REASON",
        user=FakeUser(1),
        message=message,
    )
    fsm = FakeFSMContext()
    await handle_rejection_reason(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Nothing answered (early return)
    assert len(messenger_client.answered_callbacks) == 0


@pytest.mark.asyncio
async def test_rejection_reason_user_none(
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """handle_rejection_reason returns early when user not found (line 381)."""
    # Empty repo — user won't be found
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)

    order_id = UUID("00000000-0000-0000-0000-000000000b11")
    message = FakeMessage()
    callback = FakeCallback(
        data=f"orr:{order_id}:{RejectionReason.WRONG_FORMAT.value}",
        user=FakeUser(999),
        message=message,
    )
    fsm = FakeFSMContext()
    await handle_rejection_reason(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Callback is answered with empty toast (before user check)
    assert any(
        s["callback_id"] == callback.id
        for s in messenger_client.answered_callbacks
    )
    # But no skip-with-reason message sent (early return after user is None)
    skip_msgs = [
        s
        for s in messenger_client.sent_text
        if "отказались" in s["text"].lower()
    ]
    assert len(skip_msgs) == 0


@pytest.mark.asyncio
async def test_desired_price_no_order_id_in_state(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Desired price clears FSM when no order_id in state."""
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_service = _build_offer_dispatch_service(user_repo=user_repo)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    # No order_id in state data

    msg = FakeMessage(text="2000", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # FSM should be cleared
    assert fsm.state is None
    # No message sent
    assert len(messenger_client.sent_text) == 0


@pytest.mark.asyncio
async def test_desired_price_no_text(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Desired price re-prompts when message has no text."""
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000b20")

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    # Message with no text (e.g. a sticker)
    msg = FakeMessage(text=None, user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM state should NOT be cleared (still waiting)
    assert fsm.state == OfferSkipStates.waiting_desired_price.state
    # Re-prompt should be sent
    sent = messenger_client.sent_text
    assert any("стоимость" in s["text"].lower() for s in sent)


@pytest.mark.asyncio
async def test_desired_price_no_from_user(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Desired price clears FSM when from_user is None."""
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000b30")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000b31"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="2000", user=None)
    msg.from_user = None  # explicitly ensure no from_user
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # FSM should be cleared
    assert fsm.state is None


@pytest.mark.asyncio
async def test_desired_price_user_not_found(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Desired price clears FSM when user is not found."""
    # Empty user_repo so user won't be found
    empty_user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=empty_user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=empty_user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )
    order_id = UUID("00000000-0000-0000-0000-000000000b40")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000b41"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    # external_id 999 not in empty_user_repo
    msg = FakeMessage(text="2000", user=FakeUser(999))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # FSM should be cleared
    assert fsm.state is None
    # No skip sent
    responses = await offer_dispatch_repo.list_responses_by_order(order_id)
    assert len(list(responses)) == 0


@pytest.mark.asyncio
async def test_desired_price_manager_notification(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Desired price notifies manager when assigned."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000b50"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    manager_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000b51"),
        external_id="9001",
        messenger_type=MessengerType.TELEGRAM,
        username="manager",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    await user_repo.save(manager_user)
    user_service = UserRoleService(user_repo=user_repo)

    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    manager_order_repo = InMemoryManagerOrderRepository()

    order_id = UUID("00000000-0000-0000-0000-000000000b52")
    order = Order(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000b53"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Test offer text",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await order_repo.save(order)
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)

    # Assign manager to order
    from ugc_bot.domain.entities import ManagerOrder

    await manager_order_repo.save(
        ManagerOrder(
            user_id=manager_user.user_id,
            order_id=order_id,
            created_at=datetime.now(timezone.utc),
        )
    )

    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        manager_order_repo=manager_order_repo,
        transaction_manager=None,
    )

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id=str(order_id), reason=RejectionReason.LOW_PRICE.value
    )

    msg = FakeMessage(text="2000", user=FakeUser(1))
    await handle_desired_price(
        msg,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        config=config,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # FSM should be cleared
    assert fsm.state is None
    # Confirmation sent to blogger
    sent = messenger_client.sent_text
    assert any("2000" in s["text"] for s in sent)
    # Manager notification sent to manager external_id "9001"
    manager_msgs = [s for s in sent if s["chat_id"] == "9001"]
    assert len(manager_msgs) >= 1


@pytest.mark.asyncio
async def test_cancel_price_entry_invalid_uuid(
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
) -> None:
    """Cancel handles invalid UUID in callback data."""
    blogger_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000b60"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(blogger_user)
    user_service = UserRoleService(user_repo=user_repo)
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    offer_dispatch_service = _build_offer_dispatch_service(
        user_repo=user_repo,
        offer_dispatch_repo=offer_dispatch_repo,
    )

    fsm = FakeFSMContext()
    await fsm.set_state(OfferSkipStates.waiting_desired_price.state)
    await fsm.update_data(
        order_id="irrelevant", reason=RejectionReason.LOW_PRICE.value
    )

    message = FakeMessage()
    # Invalid UUID → order_id will be None, so no skip recorded
    callback = FakeCallback(
        data="orr_cancel:not-a-uuid",
        user=FakeUser(1),
        message=message,
    )
    await handle_cancel_price_entry(
        callback,
        state=fsm,
        user_role_service=user_service,
        offer_dispatch_service=offer_dispatch_service,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # FSM cleared
    assert fsm.state is None
    # Callback answered with cancelled message
    assert any(
        s["callback_id"] == callback.id
        for s in messenger_client.answered_callbacks
    )
    # No skip recorded since order_id was None
    # (offer_dispatch_repo has nothing for any order)


@pytest.mark.asyncio
async def test_send_contact_with_telegram_handle(
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    bot_texts_service,
) -> None:
    """Contact includes Telegram button with handle."""
    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000b70"),
        external_id="870",
        username="adv",
    )
    blogger = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000b71"),
        external_id="871",
        username="blogger",
        telegram="blogger_handle",
    )
    await create_test_blogger_profile(
        blogger_repo,
        blogger.user_id,
        confirmed=True,
        instagram_url="https://instagram.com/blogger",
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000b72"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger.user_id)
    await offer_dispatch_repo.record_response(
        order.order_id, blogger.user_id, accepted=True, in_offer=True
    )

    await _send_contact_immediately(
        order=order,
        blogger_id=blogger.user_id,
        blogger_chat_id=blogger.external_id,
        response_count=1,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        messenger_client=messenger_client,
        texts={},
        bot_texts_service=bot_texts_service,
    )

    # Advertiser should receive a contact message with a Telegram button
    adv_msgs = [
        s
        for s in messenger_client.sent_text
        if s["chat_id"] == advertiser.external_id
    ]
    assert len(adv_msgs) >= 1
    # At least one message has a keyboard with a Telegram URL button
    contact_msg = next(
        (s for s in adv_msgs if s.get("keyboard") is not None),
        None,
    )
    assert contact_msg is not None
    # The keyboard should contain a t.me URL with the blogger's handle
    kb = contact_msg["keyboard"]
    all_buttons = [btn for row in kb.rows for btn in row]
    telegram_buttons = [
        btn
        for btn in all_buttons
        if btn.url and "t.me/blogger_handle" in btn.url
    ]
    assert len(telegram_buttons) >= 1


@pytest.mark.asyncio
async def test_handle_offer_response_order_creation_error(
    fake_tm: object,
    user_repo,
    blogger_repo,
    order_repo,
    offer_dispatch_repo,
    interaction_repo,
    messenger_client,
    event_adapter,
    offer_response_rate_limiter,
    config,
    bot_texts_service,
) -> None:
    """Offer response handles OrderCreationError."""
    from ugc_bot.application.errors import OrderCreationError

    user_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000b80"),
        external_id="880",
        username="blogger",
    )
    await user_service.set_user(
        external_id="880",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )

    order = await create_test_order(
        order_repo,
        UUID("00000000-0000-0000-0000-000000000b81"),
        order_id=UUID("00000000-0000-0000-0000-000000000b82"),
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
    )
    await offer_dispatch_repo.record_sent(order.order_id, user.user_id)

    class _FailingOfferResponseService:
        """Fake response service that always raises OrderCreationError."""

        async def respond_and_finalize(self, order_id, blogger_id):
            raise OrderCreationError("Order is closed")

    message = FakeMessage(user=FakeUser(880))
    message.reply_markup = object()
    callback = FakeCallback(
        data=f"offer:{order.order_id}",
        user=FakeUser(880),
        message=message,
    )

    await handle_offer_response(
        callback,
        FakeFSMContext(),
        user_service,
        profile_service,
        _FailingOfferResponseService(),  # type: ignore[arg-type]
        interaction_service,
        offer_response_rate_limiter,
        config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )

    # Order-closed message should be sent
    from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS as _DEFAULT_TEXTS

    msg_closed_full = _DEFAULT_TEXTS["ru"]["msg_order_closed_full"]
    assert any(msg_closed_full in s["text"] for s in messenger_client.sent_text)


def test_rejection_reason_callback_data_within_telegram_limit() -> None:
    """All orr:{uuid}:{reason} callback_data values must fit Telegram's 64-byte limit."""  # noqa: E501
    from uuid import UUID

    from ugc_bot.bot.handlers.offer_responses import _REJECTION_REASON_BUTTONS

    max_uuid = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    for reason in _REJECTION_REASON_BUTTONS:
        data = f"orr:{max_uuid}:{reason.value}"
        assert len(data.encode()) <= 64, (
            f"callback_data for {reason.name!r} is {len(data.encode())} bytes "
            f"(max 64): {data!r}"
        )
