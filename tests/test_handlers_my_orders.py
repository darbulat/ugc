"""Tests for my orders handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.my_orders import paginate_orders, show_my_orders
from ugc_bot.domain.entities import Order, OrderResponse, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
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

    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = FakeUser(1)
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response."""

        self.answers.append(text)

    async def edit_text(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture edited response."""

        self.answers.append(text)


class FakeCallback:
    """Minimal callback stub."""

    def __init__(self, data: str, message: FakeMessage) -> None:
        self.data = data
        self.message = message
        self.from_user = FakeUser(1)
        self.answers: list[str] = []

    async def answer(self, text: str = "") -> None:
        """Capture callback response."""

        if text:
            self.answers.append(text)


def _add_advertiser_profile(
    user_repo: InMemoryUserRepository,
    user_id: UUID,
    contact: str = "contact",
) -> None:
    """Seed advertiser profile fields on user."""

    user = user_repo.get_by_id(user_id)
    if user is None:
        return
    user_repo.save(
        User(
            user_id=user.user_id,
            external_id=user.external_id,
            messenger_type=user.messenger_type,
            username=user.username,
            role=UserRole.ADVERTISER,
            status=user.status,
            issue_count=user.issue_count,
            created_at=user.created_at,
            instagram_url=None,
            confirmed=False,
            topics=user.topics,
            audience_gender=user.audience_gender,
            audience_age_min=user.audience_age_min,
            audience_age_max=user.audience_age_max,
            audience_geo=user.audience_geo,
            price=user.price,
            contact=contact,
            profile_updated_at=user.profile_updated_at,
        )
    )


@pytest.mark.asyncio
async def test_my_orders_no_advertiser_profile() -> None:
    """Show hint when advertiser profile is missing."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(user_repo=user_repo)
    order_service = OrderService(
        user_repo=user_repo,
        order_repo=order_repo,
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=InMemoryOrderResponseRepository(),
    )

    user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text="Мои заказы")
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    assert "Профиль рекламодателя не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_empty() -> None:
    """Show hint when no orders exist."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(user_repo=user_repo)
    order_service = OrderService(
        user_repo=user_repo,
        order_repo=order_repo,
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=InMemoryOrderResponseRepository(),
    )

    user = user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
    )
    _add_advertiser_profile(user_repo, user.user_id)

    message = FakeMessage(text="/my_orders")
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    assert "пока нет заказов" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_list() -> None:
    """List existing orders."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(user_repo=user_repo)
    order_service = OrderService(
        user_repo=user_repo,
        order_repo=order_repo,
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=InMemoryOrderResponseRepository(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact="contact",
        profile_updated_at=None,
    )
    user_repo.save(user)
    _add_advertiser_profile(user_repo, user.user_id)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        advertiser_id=user.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    message = FakeMessage(text="Мои заказы")
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    assert str(order.order_id) in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_pagination() -> None:
    """Paginate orders list."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(user_repo=user_repo)
    order_service = OrderService(
        user_repo=user_repo,
        order_repo=order_repo,
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=InMemoryOrderResponseRepository(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000910"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact="contact",
        profile_updated_at=None,
    )
    user_repo.save(user)
    _add_advertiser_profile(user_repo, user.user_id)
    for idx in range(6):
        order_repo.save(
            Order(
                order_id=UUID(f"00000000-0000-0000-0000-00000000091{idx}"),
                advertiser_id=user.user_id,
                product_link="https://example.com",
                offer_text="Offer",
                ugc_requirements=None,
                barter_description=None,
                price=1000.0 + idx,
                bloggers_needed=3,
                status=OrderStatus.NEW,
                created_at=datetime.now(timezone.utc),
                contacts_sent_at=None,
            )
        )

    message = FakeMessage(text="Мои заказы")
    callback = FakeCallback(data="my_orders:2", message=message)
    await paginate_orders(
        callback, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    assert "страница 2/2" in message.answers[-1]


@pytest.mark.asyncio
async def test_my_orders_with_complaint_button() -> None:
    """Show complaint button for closed orders with responses."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(user_repo=user_repo)
    order_service = OrderService(
        user_repo=user_repo,
        order_repo=order_repo,
    )
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=response_repo,
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000920"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact="contact",
        profile_updated_at=None,
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000921"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        instagram_url=None,
        confirmed=False,
        topics=None,
        audience_gender=None,
        audience_age_min=None,
        audience_age_max=None,
        audience_geo=None,
        price=None,
        contact=None,
        profile_updated_at=None,
    )
    user_repo.save(user)
    user_repo.save(blogger)
    _add_advertiser_profile(user_repo, user.user_id)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000922"),
        advertiser_id=user.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=datetime.now(timezone.utc),
    )
    order_repo.save(order)

    response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000923"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    message = FakeMessage(text="Мои заказы")
    await show_my_orders(
        message, user_service, profile_service, order_service, offer_response_service
    )

    assert message.answers
    assert str(order.order_id) in message.answers[0]
