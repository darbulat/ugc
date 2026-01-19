"""Tests for my orders handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.my_orders import paginate_orders, show_my_orders
from ugc_bot.domain.entities import AdvertiserProfile, Order, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryBloggerProfileRepository,
    InMemoryOrderRepository,
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


@pytest.mark.asyncio
async def test_my_orders_no_advertiser_profile() -> None:
    """Show hint when advertiser profile is missing."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
    )
    order_service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text="Мои заказы")
    await show_my_orders(message, user_service, profile_service, order_service)

    assert message.answers
    assert "Профиль рекламодателя не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_empty() -> None:
    """Show hint when no orders exist."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
    )
    order_service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    user = user_service.set_user(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    advertiser_repo.save(AdvertiserProfile(user_id=user.user_id, contact="contact"))

    message = FakeMessage(text="/my_orders")
    await show_my_orders(message, user_service, profile_service, order_service)

    assert message.answers
    assert "пока нет заказов" in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_list() -> None:
    """List existing orders."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
    )
    order_service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000900"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    advertiser_repo.save(AdvertiserProfile(user_id=user.user_id, contact="contact"))
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
    await show_my_orders(message, user_service, profile_service, order_service)

    assert message.answers
    assert str(order.order_id) in message.answers[0]


@pytest.mark.asyncio
async def test_my_orders_pagination() -> None:
    """Paginate orders list."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        advertiser_repo=advertiser_repo,
    )
    order_service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000910"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    advertiser_repo.save(AdvertiserProfile(user_id=user.user_id, contact="contact"))
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
    await paginate_orders(callback, user_service, profile_service, order_service)

    assert message.answers
    assert "страница 2/2" in message.answers[-1]
