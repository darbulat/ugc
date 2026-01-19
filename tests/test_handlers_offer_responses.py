"""Tests for offer response handler."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.offer_responses import handle_offer_response
from ugc_bot.domain.entities import Order, User
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

    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        """Capture response."""

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


@pytest.mark.asyncio
async def test_offer_response_handler_success() -> None:
    """Blogger can respond to offer."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    response_repo = InMemoryOrderResponseRepository()
    user_service = UserRoleService(user_repo=user_repo)
    response_service = OfferResponseService(
        order_repo=order_repo, response_repo=response_repo
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000700"),
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service.set_role(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        role=UserRole.BLOGGER,
    )

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

    await handle_offer_response(callback, user_service, response_service)
    assert callback.answers
    assert response_repo.list_by_order(order.order_id)
