"""Tests for offer response handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.offer_responses import (
    _maybe_send_contacts_and_close,
    handle_offer_response,
)
from ugc_bot.domain.entities import BloggerProfile, Order, OrderResponse, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryInteractionRepository,
    InMemoryOrderRepository,
    InMemoryOrderResponseRepository,
    InMemoryUserRepository,
)


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeMessage:
    """Minimal message stub."""

    def __init__(self) -> None:
        self.answers: list[str] = []
        self.bot = None

    async def answer(self, text: str) -> None:
        """Capture response."""

        self.answers.append(text)

    async def send_message(self, chat_id: int, text: str) -> None:  # type: ignore[no-untyped-def]
        """Capture advertiser messages."""

        self.answers.append(text)


class FakeCallback:
    """Minimal callback stub."""

    def __init__(self, data: str, user: FakeUser, message: FakeMessage) -> None:
        self.data = data
        self.from_user = user
        self.message = message
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        """Capture callback answer."""

        self.answers.append(text)


def _profile_service(
    user_repo: InMemoryUserRepository,
    blogger_repo: InMemoryBloggerProfileRepository,
) -> ProfileService:
    """Build profile service for tests."""

    return ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=InMemoryAdvertiserProfileRepository(),
    )


def _add_blogger_profile(
    blogger_repo: InMemoryBloggerProfileRepository,
    user_id: UUID,
    confirmed: bool = True,
) -> None:
    """Seed blogger profile."""

    blogger_repo.save(
        BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            confirmed=confirmed,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_contacts_sent_and_order_closed() -> None:
    """Send contacts and close order when limit reached."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000740"),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser)
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000741"),
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blogger)
    _add_blogger_profile(blogger_repo, blogger.user_id, confirmed=True)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000742"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)
    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000743"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    bot = FakeMessage()
    await _maybe_send_contacts_and_close(
        order_id=order.order_id,
        offer_response_service=response_service,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        bot=bot,
    )

    updated = order_repo.get_by_id(order.order_id)
    assert updated is not None
    assert updated.status == OrderStatus.CLOSED
    assert updated.contacts_sent_at is not None
    assert any("Контакты блогеров" in answer for answer in bot.answers)


@pytest.mark.asyncio
async def test_offer_response_handler_success() -> None:
    """Blogger can respond to offer."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000700"),
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000701"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000702"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(10), message=message
    )

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )
    assert callback.answers
    assert response_repo.list_by_order(order.order_id)


@pytest.mark.asyncio
async def test_offer_response_handler_blocked_user() -> None:
    """Reject blocked bloggers early."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000710"),
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blocked_user)
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    message = FakeMessage()
    callback = FakeCallback(data="offer:123", user=FakeUser(11), message=message)

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Заблокированные" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_order_not_active() -> None:
    """Reject responses for inactive orders."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000711"),
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_user(
        external_id="12",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000712"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000713"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(12), message=message
    )

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Заказ не активен" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_order_not_found() -> None:
    """Reject responses for unknown order."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000714"),
        external_id="13",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    message = FakeMessage()
    callback = FakeCallback(
        data="offer:00000000-0000-0000-0000-000000000999",
        user=FakeUser(13),
        message=message,
    )

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Заказ не найден" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_already_responded() -> None:
    """Reject duplicate responses."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000715"),
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_user(
        external_id="14",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000716"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000717"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=2,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)
    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000718"),
            order_id=order.order_id,
            blogger_id=user.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(14), message=message
    )

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "уже откликались" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_limit_reached() -> None:
    """Reject responses when limit reached."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000719"),
        external_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_user(
        external_id="15",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000720"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000721"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)
    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000722"),
            order_id=order.order_id,
            blogger_id=UUID("00000000-0000-0000-0000-000000000723"),
            responded_at=datetime.now(timezone.utc),
        )
    )

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(15), message=message
    )

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Лимит откликов" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_no_from_user() -> None:
    """Handle callback without from_user."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(data="offer:123", user=FakeUser(999), message=message)
    callback.from_user = None

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert not callback.answers


@pytest.mark.asyncio
async def test_offer_response_handler_user_not_found() -> None:
    """Reject when user is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(data="offer:123", user=FakeUser(999), message=message)

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Пользователь не найден" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_paused_user() -> None:
    """Reject paused bloggers."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    paused_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000730"),
        external_id="16",
        messenger_type=MessengerType.TELEGRAM,
        username="paused",
        status=UserStatus.PAUSE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(paused_user)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(data="offer:123", user=FakeUser(16), message=message)

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "паузе" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_no_blogger_profile() -> None:
    """Reject when blogger profile is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000731"),
        external_id="17",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage()
    callback = FakeCallback(data="offer:123", user=FakeUser(17), message=message)

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Профиль блогера не заполнен" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_unconfirmed_profile() -> None:
    """Reject when Instagram is not confirmed."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000732"),
        external_id="18",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=False)

    message = FakeMessage()
    callback = FakeCallback(data="offer:123", user=FakeUser(18), message=message)

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Подтвердите Instagram" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_invalid_uuid() -> None:
    """Reject invalid UUID in callback data."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    interaction_repo = InMemoryInteractionRepository()
    response_service = OfferResponseService(
        order_repo=InMemoryOrderRepository(),
        response_repo=InMemoryOrderResponseRepository(),
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000733"),
        external_id="19",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    message = FakeMessage()
    callback = FakeCallback(data="offer:not-a-uuid", user=FakeUser(19), message=message)

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert "Неверный идентификатор" in callback.answers[0]


@pytest.mark.asyncio
async def test_offer_response_handler_exception() -> None:
    """Handle exceptions gracefully."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000734"),
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
    )
    _add_blogger_profile(blogger_repo, user.user_id, confirmed=True)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000735"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000736"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    # Mock response_repo.save to raise exception
    original_save = response_repo.save

    def failing_save(response):
        raise Exception("Test exception")

    response_repo.save = failing_save  # type: ignore[assignment]

    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer:{order.order_id}", user=FakeUser(20), message=message
    )

    await handle_offer_response(
        callback, user_service, profile_service, response_service, interaction_service
    )

    assert callback.answers
    assert any("ошибка" in ans.lower() for ans in callback.answers)

    # Restore original method
    response_repo.save = original_save


@pytest.mark.asyncio
async def test_maybe_send_contacts_order_not_found() -> None:
    """Handle missing order gracefully."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    bot = FakeMessage()
    await _maybe_send_contacts_and_close(
        order_id=UUID("00000000-0000-0000-0000-000000000999"),
        offer_response_service=response_service,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        bot=bot,
    )

    assert not bot.answers


@pytest.mark.asyncio
async def test_maybe_send_contacts_order_not_active() -> None:
    """Skip sending contacts for inactive orders."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000800"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000801"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    bot = FakeMessage()
    await _maybe_send_contacts_and_close(
        order_id=order.order_id,
        offer_response_service=response_service,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        bot=bot,
    )

    assert not bot.answers


@pytest.mark.asyncio
async def test_maybe_send_contacts_missing_user_or_profile() -> None:
    """Skip sending contacts when user or profile is missing."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    interaction_repo = InMemoryInteractionRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )
    interaction_service = InteractionService(interaction_repo=interaction_repo)
    profile_service = _profile_service(user_repo, blogger_repo)

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000810"),
        external_id="810",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(advertiser)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000811"),
        advertiser_id=advertiser.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    # Response with non-existent blogger
    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000812"),
            order_id=order.order_id,
            blogger_id=UUID("00000000-0000-0000-0000-000000000999"),
            responded_at=datetime.now(timezone.utc),
        )
    )

    bot = FakeMessage()
    await _maybe_send_contacts_and_close(
        order_id=order.order_id,
        offer_response_service=response_service,
        user_role_service=user_service,
        profile_service=profile_service,
        interaction_service=interaction_service,
        bot=bot,
    )

    # Should still close order but skip missing blogger
    updated = order_repo.get_by_id(order.order_id)
    assert updated is not None
    assert updated.status == OrderStatus.CLOSED
