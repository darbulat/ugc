"""Tests for Telegram payment service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.entities import AdvertiserProfile, Order, Payment, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, PaymentStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
    NoopOfferBroadcaster,
)
from ugc_bot.infrastructure.kafka.publisher import NoopOrderActivationPublisher


def _service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    order_repo: InMemoryOrderRepository,
    payment_repo: InMemoryPaymentRepository,
) -> PaymentService:
    """Build payment service."""

    return PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        activation_publisher=NoopOrderActivationPublisher(),
    )


def _seed_user(
    repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
) -> UUID:
    """Seed advertiser user."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000400"),
        external_id="777",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(user)
    advertiser_repo.save(AdvertiserProfile(user_id=user.user_id, contact="contact"))
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


def test_confirm_payment_success() -> None:
    """Confirm payment activates order and stores payment."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = _seed_user(user_repo, advertiser_repo)
    order_id = _seed_order(order_repo, user_id)

    service = _service(user_repo, advertiser_repo, order_repo, payment_repo)
    payment = service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )

    assert payment.status == PaymentStatus.PAID
    assert payment.amount == 1000.0
    assert order_repo.get_by_id(order_id).status == OrderStatus.ACTIVE


def test_confirm_payment_idempotent() -> None:
    """Return existing payment if already paid."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = _seed_user(user_repo, advertiser_repo)
    order_id = _seed_order(order_repo, user_id)
    payment_repo.save(
        Payment(
            payment_id=UUID("00000000-0000-0000-0000-000000000450"),
            order_id=order_id,
            provider="yookassa_telegram",
            status=PaymentStatus.PAID,
            amount=1000.0,
            currency="RUB",
            external_id="charge_1",
            created_at=datetime.now(timezone.utc),
            paid_at=datetime.now(timezone.utc),
        )
    )

    service = _service(user_repo, advertiser_repo, order_repo, payment_repo)
    payment = service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )
    assert payment.payment_id == UUID("00000000-0000-0000-0000-000000000450")


def test_confirm_payment_invalid_user() -> None:
    """Fail when user missing."""

    service = _service(
        InMemoryUserRepository(),
        InMemoryAdvertiserProfileRepository(),
        InMemoryOrderRepository(),
        InMemoryPaymentRepository(),
    )

    with pytest.raises(UserNotFoundError):
        service.confirm_telegram_payment(
            UUID("00000000-0000-0000-0000-000000000402"),
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


def test_confirm_payment_missing_profile() -> None:
    """Fail when advertiser profile missing."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000490"),
        external_id="888",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(user)
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo)
    with pytest.raises(OrderCreationError):
        service.confirm_telegram_payment(
            user.user_id,
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


def test_confirm_payment_order_not_found() -> None:
    """Fail when order does not exist."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = _seed_user(user_repo, advertiser_repo)
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo)
    with pytest.raises(OrderCreationError):
        service.confirm_telegram_payment(
            user_id,
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


def test_confirm_payment_wrong_owner() -> None:
    """Fail when order belongs to another advertiser."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = _seed_user(user_repo, advertiser_repo)
    other_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000491"),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="other",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    user_repo.save(other_user)
    order_repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000492"),
            advertiser_id=other_user.user_id,
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
    )
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo)
    with pytest.raises(OrderCreationError):
        service.confirm_telegram_payment(
            user_id,
            UUID("00000000-0000-0000-0000-000000000492"),
            "charge",
            1000,
            "RUB",
        )


def test_confirm_payment_order_not_new() -> None:
    """Fail when order is not NEW."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = _seed_user(user_repo, advertiser_repo)
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
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo)
    with pytest.raises(OrderCreationError):
        service.confirm_telegram_payment(
            user_id,
            order_id,
            "charge",
            1000,
            "RUB",
        )
