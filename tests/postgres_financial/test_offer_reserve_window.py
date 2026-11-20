"""Real row locks, durable deadlines and bounded reserve intake."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial.test_paid_selection_interest import (
    capture,
    rows,
    seed_creators,
    service,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.offer_intake import RESERVE_WINDOW
from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyOfferDispatchRepository,
)
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyOrderRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

capture_env = _capture_env


@pytest.mark.asyncio
async def test_legacy_last_place_serializes_and_unrelated_save_keeps_deadline(
    capture_env,
):
    from dataclasses import replace
    from uuid import uuid4

    env = capture_env
    creators = seed_creators(env)
    order_id = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=env["client"],
                product_link="test",
                offer_text="Legacy",
                price=500,
                bloggers_needed=1,
                status=OrderStatus.ACTIVE,
            )
        )
        db.flush()
        db.add_all(
            OfferDispatchModel(
                order_id=order_id, blogger_id=creator, in_offer=False
            )
            for creator in creators
        )
    engine = create_async_engine(env["pg"].url, pool_size=3, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    orders = SqlAlchemyOrderRepository(factory)
    responses = OfferResponseService(
        orders,
        SqlAlchemyOfferDispatchRepository(factory),
        transaction_manager=SessionTransactionManager(factory),
    )
    try:
        results = await asyncio.gather(
            *(
                responses.respond_and_finalize(order_id, creator)
                for creator in creators
            )
        )
        assert sum(result.accepted for result in results) == 1
        order = await orders.get_by_id(order_id)
        deadline = order.offer_reserve_until
        assert deadline == order.completed_at + RESERVE_WINDOW
        assert all(
            result.order.offer_reserve_until == deadline for result in results
        )
        await orders.save(
            replace(order, offer_text="Edited", offer_reserve_until=None)
        )
        restored = await SqlAlchemyOrderRepository(factory).get_by_id(order_id)
        assert restored.offer_reserve_until == deadline
        assert restored.status == order.status
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_paid_last_positions_race_has_one_deadline_and_two_delivery_jobs(
    capture_env,
):
    env = capture_env
    creators = seed_creators(env, count=4)
    await capture(env)
    engine = create_async_engine(env["pg"].url, pool_size=3, max_overflow=0)
    env["factory"] = async_sessionmaker(engine, expire_on_commit=False)
    try:
        results = await asyncio.gather(
            *(
                service(env).respond(env["order"], creator)
                for creator in creators[:3]
            )
        )
        assert sum(result.accepted for result in results) == 2
        with Session(env["pg"]) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ItemAssignmentModel)
                    .join(
                        OrderItemModel,
                        OrderItemModel.paid_item_id
                        == ItemAssignmentModel.paid_item_id,
                    )
                    .where(OrderItemModel.order_id == env["order"])
                )
                == 2
            )
        assert len(rows(env, "paid_selection_delivery_jobs")) == 2
        order = await SqlAlchemyOrderRepository(env["factory"]).get_by_id(
            env["order"]
        )
        deadline = order.offer_reserve_until
        assert deadline is not None
        assert order.status == OrderStatus.ACTIVE
        assert rows(env, "financial_obligations") == []
        # A new service instance reads the same deadline. Reserve does not
        # allocate a new paid position or enqueue another contact delivery.
        reserve = await service(env).respond(env["order"], creators[3])
        assert not reserve.accepted
        again = await SqlAlchemyOrderRepository(env["factory"]).get_by_id(
            env["order"]
        )
        assert again.offer_reserve_until == deadline
        assert len(rows(env, "paid_selection_delivery_jobs")) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_paid_reserve_72_hours_preserves_financial_due(
    capture_env,
):
    env = capture_env
    creators = seed_creators(env, count=5)
    await capture(env)
    for creator in creators[:2]:
        await service(env).respond(env["order"], creator)
    order = await SqlAlchemyOrderRepository(env["factory"]).get_by_id(
        env["order"]
    )
    deadline = order.offer_reserve_until
    assert deadline is not None
    instance = service(env)
    instance.clock = SimpleNamespace(
        now=lambda: deadline - timedelta(microseconds=1)
    )
    assert not (await instance.respond(env["order"], creators[2])).accepted
    instance.clock = SimpleNamespace(now=lambda: deadline)
    with pytest.raises(ValueError, match="offer_intake_closed"):
        await instance.respond(env["order"], creators[3])
    instance.clock = SimpleNamespace(now=lambda: deadline - timedelta(hours=1))
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == env["order"])
            .values(dispatch_stopped=True)
        )
    with pytest.raises(ValueError, match="offer_intake_closed"):
        await instance.respond(env["order"], creators[4])
    assert len(rows(env, "paid_selection_interests")) == 3
    assert len(rows(env, "paid_selection_delivery_jobs")) == 2


@pytest.mark.asyncio
async def test_no_window_keeps_original_financial_deadline(capture_env):
    env = capture_env
    creators = seed_creators(env)
    await capture(env)
    for creator in creators[:2]:
        await service(env).respond(env["order"], creator)
    # Simulate pre-window assignment history. Only an explicitly bounded
    # reserve can outlive the paid selection deadline.
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == env["order"])
            .values(offer_reserve_until=None)
        )
        due = db.scalar(
            select(func.max(OrderItemModel.selection_due_at)).where(
                OrderItemModel.order_id == env["order"]
            )
        )
    instance = service(env)
    instance.clock = SimpleNamespace(now=lambda: due + timedelta(seconds=1))
    with pytest.raises(ValueError, match="selection_due_elapsed"):
        await instance.respond(env["order"], creators[2])
    assert len(rows(env, "paid_selection_interests")) == 2
    assert len(rows(env, "paid_selection_delivery_jobs")) == 2
