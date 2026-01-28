"""Tests for Telegram payment service."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, Mock

from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.entities import AdvertiserProfile, Order, Payment, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, PaymentStatus, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
    InMemoryOrderRepository,
    InMemoryOutboxRepository,
    InMemoryPaymentRepository,
    InMemoryUserRepository,
    NoopOfferBroadcaster,
)


def _service(
    user_repo: InMemoryUserRepository,
    advertiser_repo: InMemoryAdvertiserProfileRepository,
    order_repo: InMemoryOrderRepository,
    payment_repo: InMemoryPaymentRepository,
    transaction_manager: object,
) -> PaymentService:
    """Build payment service with required transaction_manager."""

    outbox_repo = InMemoryOutboxRepository()
    outbox_publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)

    return PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        outbox_publisher=outbox_publisher,
        transaction_manager=transaction_manager,
    )


async def _seed_user(
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
    await repo.save(user)
    await advertiser_repo.save(
        AdvertiserProfile(user_id=user.user_id, contact="contact")
    )
    return user.user_id


async def _seed_order(repo: InMemoryOrderRepository, user_id: UUID) -> UUID:
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
    await repo.save(order)
    return order.order_id


@pytest.mark.asyncio
async def test_confirm_payment_success(fake_tm: object) -> None:
    """Confirm payment activates order and stores payment."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = await _seed_user(user_repo, advertiser_repo)
    order_id = await _seed_order(order_repo, user_id)

    service = _service(user_repo, advertiser_repo, order_repo, payment_repo, fake_tm)
    payment = await service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )

    assert payment.status == PaymentStatus.PAID
    assert payment.amount == 1000.0

    # Order should still be NEW until outbox is processed
    order = await order_repo.get_by_id(order_id)
    assert order is not None
    assert order.status == OrderStatus.NEW

    # Process outbox events to activate order
    from ugc_bot.infrastructure.kafka.publisher import NoopOrderActivationPublisher

    kafka_publisher = NoopOrderActivationPublisher()
    await service.outbox_publisher.process_pending_events(
        kafka_publisher, max_retries=3
    )

    # Now order should be activated
    order = await order_repo.get_by_id(order_id)
    assert order is not None
    assert order.status == OrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_confirm_payment_idempotent(fake_tm: object) -> None:
    """Return existing payment if already paid."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = await _seed_user(user_repo, advertiser_repo)
    order_id = await _seed_order(order_repo, user_id)
    await payment_repo.save(
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

    service = _service(user_repo, advertiser_repo, order_repo, payment_repo, fake_tm)
    payment = await service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )
    assert payment.payment_id == UUID("00000000-0000-0000-0000-000000000450")


@pytest.mark.asyncio
async def test_confirm_payment_requires_transaction_manager() -> None:
    """Raise when transaction_manager is None."""
    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = await _seed_user(user_repo, advertiser_repo)
    order_id = await _seed_order(order_repo, user_id)
    outbox_repo = InMemoryOutboxRepository()
    outbox_publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
    service = PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        outbox_publisher=outbox_publisher,
        transaction_manager=None,
    )
    with pytest.raises(ValueError, match="transaction_manager"):
        await service.confirm_telegram_payment(
            user_id=user_id,
            order_id=order_id,
            provider_payment_charge_id="charge_1",
            total_amount=100000,
            currency="RUB",
        )


@pytest.mark.asyncio
async def test_confirm_payment_invalid_user(fake_tm: object) -> None:
    """Fail when user missing."""

    service = _service(
        InMemoryUserRepository(),
        InMemoryAdvertiserProfileRepository(),
        InMemoryOrderRepository(),
        InMemoryPaymentRepository(),
        fake_tm,
    )

    with pytest.raises(UserNotFoundError):
        await service.confirm_telegram_payment(
            UUID("00000000-0000-0000-0000-000000000402"),
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


@pytest.mark.asyncio
async def test_confirm_payment_missing_profile(fake_tm: object) -> None:
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
    await user_repo.save(user)
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo, fake_tm)
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user.user_id,
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


@pytest.mark.asyncio
async def test_confirm_payment_uses_transaction_manager() -> None:
    """Confirm payment uses transaction manager session."""

    user_id = UUID("00000000-0000-0000-0000-000000000501")
    order_id = UUID("00000000-0000-0000-0000-000000000502")
    user = User(
        user_id=user_id,
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    order = Order(
        order_id=order_id,
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
    payment_repo = Mock()
    payment_repo.get_by_order = AsyncMock(return_value=None)
    payment_repo.save = AsyncMock()
    user_repo = Mock()
    user_repo.get_by_id = AsyncMock(return_value=user)
    advertiser_repo = Mock()
    advertiser_repo.get_by_user_id = AsyncMock(
        return_value=AdvertiserProfile(user_id=user_id, contact="contact")
    )
    order_repo = Mock()
    order_repo.get_by_id = AsyncMock(return_value=order)
    outbox_publisher = Mock()
    outbox_publisher.publish_order_activation = AsyncMock()

    session_marker = object()

    @asynccontextmanager
    async def fake_transaction():
        yield session_marker

    transaction_manager = Mock()
    transaction_manager.transaction = fake_transaction

    service = PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        outbox_publisher=outbox_publisher,
        transaction_manager=transaction_manager,
    )

    await service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )

    payment_repo.save.assert_called_once()
    # Check that save was called with session parameter
    call_kwargs = payment_repo.save.call_args.kwargs
    assert "session" in call_kwargs
    assert call_kwargs["session"] is session_marker
    outbox_publisher.publish_order_activation.assert_called_once()
    # Check that publish_order_activation was called with session parameter
    pub_call_kwargs = outbox_publisher.publish_order_activation.call_args.kwargs
    assert "session" in pub_call_kwargs
    assert pub_call_kwargs["session"] is session_marker


@pytest.mark.asyncio
async def test_confirm_payment_order_not_found(fake_tm: object) -> None:
    """Fail when order does not exist."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = await _seed_user(user_repo, advertiser_repo)
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo, fake_tm)
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user_id,
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


@pytest.mark.asyncio
async def test_confirm_payment_wrong_owner(fake_tm: object) -> None:
    """Fail when order belongs to another advertiser."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = await _seed_user(user_repo, advertiser_repo)
    other_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000491"),
        external_id="999",
        messenger_type=MessengerType.TELEGRAM,
        username="other",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(other_user)
    await order_repo.save(
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
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo, fake_tm)
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user_id,
            UUID("00000000-0000-0000-0000-000000000492"),
            "charge",
            1000,
            "RUB",
        )


@pytest.mark.asyncio
async def test_confirm_payment_order_not_new(fake_tm: object) -> None:
    """Fail when order is not NEW."""

    user_repo = InMemoryUserRepository()
    advertiser_repo = InMemoryAdvertiserProfileRepository()
    order_repo = InMemoryOrderRepository()
    payment_repo = InMemoryPaymentRepository()
    user_id = await _seed_user(user_repo, advertiser_repo)
    order_id = await _seed_order(order_repo, user_id)
    order = await order_repo.get_by_id(order_id)
    assert order is not None
    await order_repo.save(
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
    service = _service(user_repo, advertiser_repo, order_repo, payment_repo, fake_tm)
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user_id,
            order_id,
            "charge",
            1000,
            "RUB",
        )
