"""A confirmed interest allocates one real paid position and delivery job."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from tests.postgres_financial.test_client_entitlement_runtime import (
    capture as capture_payment,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot.application.services.paid_selection_interest import (
    PaidSelectionInterestService,
)
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.paid_selection import (
    SqlAlchemyPaidSelectionRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

capture_env = _capture_env


async def capture(env):
    await capture_payment(env)
    # Moderation/activation is a prerequisite of this selection test fixture.
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderModel)
            .where(OrderModel.order_id == env["order"])
            .values(status=OrderStatus.ACTIVE)
        )


def seed_creators(env, count=3):
    creators = tuple(uuid4() for _ in range(count))
    with Session(env["pg"]) as db, db.begin():
        db.add(AdvertiserProfileModel(user_id=env["client"], contact="test"))
        for creator in creators:
            db.add(
                UserModel(
                    user_id=creator,
                    telegram_id=str(creator.int % 10**12 + 1),
                    messenger_type=MessengerType.TELEGRAM,
                    username="synthetic-creator",
                    status=UserStatus.ACTIVE,
                )
            )
        db.flush()
        for creator in creators:
            db.add(
                BloggerProfileModel(
                    user_id=creator,
                    instagram_url="https://instagram.com/" + creator.hex,
                    instagram_user_id=creator.hex,
                    confirmed=True,
                    topics={},
                    audience_gender="all",
                    audience_age_min=18,
                    audience_age_max=40,
                    audience_geo="synthetic",
                    price=1,
                )
            )
    return creators


def service(env, repository=None, *, enabled=True):
    return PaidSelectionInterestService(
        repository or SqlAlchemyPaidSelectionRepository(),
        SessionTransactionManager(env["factory"]),
        SystemClock(),
        enabled=enabled,
    )


def rows(env, name):
    table = Base.metadata.tables[name]
    with Session(env["pg"]) as db:
        return (
            db.execute(select(table).where(table.c.order_id == env["order"]))
            .mappings()
            .all()
        )


@pytest.mark.asyncio
async def test_capture_interest_creates_assignment_and_durable_job(capture_env):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    result = await service(env).respond(env["order"], creator)
    assert result.accepted and result.delivery_state == "ready"
    assert result.creator_id == creator and result.manager_id is None
    assert result.confirmed_at <= datetime.now(timezone.utc)
    assert result.assignment_id and result.paid_item_id and result.job_id
    assert await service(env).respond(env["order"], creator) == result
    with Session(env["pg"]) as db:
        assignment = db.get(ItemAssignmentModel, result.assignment_id)
        assert assignment.creator_id == creator
        assert assignment.actor_id == creator and assignment.version == 1
        assert assignment.valid_to is None
        assert (
            db.get(OrderItemModel, result.paid_item_id).selection_state
            == "paid"
        )
    assert len(rows(env, "paid_selection_interests")) == 1
    assert len(rows(env, "paid_selection_delivery_jobs")) == 1
    # No invented agreed publication brief or financial success.
    assert rows(env, "financial_collaborations") == []
    assert rows(env, "financial_obligations") == []


@pytest.mark.asyncio
async def test_two_paid_positions_then_waitlist_never_create_third_job(
    capture_env,
):
    env = capture_env
    creators = seed_creators(env)
    await capture(env)
    results = [await service(env).respond(env["order"], c) for c in creators]
    assert [r.accepted for r in results] == [True, True, False]
    assert len({r.paid_item_id for r in results if r.accepted}) == 2
    assert (
        results[2].paid_item_id
        is results[2].assignment_id
        is results[2].job_id
        is None
    )
    assert results[2].delivery_state == "waitlisted"
    assert len(rows(env, "paid_selection_interests")) == 3
    assert len(rows(env, "paid_selection_delivery_jobs")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["unpaid", "unverified", "blocked", "paused_core"]
)
async def test_invalid_interest_never_assigns_or_queues(capture_env, reason):
    env = capture_env
    creator, *_ = seed_creators(env)
    if reason != "unpaid":
        await capture(env)
    with Session(env["pg"]) as db, db.begin():
        if reason == "unverified":
            db.execute(
                update(BloggerProfileModel)
                .where(BloggerProfileModel.user_id == creator)
                .values(confirmed=False)
            )
        if reason == "blocked":
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == creator)
                .values(status=UserStatus.BLOCKED)
            )
    with pytest.raises(ValueError):
        await service(env, enabled=reason != "paused_core").respond(
            env["order"], creator
        )
    assert rows(env, "paid_selection_interests") == []
    assert rows(env, "paid_selection_delivery_jobs") == []


@pytest.mark.asyncio
async def test_real_concurrent_duplicate_has_one_assignment_and_job(
    capture_env,
):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    # A second real connection is needed; the shared capture helper has one.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(env["pg"].url, pool_size=2, max_overflow=0)
    original = env["factory"]
    env["factory"] = async_sessionmaker(engine, expire_on_commit=False)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                *(service(env).respond(env["order"], creator) for _ in range(2))
            ),
            timeout=10,
        )
        assert results[0] == results[1]
        assert len(rows(env, "paid_selection_interests")) == 1
        assert len(rows(env, "paid_selection_delivery_jobs")) == 1
    finally:
        env["factory"] = original
        await engine.dispose()


@pytest.mark.asyncio
async def test_actual_offer_response_factory_uses_v1_without_legacy_close(
    capture_env,
):
    from ugc_bot.config import AppConfig
    from ugc_bot.container import Container

    env = capture_env
    creators = seed_creators(env)
    await capture(env)
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
            "FINANCIAL_CORE_ENABLED": True,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    container = Container(config)
    try:
        responses = container.build_bot_services()["offer_response_service"]
        first = await responses.respond_and_finalize(env["order"], creators[0])
        again = await responses.respond_and_finalize(env["order"], creators[0])
        second = await responses.respond_and_finalize(env["order"], creators[1])
        waitlist = await responses.respond_and_finalize(
            env["order"], creators[2]
        )
        assert first.delivery_queued and first.selection_assignment_id
        assert again.selection_assignment_id == first.selection_assignment_id
        assert second.delivery_queued and second.response_count == 2
        assert not waitlist.accepted and not waitlist.delivery_queued
        assert all(not r.order_closed for r in (first, second, waitlist))
        assert len(rows(env, "paid_selection_delivery_jobs")) == 2
        assert rows(env, "financial_obligations") == []
    finally:
        await container.dispose()


@pytest.mark.asyncio
async def test_unanswered_dispatches_do_not_consume_positions(capture_env):
    env = capture_env
    creators = seed_creators(env)
    await capture(env)
    with Session(env["pg"]) as db, db.begin():
        for creator in creators:
            db.add(
                OfferDispatchModel(order_id=env["order"], blogger_id=creator)
            )
    first = await service(env).respond(env["order"], creators[0])
    assert first.accepted
    async with env["factory"].begin() as db:
        assert (
            await SqlAlchemyPaidSelectionRepository().count_accepted(
                env["order"], session=db
            )
            == 1
        )
    assert len(rows(env, "paid_selection_delivery_jobs")) == 1


@pytest.mark.asyncio
async def test_manager_only_assigned_to_purchased_accompaniment(capture_env):
    env = capture_env
    creator, second, manager = seed_creators(env)
    await capture(env)
    with Session(env["pg"]) as db, db.begin():
        db.add(
            ManagerOrderModel(
                order_id=env["order"],
                user_id=manager,
                created_at=env["now"],
            )
        )
    first = await service(env).respond(env["order"], creator)
    last = await service(env).respond(env["order"], second)
    assert first.manager_id == manager
    assert last.manager_id is None
    assert rows(env, "financial_obligations") == []


@pytest.mark.asyncio
async def test_first_interest_rolls_back_all_side_effects(
    capture_env, monkeypatch
):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    repo = SqlAlchemyPaidSelectionRepository()
    original = repo._record_dispatch

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic_commit_failure")

    monkeypatch.setattr(repo, "_record_dispatch", fail)
    with pytest.raises(RuntimeError, match="synthetic_commit_failure"):
        await service(env, repo).respond(env["order"], creator)
    assert rows(env, "paid_selection_interests") == []
    assert rows(env, "paid_selection_delivery_jobs") == []
    with Session(env["pg"]) as db:
        assert not db.scalars(
            select(ItemAssignmentModel)
            .join(OrderItemModel)
            .where(OrderItemModel.order_id == env["order"])
        ).all()
    assert (await service(env).respond(env["order"], creator)).accepted


@pytest.mark.asyncio
async def test_same_verified_instagram_cannot_reenter_as_second_author(
    capture_env,
):
    env = capture_env
    first, second, *_ = seed_creators(env)
    await capture(env)
    result = await service(env).respond(env["order"], first)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == first)
            .values(confirmed=False)
        )
        db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == second)
            .values(instagram_user_id=result.instagram_user_id)
        )
    with pytest.raises(
        ValueError, match="selection_identity_already_interested"
    ):
        await service(env).respond(env["order"], second)
    assert len(rows(env, "paid_selection_interests")) == 1


@pytest.mark.asyncio
async def test_new_manager_discovery_restarts_before_item_mutation(
    capture_env, monkeypatch
):
    env = capture_env
    creator, _, manager = seed_creators(env)
    await capture(env)
    repo = SqlAlchemyPaidSelectionRepository()
    discover = repo.discover
    calls = 0

    async def changed(order_id, *, session):
        nonlocal calls
        users = await discover(order_id, session=session)
        calls += 1
        if calls == 1:
            with Session(env["pg"]) as db, db.begin():
                db.add(
                    ManagerOrderModel(
                        order_id=order_id,
                        user_id=manager,
                        created_at=env["now"],
                    )
                )
        return users

    monkeypatch.setattr(repo, "discover", changed)
    result = await service(env, repo).respond(env["order"], creator)
    assert calls == 2 and result.manager_id == manager
    assert len(rows(env, "paid_selection_delivery_jobs")) == 1


@pytest.mark.asyncio
async def test_legacy_order_routes_without_financial_mutation(capture_env):
    env = capture_env
    seed_creators(env)
    legacy = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            OrderModel(
                order_id=legacy,
                advertiser_id=env["client"],
                product_link="legacy",
                offer_text="legacy",
                price=1,
                bloggers_needed=2,
                status=OrderStatus.ACTIVE,
            )
        )
    assert await service(env, enabled=False).respond(legacy, uuid4()) is None
    with pytest.raises(ValueError, match="order_not_found"):
        await service(env).respond(uuid4(), uuid4())
    assert rows(env, "paid_selection_interests") == []


@pytest.mark.asyncio
async def test_deadline_uses_time_after_waiting_for_locked_scope(
    capture_env,
    monkeypatch,
):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)

    class Clock:
        at = env["now"] + timedelta(days=3, seconds=-1)

        def now(self):
            return self.at

    clock, repo = Clock(), SqlAlchemyPaidSelectionRepository()
    original = repo.confirm

    async def delayed(*args, **kwargs):
        # The scope may have waited while another transaction held the order.
        clock.at += timedelta(seconds=2)
        return await original(*args, **kwargs)

    monkeypatch.setattr(repo, "confirm", delayed)
    subject = service(env, repo)
    subject.clock = clock
    with pytest.raises(ValueError, match="selection_due_elapsed"):
        await subject.respond(env["order"], creator)
    assert rows(env, "paid_selection_interests") == []


@pytest.mark.asyncio
async def test_client_role_cannot_disappear_before_interest_commit(
    capture_env,
    monkeypatch,
):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    repo = SqlAlchemyPaidSelectionRepository()
    original = repo._record_dispatch
    recorded, release = asyncio.Event(), asyncio.Event()

    async def before_commit(*args, **kwargs):
        await original(*args, **kwargs)
        recorded.set()
        await release.wait()

    monkeypatch.setattr(repo, "_record_dispatch", before_commit)
    interest_task = asyncio.create_task(
        service(env, repo).respond(env["order"], creator)
    )
    await asyncio.wait_for(recorded.wait(), timeout=3)
    loop = asyncio.get_running_loop()
    pid_ready = loop.create_future()

    def delete_role():
        with Session(env["pg"]) as db, db.begin():
            pid = db.scalar(text("SELECT pg_backend_pid()"))
            loop.call_soon_threadsafe(pid_ready.set_result, pid)
            db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == env["client"]
                )
            )

    deletion = asyncio.create_task(asyncio.to_thread(delete_role))
    blocked = False
    try:
        pid = await asyncio.wait_for(pid_ready, timeout=3)
        until = loop.time() + 3
        while loop.time() < until and not deletion.done():
            with Session(env["pg"]) as db:
                blocked = bool(
                    db.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    )
                )
            if blocked:
                break
            await asyncio.sleep(0.01)
    finally:
        release.set()
        result = await asyncio.wait_for(interest_task, timeout=5)
        await asyncio.wait_for(deletion, timeout=5)
    assert result.accepted and blocked
    assert len(rows(env, "paid_selection_interests")) == 1
