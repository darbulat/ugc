"""Tests for mock payment handler."""

from __future__ import annotations

import pytest
from uuid import UUID
from datetime import datetime, timezone

from ugc_bot.application.ports import BloggerRelevanceSelector
from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.payments import mock_pay_order
from ugc_bot.domain.entities import BloggerProfile, Order, User
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    UserRole,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
    NoopOfferBroadcaster,
)


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int, username: str | None, first_name: str) -> None:
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(self, text: str | None, user: FakeUser | None, bot) -> None:
        self.text = text
        self.from_user = user
        self.bot = bot
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response text."""

        self.answers.append(text)


@pytest.mark.asyncio
async def test_mock_pay_handler_success() -> None:
    """Mock payment handler activates order."""

    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
    )

    class FakeSelector(BloggerRelevanceSelector):
        """Fake selector for tests."""

        def select(self, order, profiles, limit):  # type: ignore[no-untyped-def]
            return [profile.user_id for profile in profiles][:limit]

    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        relevance_selector=FakeSelector(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000500"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_role(
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
    )

    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000502"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blogger)
    blogger_repo.save(
        BloggerProfile(
            user_id=blogger.user_id,
            instagram_url="https://instagram.com/blogger",
            confirmed=True,
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            updated_at=datetime.now(timezone.utc),
        )
    )

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000501"),
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

    class FakeBot:
        def __init__(self) -> None:
            self.sent: list[tuple[int, str]] = []

        async def send_message(
            self, chat_id: int, text: str, reply_markup=None
        ) -> None:  # type: ignore[no-untyped-def]
            self.sent.append((chat_id, text))

    bot = FakeBot()
    message = FakeMessage(
        text=f"/pay_order {order.order_id}",
        user=FakeUser(1, "adv", "Adv"),
        bot=bot,
    )

    await mock_pay_order(message, user_service, payment_service, offer_dispatch_service)
    assert message.answers
    assert "Оплата зафиксирована" in message.answers[-1]
    assert bot.sent
