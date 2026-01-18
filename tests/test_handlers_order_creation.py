"""Tests for order creation handlers."""

from __future__ import annotations

import pytest

from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.order_creation import (
    handle_bloggers_needed,
    handle_offer_text,
    handle_price,
    handle_product_link,
    handle_ugc_requirements,
    start_order_creation,
)
from ugc_bot.domain.enums import MessengerType, UserRole
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryUserRepository,
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


class FakeFSMContext:
    """Minimal FSM context for tests."""

    def __init__(self) -> None:
        self._data: dict = {}
        self.state = None

    async def update_data(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self._data.update(kwargs)

    async def set_state(self, state) -> None:  # type: ignore[no-untyped-def]
        self.state = state

    async def get_data(self) -> dict:  # type: ignore[no-untyped-def]
        return dict(self._data)

    async def clear(self) -> None:
        self._data.clear()
        self.state = None


@pytest.mark.asyncio
async def test_start_order_creation_requires_role() -> None:
    """Require advertiser role before creation."""

    repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=repo)
    order_service = OrderService(user_repo=repo, order_repo=InMemoryOrderRepository())
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await start_order_creation(message, state, user_service, order_service)
    assert "Please choose role" in message.answers[0]


@pytest.mark.asyncio
async def test_order_creation_flow_new_advertiser() -> None:
    """New advertisers skip barter step."""

    repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    user_service = UserRoleService(user_repo=repo)
    order_service = OrderService(user_repo=repo, order_repo=order_repo)
    user_service.set_role(
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
    )

    message = FakeMessage(text=None, user=FakeUser(5, "adv", "Adv"))
    state = FakeFSMContext()
    await start_order_creation(message, state, user_service, order_service)
    assert state._data["is_new"] is True

    await handle_product_link(FakeMessage(text="https://example.com", user=None), state)
    await handle_offer_text(FakeMessage(text="Offer", user=None), state)
    await handle_ugc_requirements(FakeMessage(text="пропустить", user=None), state)
    await handle_price(FakeMessage(text="1000", user=None), state)
    await handle_bloggers_needed(FakeMessage(text="3", user=None), state, order_service)

    assert len(order_repo.orders) == 1
