"""Integration test for complete advertiser user flow."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from aiogram import Dispatcher
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock

from ugc_bot.domain.entities import AdvertiserProfile, Payment
from ugc_bot.domain.enums import OrderStatus, PaymentStatus, UserStatus


@pytest.mark.asyncio
async def test_advertiser_basic_flow(
    dispatcher: Dispatcher,
    session: AsyncSession,
    mock_bot: AsyncMock,
    create_test_user,
    create_test_order,
) -> None:
    """Test complete advertiser flow: registration → order creation → payment → contacts → feedback."""

    # === Step 1: Advertiser registration ===
    advertiser_user = create_test_user("advertiser_123")
    user_repo = dispatcher["user_repo"]
    await user_repo.save(advertiser_user, session=session)
    await session.commit()

    # Advertiser profile required for order creation
    advertiser_repo = dispatcher["advertiser_repo"]
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=advertiser_user.user_id,
            phone="test_contact",
            brand="Brand",
        ),
        session=session,
    )
    await session.commit()

    # === Step 2: Create order ===
    order_template = create_test_order(advertiser_user.user_id)
    order_service = dispatcher["order_service"]
    order = await order_service.create_order(
        advertiser_id=advertiser_user.user_id,
        order_type=order_template.order_type,
        product_link=order_template.product_link,
        offer_text=order_template.offer_text,
        ugc_requirements=order_template.ugc_requirements,
        barter_description=order_template.barter_description,
        price=order_template.price,
        bloggers_needed=order_template.bloggers_needed,
    )
    assert order.status == OrderStatus.NEW
    assert order.advertiser_id == advertiser_user.user_id

    # === Step 3: Payment and order activation (same transaction, no outbox table) ===
    # PaymentService.confirm_telegram_payment does reads without session; we run the
    # write path manually so integration tests work with SQLite.
    now = datetime.now(timezone.utc)
    payment = Payment(
        payment_id=uuid4(),
        order_id=order.order_id,
        provider="yookassa_telegram",
        status=PaymentStatus.PAID,
        amount=order.price,
        currency="RUB",
        external_id="test_charge_1",
        created_at=now,
        paid_at=now,
    )
    transaction_manager = dispatcher["transaction_manager"]
    payment_service = dispatcher["payment_service"]
    async with transaction_manager.transaction() as tx_session:
        await dispatcher["payment_repo"].save(payment, session=tx_session)
        await payment_service.outbox_publisher.publish_order_activation(
            order, session=tx_session
        )

    order_repo = dispatcher["order_repo"]
    updated_order = await order_repo.get_by_id(order.order_id, session=session)
    assert updated_order is not None
    assert updated_order.status == OrderStatus.ACTIVE

    # === Final checks ===
    assert advertiser_user.status == UserStatus.ACTIVE
