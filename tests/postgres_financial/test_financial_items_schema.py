"""Genuine upgrades in private schemas, never metadata.create_all."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    OrderItemModel,
    OrderModel,
    PaymentItemAllocationModel,
    PaymentModel,
    UserModel,
)


def test_financial_items_schema(financial_pg_engine):
    tables = inspect(financial_pg_engine).get_table_names()
    assert {
        "financial_policy_versions",
        "order_items",
        "item_assignments",
        "payment_item_allocations",
    } <= set(tables)


@pytest.fixture
def seed(financial_pg_engine, request):
    now = datetime.now(timezone.utc)
    user, order, payment, item = [uuid4() for _ in range(4)]
    version = str(uuid4())
    with Session(financial_pg_engine) as session, session.begin():
        session.add(
            UserModel(
                user_id=user,
                messenger_type=MessengerType.TELEGRAM,
                username="synthetic",
                status=UserStatus.ACTIVE,
            )
        )
        session.flush()
        session.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=user,
                approved_at=now,
                effective_from=now,
                refund_window_seconds=3600,
                rules={},
            )
        )
        session.add(
            OrderModel(
                order_id=order,
                advertiser_id=user,
                product_link="synthetic",
                offer_text="synthetic",
                price=1,
                bloggers_needed=1,
                status=OrderStatus.NEW,
            )
        )
        session.flush()
        session.add(
            PaymentModel(
                payment_id=payment,
                order_id=order,
                provider="synthetic",
                status=PaymentStatus.PAID,
                amount=500,
                currency="RUB",
                external_id=str(payment),
                captured_minor=getattr(request, "param", 1),
                financial_version=version,
            )
        )
        session.add(
            OrderItemModel(
                paid_item_id=item,
                order_id=order,
                ordinal=1,
                currency="RUB",
                selection_minor=50000,
                accompaniment_minor=0,
                policy_version=version,
                selection_due_at=now + timedelta(days=1),
                quote_key="quote",
                quote_payload={},
            )
        )
    return dict(
        user=user,
        order=order,
        payment=payment,
        item=item,
        version=version,
        now=now,
    )


@pytest.mark.asyncio
async def test_quote_repository_is_idempotent_and_snapshots_30_items(
    financial_pg_engine, seed
):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ugc_bot.application.services.paid_item_service import build_quote
    from ugc_bot.infrastructure.db.repositories.financial_items import (
        SqlAlchemyFinancialItemRepository,
    )

    with Session(financial_pg_engine) as session, session.begin():
        session.delete(session.get(OrderItemModel, seed["item"]))
        session.get(OrderModel, seed["order"]).financial_version = seed[
            "version"
        ]
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyFinancialItemRepository()
    try:
        params = dict(
            order_id=seed["order"],
            count=30,
            selection_minor=50000,
            accompaniment_minor=120000,
            accompaniment_ordinals=frozenset({1, 2}),
            currency="RUB",
            policy_version=seed["version"],
            selection_due_at=seed["now"] + timedelta(days=2),
            client_contact_reference="protected:client",
            terms_reference="terms:v1",
            idempotency_key="selection-1",
        )
        async with factory.begin() as session:
            first = await repo.save_quote(
                build_quote(**params), session=session
            )
        async with factory.begin() as session:
            retry = await repo.save_quote(
                build_quote(**params), session=session
            )
        assert retry == first
        assert len(first.items) == 30
        assert first.total_minor == 1740000
        async with factory.begin() as session:
            with pytest.raises(
                ValueError, match="idempotency_payload_conflict"
            ):
                await repo.save_quote(
                    build_quote(
                        **dict(params, accompaniment_ordinals=frozenset())
                    ),
                    session=session,
                )
    finally:
        await engine.dispose()


def test_approved_policy_is_immutable(financial_pg_engine, seed):
    with (
        pytest.raises(IntegrityError, match="financial_record_immutable"),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        policy = session.get(FinancialPolicyVersionModel, seed["version"])
        policy.refund_window_seconds = 1


def test_allocations_and_capture_are_immutable(financial_pg_engine, seed):
    key = str(uuid4())
    with Session(financial_pg_engine) as session, session.begin():
        session.add(
            PaymentItemAllocationModel(
                allocation_key=key,
                payment_id=seed["payment"],
                paid_item_id=seed["item"],
                order_id=seed["order"],
                component="selection",
                amount_minor=1,
                currency="RUB",
            )
        )
    with (
        pytest.raises(IntegrityError, match="financial_record_immutable"),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        session.delete(session.get(PaymentItemAllocationModel, key))
    with (
        pytest.raises(IntegrityError, match="allocated_payment_immutable"),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        session.get(PaymentModel, seed["payment"]).captured_minor = 0


def test_captured_prices_are_immutable(financial_pg_engine, seed):
    with Session(financial_pg_engine) as session, session.begin():
        item = session.get(OrderItemModel, seed["item"])
        item.captured_at = seed["now"]
    with (
        pytest.raises(IntegrityError, match="captured_item_immutable"),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        item = session.get(OrderItemModel, seed["item"])
        item.selection_minor = 1


def test_allocation_cannot_exceed_capture(financial_pg_engine, seed):
    with (
        pytest.raises(IntegrityError, match="allocation_exceeds_capture"),
        Session(financial_pg_engine) as session,
        session.begin(),
    ):
        session.add(
            PaymentItemAllocationModel(
                allocation_key=str(uuid4()),
                payment_id=seed["payment"],
                paid_item_id=seed["item"],
                order_id=seed["order"],
                component="selection",
                amount_minor=2,
                currency="RUB",
            )
        )
