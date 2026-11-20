"""Discovery queue fairness against migrated PostgreSQL, without HTTP calls."""

from datetime import timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from tests.postgres_financial.test_instagram_discovery_pg import (
    NOW,
    async_sessions,
    seed,
)
from ugc_bot.infrastructure.db.instagram_discovery_models import DISCOVERY as D
from ugc_bot.infrastructure.db.instagram_discovery_models import (
    DISCOVERY_CONTROL as C,
)
from ugc_bot.infrastructure.db.instagram_maintenance_models import HEALTH as H
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    BloggerProfileModel,
    InstagramStatsModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.instagram_discovery import (
    DiscoveryRepository,
)

P = BloggerProfileModel.__table__
S = InstagramStatsModel.__table__
U = UserModel.__table__
A = AuditLogModel.__table__


@pytest.fixture
def queue_db(financial_pg_engine):
    with financial_pg_engine.begin() as conn:
        conn.execute(sa.delete(C))
    return financial_pg_engine


def cached(engine, owner, context, *, observed=None, media=None, **changes):
    with engine.begin() as conn:
        profile = (
            conn.execute(sa.select(P).where(P.c.user_id == owner))
            .mappings()
            .one()
        )
        values = dict(
            user_id=owner,
            attempt_meta_id=profile["instagram_user_id"],
            attempt_profile_url=profile["instagram_url"],
            attempt_id=uuid4(),
            attempted_at=NOW - timedelta(minutes=1),
            next_attempt_at=NOW,
            last_outcome="invalid_request",
        )
        if observed is not None:
            values.update(
                observed_meta_id=profile["instagram_user_id"],
                identity_context=context,
                username=profile["instagram_username"],
                discovery_object_id="123",
                discovery_context="discovery:test",
                observed_at=observed,
                followers_count=100,
                followers_observed_at=observed,
                media_count=media,
                media_observed_at=observed if media is not None else None,
                last_outcome="success",
            )
        values.update(changes)
        conn.execute(D.insert().values(**values))


def legacy(engine, owner, media, *, handle=None):
    with engine.begin() as conn:
        current_handle = conn.scalar(
            sa.select(P.c.instagram_username).where(P.c.user_id == owner)
        )
        conn.execute(
            S.insert().values(
                user_id=owner,
                raw_response={},
                fetched_at=NOW,
                media_count=media,
                instagram_username=handle or current_handle,
            )
        )


def ordered(engine, context):
    repo = DiscoveryRepository(None, context)
    with engine.connect() as conn:
        conn.execute(sa.text("SET TRANSACTION READ ONLY"))
        owners = conn.execute(repo.target_query(NOW).limit(150)).scalars().all()
        conn.rollback()
    return owners


def test_due_failure_is_not_always_behind_never_attempted_profiles(queue_db):
    context = str(uuid4())
    unseen = seed(queue_db, context, age=1)
    failed = seed(queue_db, context, age=2)
    cached(queue_db, failed, context)
    assert ordered(queue_db, context) == [failed, unseen]


def test_partial_success_uses_the_oldest_actual_counter_date(queue_db):
    context = str(uuid4())
    partial = seed(queue_db, context)
    older_body = seed(queue_db, context, age=2)
    cached(
        queue_db,
        partial,
        context,
        observed=NOW - timedelta(days=15),
        followers_observed_at=NOW - timedelta(days=45),
        media=10,
    )
    cached(
        queue_db,
        older_body,
        context,
        observed=NOW - timedelta(days=20),
        media=10,
    )
    assert ordered(queue_db, context) == [partial, older_body]


def test_effective_bot_block_is_only_a_tiebreaker_without_status_writes(
    queue_db,
):
    context = str(uuid4())
    reachable = seed(queue_db, context)
    blocked = seed(queue_db, context)
    legacy(queue_db, reachable, 0)
    with queue_db.begin() as conn:
        conn.execute(
            A.insert().values(
                id=uuid4(),
                entity_type="bot_unavailable",
                entity_id=blocked,
                action="create",
                new_values={
                    "platform": "telegram",
                    "telegram_id": str(blocked),
                },
                changed_at=NOW,
            )
        )
    assert ordered(queue_db, context) == [reachable, blocked]
    with queue_db.connect() as conn:
        assert (
            conn.scalar(sa.select(U.c.status).where(U.c.user_id == blocked))
            == "active"
        )


def test_older_blocked_snapshot_precedes_a_newer_reachable_profile(queue_db):
    context = str(uuid4())
    newer = seed(queue_db, context)
    blocked = seed(queue_db, context)
    with queue_db.begin() as conn:
        conn.execute(
            sa.update(U)
            .where(U.c.user_id == blocked)
            .values(status="bot_blocked")
        )
    cached(
        queue_db,
        blocked,
        context,
        observed=NOW - timedelta(days=20),
        media=10,
    )
    assert ordered(queue_db, context) == [blocked, newer]


def test_missing_publications_precede_known_zero_at_equal_age(queue_db):
    context = str(uuid4())
    missing = seed(queue_db, context)
    legacy_zero = seed(queue_db, context)
    discovery_zero = seed(queue_db, context)
    legacy(queue_db, legacy_zero, 0)
    cached(
        queue_db,
        discovery_zero,
        context,
        observed=NOW - timedelta(hours=1),
        media=0,
    )
    result = ordered(queue_db, context)
    assert result[0] == missing
    assert result[1:] == sorted([legacy_zero, discovery_zero])


@pytest.mark.parametrize("evidence", ["undated", "old", "wrong_handle"])
def test_old_legacy_publications_do_not_count_after_reverification(
    queue_db, evidence
):
    context = str(uuid4())
    unknown = seed(queue_db, context)
    known_zero = seed(queue_db, context)
    legacy(queue_db, known_zero, 0)
    legacy(
        queue_db,
        unknown,
        77,
        handle="previous_handle" if evidence == "wrong_handle" else None,
    )
    observed = {
        "undated": None,
        "old": NOW - timedelta(days=2),
        "wrong_handle": NOW,
    }[evidence]
    with queue_db.begin() as conn:
        conn.execute(
            sa.update(H)
            .where(H.c.user_id == unknown)
            .values(
                identity_since=NOW - timedelta(days=1),
                metrics_observed_at=observed,
            )
        )
    assert ordered(queue_db, context) == [unknown, known_zero]


def test_snapshot_of_previous_identity_does_not_steal_priority(queue_db):
    context = str(uuid4())
    changed = seed(queue_db, context, age=1)
    older = seed(queue_db, context, age=2)
    cached(
        queue_db,
        changed,
        context,
        observed=NOW - timedelta(days=30),
        observed_meta_id="previous_identity",
    )
    assert ordered(queue_db, context) == [older, changed]


def test_cooldown_and_primary_health_guards_remain_in_force(queue_db):
    context = str(uuid4())
    due = seed(queue_db, context)
    cooling = seed(queue_db, context, age=2)
    cached(
        queue_db,
        cooling,
        context,
        next_attempt_at=NOW + timedelta(days=1),
    )
    seed(queue_db, context, age=49)
    seed(queue_db, context, confirmed=False)
    assert ordered(queue_db, context) == [due]


def test_new_identity_uses_its_age_and_not_previous_binding_cooldown(queue_db):
    context = str(uuid4())
    changed = seed(queue_db, context, age=2)
    newer = seed(queue_db, context, age=1)
    cached(
        queue_db,
        changed,
        context,
        observed=NOW - timedelta(days=20),
        observed_meta_id="previous_identity",
        attempt_meta_id="previous_identity",
        next_attempt_at=NOW + timedelta(days=14),
    )
    assert ordered(queue_db, context) == [changed, newer]


def test_counter_from_before_reverification_cannot_set_current_age(queue_db):
    context = str(uuid4())
    older = seed(queue_db, context)
    changed = seed(queue_db, context)
    cached(queue_db, older, context, observed=NOW - timedelta(hours=2))
    cached(
        queue_db,
        changed,
        context,
        observed=NOW - timedelta(hours=1),
        followers_observed_at=NOW - timedelta(days=40),
    )
    with queue_db.begin() as conn:
        conn.execute(
            sa.update(H)
            .where(H.c.user_id == changed)
            .values(identity_since=NOW - timedelta(days=1))
        )
    assert ordered(queue_db, context) == [older, changed]


@pytest.mark.asyncio
async def test_prepare_uses_priority_and_keeps_budget_and_profiles(queue_db):
    context = str(uuid4())
    seed(queue_db, context, age=1)
    failed = seed(queue_db, context, age=2)
    cached(queue_db, failed, context)
    with queue_db.connect() as conn:
        before = conn.execute(sa.select(P).order_by(P.c.user_id)).all()
    engine, sessions = async_sessions(queue_db)
    repo = DiscoveryRepository(sessions, context)
    try:
        assert await repo.claim(NOW - timedelta(minutes=1)) is None
        lease = await repo.claim(NOW)
        assert lease is not None
        target = await repo.prepare(lease, NOW)
        assert target is not None
        assert target.user_id == failed
        with queue_db.begin() as conn:
            control = conn.execute(sa.select(C)).mappings().one()
            assert control["requests_used"] == 1
            assert control["next_run_at"] == NOW + timedelta(days=1)
            conn.execute(sa.update(C).values(requests_used=150))
            assert (
                conn.execute(sa.select(P).order_by(P.c.user_id)).all() == before
            )
        assert await repo.prepare(lease, NOW) is None
        await repo.release(lease, "complete")
    finally:
        await engine.dispose()
