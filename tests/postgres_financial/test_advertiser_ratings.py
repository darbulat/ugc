"""Rating authorization, completion and locking on migrated PostgreSQL."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from tests.postgres_financial.test_work_entitlement_runtime import start_flow
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    RaterRole,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    ManagerOrderModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.rating_eligibility import (
    SqlAlchemyRatingEligibilityRepository,
)
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager

capture_env = _capture_env


@pytest_asyncio.fixture
async def ratings_env(financial_pg_engine):
    engine = create_async_engine(
        financial_pg_engine.url, pool_size=4, max_overflow=0
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    owner, manager, outsider, creator, incomplete, order, foreign_order = (
        uuid4() for _ in range(7)
    )
    now = datetime.now(timezone.utc)
    with Session(financial_pg_engine) as db, db.begin():
        for user in (owner, manager, outsider, creator, incomplete):
            db.add(
                UserModel(
                    user_id=user,
                    messenger_type=MessengerType.TELEGRAM,
                    telegram_id=str(user),
                    username="rating-" + user.hex[:8],
                    status=UserStatus.ACTIVE,
                )
            )
        db.flush()
        for oid in (order, foreign_order):
            db.add(
                OrderModel(
                    order_id=oid,
                    advertiser_id=owner,
                    product_link="test",
                    offer_text="test",
                    price=1000,
                    bloggers_needed=2,
                    status=OrderStatus.CLOSED,
                    created_at=now,
                )
            )
        db.flush()
        db.add(
            ManagerOrderModel(user_id=manager, order_id=order, created_at=now)
        )
        for uid, oid, state in (
            (creator, order, InteractionStatus.OK),
            (incomplete, order, InteractionStatus.PENDING),
            (outsider, foreign_order, InteractionStatus.OK),
        ):
            db.add(
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=oid,
                    blogger_id=uid,
                    advertiser_id=owner,
                    status=state,
                    created_at=now,
                    updated_at=now,
                )
            )
    repo = SqlAlchemyBloggerRatingRepository(factory)
    service = BloggerRatingService(
        repo,
        SessionTransactionManager(factory),
        SqlAlchemyRatingEligibilityRepository(),
    )
    try:
        yield dict(
            service=service,
            repo=repo,
            factory=factory,
            owner=owner,
            manager=manager,
            outsider=outsider,
            creator=creator,
            incomplete=incomplete,
            order=order,
        )
    finally:
        await engine.dispose()


async def rate(env, *, actor=None, creator=None, score=5, **kwargs):
    return await env["service"].rate_blogger(
        creator or env["creator"],
        env["order"],
        actor or env["owner"],
        RaterRole.ADMIN,
        score,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_postgres_owner_upsert_preserves_manager_and_effective_average(
    ratings_env,
):
    env = ratings_env
    manager = await rate(env, actor=env["manager"], score=2)
    first = await rate(env, score=5)
    second = await rate(env, score=1)
    assert first.rating_id == second.rating_id
    assert (
        first.created_at == second.created_at and second.updated_at is not None
    )
    assert await env["repo"].get_avg_rating(env["creator"]) == 1
    assert await env["repo"].get_avg_ratings_for_bloggers([env["creator"]]) == {
        env["creator"]: 1
    }
    assert (
        await env["repo"].get_by_blogger_order_and_rater(
            env["creator"], env["order"], env["manager"]
        )
    ).rating_id == manager.rating_id
    listing = await env["service"].list_for_order(env["owner"], env["order"])
    assert {row["blogger_id"]: row["rating_eligible"] for row in listing} == {
        str(env["creator"]): True,
        str(env["incomplete"]): False,
    }
    assert len(await env["repo"].list_by_blogger(env["creator"])) == 2


@pytest.mark.asyncio
async def test_postgres_checks_current_principal_participant_and_completion(
    ratings_env,
):
    env = ratings_env
    for actor, creator, principal, reason in (
        (env["outsider"], env["creator"], None, "rating_access_denied"),
        (env["owner"], env["outsider"], None, "rating_participant_required"),
        (env["owner"], env["incomplete"], None, "rating_work_incomplete"),
        (
            env["owner"],
            env["creator"],
            AuthenticatedMessengerPrincipal(env["owner"], "telegram", "old"),
            "financial_principal_changed",
        ),
    ):
        with pytest.raises(ValueError, match=reason):
            await rate(env, actor=actor, creator=creator, principal=principal)
    assert await env["repo"].list_by_blogger(env["creator"]) == []
    with pytest.raises(ValueError, match="rating_access_denied"):
        await env["service"].list_for_order(env["outsider"], env["order"])
    await rate(
        env,
        principal=AuthenticatedMessengerPrincipal(
            env["owner"], "telegram", str(env["owner"])
        ),
    )


@pytest.mark.asyncio
async def test_postgres_concurrent_repeats_share_one_rating_and_order_lock(
    ratings_env,
):
    env = ratings_env
    async with env["factory"].begin() as db:
        await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == env["order"])
            .with_for_update()
        )
        pending = asyncio.create_task(rate(env, score=5))
        # A separate connection must wait for the externally-held order lock.
        await asyncio.sleep(0.1)
        assert not pending.done()
    first = await asyncio.wait_for(pending, 3)
    results = await asyncio.gather(
        *(rate(env, score=score) for score in (1, 3, 5))
    )
    assert {result.rating_id for result in results} == {first.rating_id}
    history = await env["repo"].list_by_blogger(env["creator"])
    assert len(history) == 1 and history[0].score in (1, 3, 5)


@pytest.mark.asyncio
async def test_actual_financial_completion_unlocks_advertiser_rating(
    capture_env, monkeypatch
):
    env = capture_env
    flow = await start_flow(env, monkeypatch)
    service = BloggerRatingService(
        SqlAlchemyBloggerRatingRepository(env["factory"]),
        SessionTransactionManager(env["factory"]),
        SqlAlchemyRatingEligibilityRepository(),
    )

    async def submit():
        return await service.rate_blogger(
            flow["creator"],
            env["order"],
            env["client"],
            RaterRole.ADVERTISER,
            5,
        )

    try:
        with pytest.raises(ValueError, match="rating_work_incomplete"):
            await submit()
        await flow["command"]("start", env["client"], 1)
        await flow["command"](
            "claim",
            flow["creator"],
            2,
            evidence="published actual creator work",
        )
        with pytest.raises(ValueError, match="rating_work_incomplete"):
            await submit()
        await flow["command"]("agree", env["client"], 3)
        assert (await submit()).score == 5
        assert (await service.list_for_order(env["client"], env["order"]))[0][
            "rating_eligible"
        ] is True
    finally:
        await flow["container"].session_factory.kw["bind"].dispose()
