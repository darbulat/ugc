"""Concurrent real consumers preserve a single captured economic ground."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial.test_client_entitlement_runtime import (
    capture,
    processor,
    rows,
    seed_attribution,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot.container.repository_factory import build_repos
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import UserReferralBindingModel
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyFinancialDeliveryRepository,
)

capture_env = _capture_env


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_two_consumers_commit_one_immutable_assessment(request):
    env = request.getfixturevalue("capture_env")
    partner, _ = seed_attribution(env)
    event_id = await capture(env)
    engine = create_async_engine(env["pg"].url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    source = await SqlAlchemyFinancialDeliveryRepository(factory).get_by_id(
        event_id
    )
    config = processor(env).outbox_publisher.financial_delivery
    # Use its production handler, with only the nonlocking discovery rendezvous
    # controlled. Both transactions read the same unprocessed source first.
    handler = config.financial_router.handlers[source.event_type]
    original = handler.repository.load_capture
    arrived, proceed = 0, asyncio.Event()

    async def discovered(event, *, session):
        nonlocal arrived
        result = await original(event, session=session)
        if not session.info.get("discovered"):
            session.info["discovered"] = True
            arrived += 1
            if arrived == 2:
                proceed.set()
            await proceed.wait()
        return result

    handler.repository.load_capture = discovered

    async def consume():
        async with factory.begin() as session:
            await handler.handle(source, session=session)

    try:
        await asyncio.wait_for(asyncio.gather(consume(), consume()), 10)
        assert len(rows(env, "financial_obligations")) == 2
        assert len(rows(env, "financial_movements")) == 2
        table = Base.metadata.tables["financial_client_assessments"]
        wallet = Base.metadata.tables["financial_wallets"]
        with Session(env["pg"]) as db:
            receipts = (
                db.execute(select(table).where(table.c.event_id == event_id))
                .mappings()
                .all()
            )
            assert len(receipts) == 1
            assert receipts[0]["assessment"]["attribution"][
                "referrer_user_id"
            ] == str(partner)
            assert (
                db.scalar(
                    select(wallet.c.pending_minor).where(
                        wallet.c.recipient_id == partner
                    )
                )
                == 10000
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_missing_recipient_discovery_retries_without_taking_new_wallet(
    request,
):
    env = request.getfixturevalue("capture_env")
    partner, stranger = seed_attribution(env)
    event_id = await capture(env)
    parent = processor(env).outbox_publisher
    child = parent.financial_delivery
    handler = child.financial_router.handlers[
        "financial.client_snapshot_requested"
    ]
    from dataclasses import replace

    resolve = handler.history.resolve_direct_binding
    calls = 0

    async def changed(user, at, *, session):
        nonlocal calls
        calls += 1
        result = await resolve(user, at, session=session)
        return (
            replace(result, referrer_user_id=stranger) if calls == 2 else result
        )

    handler.history = SimpleNamespace(
        resolve_direct_binding=changed,
        acquire_snapshot_barrier=handler.history.acquire_snapshot_barrier,
    )
    source = await child.outbox_repo.get_by_id(event_id)
    with pytest.raises(
        ValueError, match="financial_scope_changed_retry_required"
    ):
        await child._process_one_event(source, None, 3)
    assert rows(env, "financial_obligations") == []
    assert rows(env, "financial_movements") == []
    wallet = Base.metadata.tables["financial_wallets"]
    with Session(env["pg"]) as db:
        assert (
            db.execute(
                select(wallet).where(
                    wallet.c.recipient_id.in_((partner, stranger))
                )
            ).first()
            is None
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("capture_env")
async def test_late_binding_writer_waits_safely_and_keeps_payment_partner(
    request,
):
    env = request.getfixturevalue("capture_env")
    partner, stranger = seed_attribution(env)
    event_id = await capture(env)
    engine = create_async_engine(env["pg"].url, pool_size=2, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    dependencies = build_repos(factory)
    config = processor(env).outbox_publisher.financial_delivery
    handler = config.financial_router.handlers[
        "financial.client_snapshot_requested"
    ]
    writer = factory()
    await writer.begin()
    await writer.execute(
        update(UserReferralBindingModel)
        .where(UserReferralBindingModel.referred_user_id == env["client"])
        .values(referrer_user_id=stranger)
    )
    barrier_entered = asyncio.Event()
    original = handler.history.acquire_snapshot_barrier

    async def barrier(*, session):
        barrier_entered.set()
        await original(session=session)

    handler.history = SimpleNamespace(
        resolve_direct_binding=handler.history.resolve_direct_binding,
        acquire_snapshot_barrier=barrier,
    )
    source = await dependencies["financial_delivery_repo"].get_by_id(event_id)

    async def consume():
        async with factory.begin() as session:
            await handler.handle(source, session=session)

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(barrier_entered.wait(), 5)
        assert not task.done()
        await writer.commit()
        await asyncio.wait_for(task, 5)
        assert {
            r["recipient_id"] for r in rows(env, "financial_obligations")
        } == {partner}
    finally:
        if writer.in_transaction():
            await writer.rollback()
        await writer.close()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
