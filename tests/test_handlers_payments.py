"""Tests for mock payment handler."""

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
from ugc_bot.infrastructure.kafka.publisher import NoopOrderActivationPublisher


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
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
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

    await mock_pay_order(message, user_service, payment_service)
    assert message.answers


@pytest.mark.asyncio
async def test_mock_pay_handler_blocked_user() -> None:
    """Reject payments for blocked advertisers."""

    user_repo = InMemoryUserRepository()
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000520"),
        external_id="5",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked",
        role=UserRole.ADVERTISER,
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(blocked_user)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage(
        text="/pay_order 123", user=FakeUser(5, "adv", "Adv"), bot=None
    )

    await mock_pay_order(message, user_service, payment_service)

    assert message.answers
    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_mock_pay_handler_order_not_found() -> None:
    """Reject missing orders before payment."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000521"),
        external_id="6",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)

    message = FakeMessage(
        text="/pay_order 00000000-0000-0000-0000-000000000522",
        user=FakeUser(6, "adv", "Adv"),
        bot=None,
    )

    await mock_pay_order(message, user_service, payment_service)

    assert message.answers
    assert "Заказ не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_mock_pay_handler_order_wrong_owner() -> None:
    """Reject payments for чужие заказы."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000523"),
        external_id="7",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    other = User(
        user_id=UUID("00000000-0000-0000-0000-000000000524"),
        external_id="8",
        messenger_type=MessengerType.TELEGRAM,
        username="other",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_repo.save(other)
    user_service = UserRoleService(user_repo=user_repo)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000525"),
        advertiser_id=other.user_id,
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
        text=f"/pay_order {order.order_id}",
        user=FakeUser(7, "adv", "Adv"),
        bot=None,
    )

    await mock_pay_order(message, user_service, payment_service)

    assert message.answers
    assert "не принадлежит" in message.answers[0]


@pytest.mark.asyncio
async def test_mock_pay_handler_order_not_new() -> None:
    """Reject payments for non-NEW orders."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000526"),
        external_id="9",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    user_service = UserRoleService(user_repo=user_repo)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000527"),
        advertiser_id=user.user_id,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    order_repo.save(order)

    message = FakeMessage(
        text=f"/pay_order {order.order_id}",
        user=FakeUser(9, "adv", "Adv"),
        bot=None,
    )

    await mock_pay_order(message, user_service, payment_service)

    assert message.answers
    assert "статусе NEW" in message.answers[0]


@pytest.mark.asyncio
async def test_mock_pay_handler_missing_args() -> None:
    """Reject missing order id argument."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000528"),
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)

    message = FakeMessage(text="/pay_order", user=FakeUser(10, "adv", "Adv"), bot=None)

    await mock_pay_order(message, user_service, payment_service)

    assert message.answers
    assert "Использование" in message.answers[0]


@pytest.mark.asyncio
async def test_mock_pay_handler_invalid_order_id() -> None:
    """Reject invalid order id format."""

    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    payment_service = PaymentService(
        user_repo=user_repo,
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000529"),
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)

    message = FakeMessage(
        text="/pay_order not-a-uuid",
        user=FakeUser(11, "adv", "Adv"),
        bot=None,
    )

    await mock_pay_order(message, user_service, payment_service)

    assert message.answers
    assert "Неверный формат" in message.answers[0]
