"""Tests for mock payment handler."""

from __future__ import annotations

import pytest
from uuid import UUID
from datetime import datetime, timezone

from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.payments import mock_pay_order
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
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

    def __init__(self, text: str | None, user: FakeUser | None) -> None:
        self.text = text
        self.from_user = user
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response text."""

        self.answers.append(text)


@pytest.mark.asyncio
async def test_mock_pay_handler_success() -> None:
    """Mock payment handler activates order."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
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

    message = FakeMessage(
        text=f"/pay_order {order.order_id}", user=FakeUser(1, "adv", "Adv")
    )

    await mock_pay_order(message, user_service, payment_service)
    assert message.answers
    assert "Оплата зафиксирована" in message.answers[-1]
