"""Tests for mock payment service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserRole, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
    NoopOfferBroadcaster,
)
from ugc_bot.infrastructure.kafka.publisher import NoopOrderActivationPublisher


def _seed_user(repo: InMemoryUserRepository) -> UUID:
    """Seed advertiser user."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000400"),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(user)
    return user.user_id


def _seed_order(repo: InMemoryOrderRepository, user_id: UUID) -> UUID:
    """Seed order."""

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000401"),
        advertiser_id=user_id,
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
    repo.save(order)
    return order.order_id


def test_mock_pay_success() -> None:
    """Mock payment activates order."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    broadcaster = NoopOfferBroadcaster()
    user_id = _seed_user(user_repo)
    order_id = _seed_order(order_repo, user_id)

    service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=broadcaster,
        activation_publisher=NoopOrderActivationPublisher(),
    )

    payment = service.mock_pay(user_id, order_id)
    assert payment.order_id == order_id
    assert order_repo.get_by_id(order_id).status == OrderStatus.ACTIVE


def test_mock_pay_invalid_user() -> None:
    """Fail when user missing."""

    service = PaymentService(
        user_repo=InMemoryUserRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    with pytest.raises(UserNotFoundError):
        service.mock_pay(UUID("00000000-0000-0000-0000-000000000402"), UUID(int=0))


def test_mock_pay_wrong_order_status() -> None:
    """Fail when order not NEW."""

    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = _seed_user(user_repo)
    order_id = _seed_order(order_repo, user_id)
    order = order_repo.get_by_id(order_id)
    order_repo.save(
        Order(
            order_id=order.order_id,
            advertiser_id=order.advertiser_id,
            product_link=order.product_link,
            offer_text=order.offer_text,
            ugc_requirements=order.ugc_requirements,
            barter_description=order.barter_description,
            price=order.price,
            bloggers_needed=order.bloggers_needed,
            status=OrderStatus.ACTIVE,
            created_at=order.created_at,
            contacts_sent_at=order.contacts_sent_at,
        )
    )

    service = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )

    with pytest.raises(OrderCreationError):
        service.mock_pay(user_id, order_id)
