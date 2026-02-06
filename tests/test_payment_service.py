"""Tests for Telegram payment service."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

from tests.helpers.factories import create_test_advertiser, create_test_order
from tests.helpers.services import build_payment_service
from ugc_bot.application.errors import OrderCreationError, UserNotFoundError
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.entities import AdvertiserProfile, Order, Payment, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    PaymentStatus,
    UserStatus,
)


@pytest.mark.asyncio
async def test_confirm_payment_success(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Confirm payment activates order and stores payment."""

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    order_id = order.order_id

    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
    payment = await service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )

    assert payment.status == PaymentStatus.PAID
    assert payment.amount == 1000.0

    # Order goes to PENDING_MODERATION after payment
    order = await order_repo.get_by_id(order_id)
    assert order is not None
    assert order.status == OrderStatus.PENDING_MODERATION


@pytest.mark.asyncio
async def test_confirm_payment_idempotent(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Return existing payment if already paid."""

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    order_id = order.order_id
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

    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
    payment = await service.confirm_telegram_payment(
        user_id=user_id,
        order_id=order_id,
        provider_payment_charge_id="charge_1",
        total_amount=100000,
        currency="RUB",
    )
    assert payment.payment_id == UUID("00000000-0000-0000-0000-000000000450")


@pytest.mark.asyncio
async def test_confirm_payment_requires_transaction_manager(
    user_repo, advertiser_repo, order_repo, payment_repo
) -> None:
    """Raise when transaction_manager is None."""
    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    order_id = order.order_id
    service = PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
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
async def test_confirm_payment_invalid_user(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Fail when user missing."""

    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
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
async def test_confirm_payment_missing_profile(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Fail when advertiser profile missing."""

    from tests.helpers.factories import create_test_user

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000490"),
        external_id="888",
        username="adv",
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
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
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    payment_repo = Mock()
    payment_repo.get_by_order = AsyncMock(return_value=None)
    payment_repo.save = AsyncMock()
    user_repo = Mock()
    user_repo.get_by_id = AsyncMock(return_value=user)
    advertiser_repo = Mock()
    advertiser_repo.get_by_user_id = AsyncMock(
        return_value=AdvertiserProfile(
            user_id=user_id,
            phone="contact",
            brand="Brand",
        )
    )
    order_repo = Mock()
    order_repo.get_by_id = AsyncMock(return_value=order)
    order_repo.save = AsyncMock()

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
    call_kwargs = payment_repo.save.call_args.kwargs
    assert "session" in call_kwargs
    assert call_kwargs["session"] is session_marker

    order_repo.save.assert_called_once()
    saved_order = order_repo.save.call_args[0][0]
    assert saved_order.status == OrderStatus.PENDING_MODERATION


@pytest.mark.asyncio
async def test_confirm_payment_order_not_found(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Fail when order does not exist."""

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user_id,
            UUID(int=0),
            "charge",
            1000,
            "RUB",
        )


@pytest.mark.asyncio
async def test_confirm_payment_wrong_owner(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Fail when order belongs to another advertiser."""

    from tests.helpers.factories import create_test_order, create_test_user

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    other_user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000491"),
        external_id="999",
        username="other",
    )
    await create_test_order(
        order_repo,
        other_user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000492"),
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user_id,
            UUID("00000000-0000-0000-0000-000000000492"),
            "charge",
            1000,
            "RUB",
        )


@pytest.mark.asyncio
async def test_get_order_with_transaction_manager(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """get_order uses transaction_manager when provided."""

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
    found = await service.get_order(order.order_id)
    assert found is not None
    assert found.order_id == order.order_id


@pytest.mark.asyncio
async def test_get_order_without_transaction_manager(
    user_repo, advertiser_repo, order_repo, payment_repo
) -> None:
    """get_order uses order_repo directly when transaction_manager is None."""

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    service = PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        transaction_manager=None,
    )
    found = await service.get_order(order.order_id)
    assert found is not None
    assert found.order_id == order.order_id


@pytest.mark.asyncio
async def test_confirm_payment_order_not_new(
    fake_tm: object,
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    outbox_repo,
) -> None:
    """Fail when order is not NEW."""

    user_id = await create_test_advertiser(user_repo, advertiser_repo)
    order = await create_test_order(order_repo, user_id)
    order_id = order.order_id
    await create_test_order(
        order_repo,
        order.advertiser_id,
        order_id=order.order_id,
        status=OrderStatus.ACTIVE,
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        fake_tm,
    )
    with pytest.raises(OrderCreationError):
        await service.confirm_telegram_payment(
            user_id,
            order_id,
            "charge",
            1000,
            "RUB",
        )
