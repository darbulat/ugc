"""One captured receipt across independent PostgreSQL transactions."""

import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tests.helpers.financial_environment import isolated_financial_database
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    ContactPricingModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest_asyncio.fixture
async def capture_pg():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Local unit-only run without explicit financial PostgreSQL")
    assert url is not None
    with isolated_financial_database(url) as migrated:
        engine = create_async_engine(migrated.url, pool_size=2, max_overflow=0)
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_capture_or_binding_races_on_captured_payment(capture_pg):
    factory = capture_pg
    ready = asyncio.Barrier(2)
    backend_ids = set()
    armed = False

    class ConcurrentOrders(SqlAlchemyOrderRepository):
        async def get_by_id(self, order_id, session=None):
            result = await super().get_by_id(order_id, session=session)
            if armed:
                assert isinstance(session, AsyncSession)
                backend_ids.add(
                    await session.scalar(text("SELECT pg_backend_pid()"))
                )
                await ready.wait()
            return result

        async def get_by_id_for_update(self, order_id, session=None):
            assert isinstance(session, AsyncSession)
            backend_ids.add(
                await session.scalar(text("SELECT pg_backend_pid()"))
            )
            await ready.wait()
            return await super().get_by_id_for_update(order_id, session=session)

    users = SqlAlchemyUserRepository(factory)
    advertisers = SqlAlchemyAdvertiserProfileRepository(factory)
    orders = ConcurrentOrders(factory)
    payments = SqlAlchemyPaymentRepository(factory)
    prices = SqlAlchemyContactPricingRepository(factory)
    actor, order_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    async with factory.begin() as session:
        session.add(
            UserModel(
                user_id=actor,
                messenger_type=MessengerType.TELEGRAM,
                username="capture-synthetic",
                country="ru",
                status=UserStatus.ACTIVE,
                issue_count=0,
                created_at=now,
            )
        )
        await session.flush()
        session.add(
            AdvertiserProfileModel(
                user_id=actor,
                contact="synthetic@example.test",
                brand="Synthetic",
            )
        )
        session.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=actor,
                order_type=OrderType.UGC_ONLY,
                product_link="https://example.test",
                offer_text="synthetic",
                price=1000,
                bloggers_needed=3,
                status=OrderStatus.NEW,
                currency="RUB",
                created_at=now,
            )
        )
        await session.merge(
            ContactPricingModel(
                country_code="ru",
                bloggers_count=3,
                price=Decimal("1000"),
                currency="RUB",
            )
        )
    order = await orders.get_by_id(order_id)
    assert order is not None
    service = PaymentService(
        user_repo=users,
        advertiser_repo=advertisers,
        order_repo=orders,
        payment_repo=payments,
        pricing_repo=prices,
        transaction_manager=SessionTransactionManager(factory),
    )
    armed = True
    first, second = await asyncio.gather(
        service.confirm_telegram_payment(
            actor, order.order_id, "same-captured-receipt", 100000, "RUB"
        ),
        service.confirm_telegram_payment(
            actor, order.order_id, "same-captured-receipt", 100000, "RUB"
        ),
    )
    armed = False
    assert len(backend_ids) == 2
    assert first.payment_id == second.payment_id
    assert first.amount == second.amount
    assert first.status == second.status == PaymentStatus.PAID
    async with factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(PaymentModel)
            .where(PaymentModel.order_id == order.order_id)
        )
    assert count == 1
    assert (
        await orders.get_by_id(order.order_id)
    ).status == OrderStatus.PENDING_MODERATION
