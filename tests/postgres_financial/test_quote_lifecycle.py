"""Task 15 service path against migrated PostgreSQL, not metadata/SQLite."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.factories import create_test_advertiser
from tests.postgres_financial import test_financial_items_schema as schema_tests
from ugc_bot.application.services import paid_item_service as quotes
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
    FinancialPolicyService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.config import FinancialConfig
from ugc_bot.domain.enums import OrderType
from ugc_bot.infrastructure.db.models import OrderItemModel, OrderModel
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
)
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyOrderRepository,
)
from ugc_bot.infrastructure.db.repositories.platform import (
    SqlAlchemyCountryRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.fixture
def seed(financial_pg_engine, request):
    return schema_tests.seed.__wrapped__(financial_pg_engine, request)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "quote", "commit"])
async def test_explicit_new_order_atomic_quote_retry(
    financial_pg_engine, seed, user_repo, advertiser_repo, failure
):
    assert hasattr(OrderService, "create_financial_order"), (
        "explicit v1 command missing"
    )
    client = await create_test_advertiser(
        user_repo, advertiser_repo, country="ru"
    )
    # Existing user/profile ports; genuine PostgreSQL order and quote path.
    with Session(financial_pg_engine) as db, db.begin():
        from ugc_bot.domain.enums import MessengerType, UserStatus
        from ugc_bot.infrastructure.db.models import UserModel

        db.add(
            UserModel(
                user_id=client,
                messenger_type=MessengerType.TELEGRAM,
                username="quote",
                status=UserStatus.ACTIVE,
                country="ru",
            )
        )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    policy = FinancialPolicy(
        seed["version"],
        seed["user"],
        seed["now"],
        seed["now"],
        timedelta(hours=1),
        frozenset({client}),
        "terms:v1",
    )
    from uuid import uuid4

    order_id = uuid4()

    class FailingRepository(SqlAlchemyFinancialItemRepository):
        async def save_quote(self, quote, *, session):
            result = await super().save_quote(quote, session=session)
            if failure == "quote":
                raise RuntimeError("quote failed after flush")
            return result

    class NoPrecommitEffects:
        def record_order_created(self, **kwargs):
            raise AssertionError("external effect before committed order")

    repository = FailingRepository()
    service = OrderService(
        user_repo,
        advertiser_repo,
        SqlAlchemyOrderRepository(factory),
        frozenset({3}),
        100000,
        transaction_manager=SessionTransactionManager(factory),
        country_repo=SqlAlchemyCountryRepository(factory),
    )
    service.metrics_collector = NoPrecommitEffects()
    if failure == "commit":
        from contextlib import asynccontextmanager

        class CommitFailure:
            @asynccontextmanager
            async def transaction(self):
                async with factory.begin() as session:
                    yield session
                    raise RuntimeError("commit failed")

        service.transaction_manager = CommitFailure()
    service.paid_item_service = quotes.PaidItemService(
        repository,
        FinancialPolicyService(
            FinancialConfig(
                FINANCIAL_CORE_ENABLED=True, FINANCIAL_NEW_ORDERS_ENABLED=True
            )
        ),
    )
    params = dict(
        order_id=order_id,
        advertiser_id=client,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="offer",
        barter_description=None,
        price=1000,
        policy=policy,
        order_created_at=seed["now"],
        now=seed["now"],
        selection_due_at=seed["now"] + timedelta(days=2),
        currency="RUB",
        accompaniment_ordinals=frozenset({1, 3}),
        client_contact_reference="protected:client",
        idempotency_key="create-1",
    )
    try:
        if failure:
            with pytest.raises(RuntimeError, match="failed"):
                await service.create_financial_order(**params)
            with Session(financial_pg_engine) as db:
                assert db.get(OrderModel, order_id) is None
                assert not db.scalars(
                    select(OrderItemModel).where(
                        OrderItemModel.order_id == order_id
                    )
                ).all()
            return
        import asyncio

        first, retry = await asyncio.gather(
            service.create_financial_order(**params),
            service.create_financial_order(**params),
        )
        assert retry == first
        assert len(first[1].items) == 30
        assert first[1].selection_base_minor == 1500000
        assert first[1].total_minor == 1740000
        with Session(financial_pg_engine) as db:
            assert (
                db.get(OrderModel, order_id).financial_version == policy.version
            )
            assert (
                len(
                    db.scalars(
                        select(OrderItemModel).where(
                            OrderItemModel.order_id == order_id
                        )
                    ).all()
                )
                == 30
            )
        with pytest.raises(ValueError, match="idempotency_payload_conflict"):
            await service.create_financial_order(
                **dict(params, offer_text="changed")
            )
        from dataclasses import replace

        attacker_policy = replace(
            policy, allowed_clients=frozenset({seed["user"]})
        )
        async with factory.begin() as session:
            with pytest.raises(ValueError, match="quote_client_mismatch"):
                await service.paid_item_service.quote_new_order(
                    policy=attacker_policy,
                    client_id=seed["user"],
                    order_created_at=seed["now"],
                    now=seed["now"],
                    selection_due_at=params["selection_due_at"],
                    currency="RUB",
                    order_id=order_id,
                    accompaniment_ordinals=frozenset(),
                    client_contact_reference="attacker",
                    idempotency_key="attack",
                    session=session,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("freeze", ["capture", "invoice"])
async def test_draft_selection_revision_preserves_item_ids(
    financial_pg_engine, seed, freeze
):
    from uuid import uuid4

    from ugc_bot.domain.enums import OrderStatus

    seed = dict(seed, order=uuid4())
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            OrderModel(
                order_id=seed["order"],
                advertiser_id=seed["user"],
                product_link="draft",
                offer_text="draft",
                price=1,
                bloggers_needed=30,
                status=OrderStatus.NEW,
                financial_version=seed["version"],
            )
        )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    service = quotes.PaidItemService(
        SqlAlchemyFinancialItemRepository(),
        FinancialPolicyService(
            FinancialConfig(
                FINANCIAL_CORE_ENABLED=True, FINANCIAL_NEW_ORDERS_ENABLED=True
            )
        ),
    )
    policy = FinancialPolicy(
        seed["version"],
        seed["user"],
        seed["now"],
        seed["now"],
        timedelta(hours=1),
        frozenset({seed["user"]}),
        "terms:v1",
    )
    params = dict(
        policy=policy,
        client_id=seed["user"],
        order_created_at=seed["now"],
        selection_due_at=seed["now"] + timedelta(days=2),
        currency="RUB",
        now=seed["now"],
        order_id=seed["order"],
        accompaniment_ordinals=frozenset({1}),
        client_contact_reference="protected:client",
        idempotency_key="draft-1",
    )
    try:
        async with factory.begin() as session:
            first = await service.quote_new_order(**params, session=session)
        revised_params = dict(
            params,
            accompaniment_ordinals=frozenset({2, 4}),
            idempotency_key="draft-2",
        )
        async with factory.begin() as session:
            revised = await service.quote_new_order(
                **revised_params, session=session
            )
        assert [i.paid_item_id for i in first.items] == [
            i.paid_item_id for i in revised.items
        ]
        assert revised.total_minor == 1740000
        assert revised.items[0].accompaniment_minor == 0
        async with factory.begin() as session:
            assert (
                await service.quote_new_order(**revised_params, session=session)
                == revised
            )
        # Old command retries return the original without reverting state.
        async with factory.begin() as session:
            assert (
                await service.quote_new_order(**params, session=session)
                == first
            )
        with Session(financial_pg_engine) as db:
            assert (
                db.scalar(
                    select(OrderItemModel.quote_key).where(
                        OrderItemModel.order_id == seed["order"],
                        OrderItemModel.ordinal == 1,
                    )
                )
                == "draft-2"
            )
        async with factory.begin() as session:
            assert (
                await service.quote_new_order(**revised_params, session=session)
                == revised
            )
        with Session(financial_pg_engine) as db:
            row = db.scalar(
                select(OrderItemModel).where(
                    OrderItemModel.order_id == seed["order"],
                    OrderItemModel.ordinal == 1,
                )
            )
            assert row.quote_key == "draft-2"
            assert row.accompaniment_minor == 0
        with Session(financial_pg_engine) as db, db.begin():
            from decimal import Decimal

            from ugc_bot.infrastructure.db.models import ContactPricingModel

            db.merge(
                ContactPricingModel(
                    country_code="ru",
                    bloggers_count=30,
                    price=Decimal("999999"),
                    currency="RUB",
                )
            )
            if freeze == "capture":
                for row in db.scalars(
                    select(OrderItemModel).where(
                        OrderItemModel.order_id == seed["order"]
                    )
                ):
                    row.captured_at = seed["now"]
            else:
                from ugc_bot.domain.enums import PaymentStatus
                from ugc_bot.infrastructure.db.models import PaymentModel

                payment_id = uuid4()
                db.add(
                    PaymentModel(
                        payment_id=payment_id,
                        order_id=seed["order"],
                        provider="bank",
                        status=PaymentStatus.PENDING,
                        amount=17400,
                        currency="RUB",
                        external_id=str(payment_id),
                        financial_version=seed["version"],
                    )
                )
        with Session(financial_pg_engine) as db:
            stored = db.scalars(
                select(OrderItemModel)
                .where(OrderItemModel.order_id == seed["order"])
                .order_by(OrderItemModel.ordinal)
            ).all()
            assert len(stored) == 30
            assert all(row.selection_minor == 50000 for row in stored)
            assert [
                row.ordinal
                for row in stored
                if row.accompaniment_minor == 120000
            ] == [2, 4]
            assert (
                sum(
                    row.selection_minor + row.accompaniment_minor
                    for row in stored
                )
                == revised.total_minor
            )
            if freeze == "capture":
                assert all(row.captured_at is not None for row in stored)
        async with factory.begin() as session:
            with pytest.raises(
                ValueError,
                match="captured_quote_immutable|issued_payment_quote_immutable",
            ):
                await service.quote_new_order(
                    **dict(
                        revised_params,
                        idempotency_key="draft-3",
                        accompaniment_ordinals=frozenset(),
                    ),
                    session=session,
                )
        async with factory.begin() as session:
            assert (
                await service.quote_new_order(**revised_params, session=session)
                == revised
            )
    finally:
        await engine.dispose()
