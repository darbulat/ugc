"""Real migrated PostgreSQL: budgets, identity races and cache provenance."""

import asyncio
import importlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_creator_social import (
    profile_values,
    seed_user,
)
from tests.unit.test_instagram_discovery import credential
from ugc_bot.domain.instagram_discovery import DiscoveryProfile, DiscoveryResult
from ugc_bot.infrastructure.db.instagram_discovery_models import DISCOVERY as D
from ugc_bot.infrastructure.db.instagram_discovery_models import (
    DISCOVERY_CONTROL as C,
)
from ugc_bot.infrastructure.db.instagram_maintenance_models import (
    HEALTH as H,
)
from ugc_bot.infrastructure.db.instagram_maintenance_models import (
    NOTICES,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel as P,
)
from ugc_bot.infrastructure.db.models import (
    InstagramStatsModel as S,
)
from ugc_bot.infrastructure.db.repositories.instagram import (
    SqlAlchemyInstagramStatsRepository,
)
from ugc_bot.infrastructure.db.repositories.instagram_discovery import (
    DiscoveryRepository,
)
from ugc_bot.infrastructure.instagram.discovery_client import DiscoveryClient
from ugc_bot.instagram_discovery_scheduler import scheduled_batch

NOW = datetime(2026, 11, 20, 7, 30, tzinfo=timezone.utc)


@pytest.fixture
def discovery_db(financial_pg_engine):
    with financial_pg_engine.begin() as conn:
        conn.execute(sa.delete(C))
    return financial_pg_engine


def seed(engine, context, *, age=1, confirmed=True):
    with engine.begin() as conn:
        owner = seed_user(conn)
        handle = "c" + owner.hex[:20]
        values = profile_values(owner, stable_id=owner.hex, confirmed=confirmed)
        values.update(
            instagram_username=handle,
            instagram_followers_count=110,
            instagram_stats_fetched_at=NOW - timedelta(hours=1),
        )
        conn.execute(P.__table__.insert().values(**values))
        conn.execute(
            H.insert().values(
                user_id=owner,
                meta_id=owner.hex,
                id_kind="instagram_scoped_id",
                identity_context=context,
                handle=handle,
                status="healthy",
                failure_count=0,
                last_success_at=NOW - timedelta(hours=age),
                checked_at=NOW,
                episode=uuid4(),
            )
        )
    return owner


def async_sessions(engine):
    async_engine = create_async_engine(engine.url)
    return async_engine, async_sessionmaker(
        async_engine, expire_on_commit=False
    )


@pytest.mark.asyncio
async def test_boot_waits_concurrent_claim_and_persistent_budget(discovery_db):
    engine, sessions = async_sessions(discovery_db)
    context = str(uuid4())
    repo = DiscoveryRepository(sessions, context)
    owner = seed(discovery_db, context)
    seed(discovery_db, context, age=49)
    seed(discovery_db, context, confirmed=False)
    try:
        assert await repo.claim(NOW - timedelta(minutes=5)) is None
        leases = await asyncio.gather(repo.claim(NOW), repo.claim(NOW))
        assert sum(lease is not None for lease in leases) == 1
        lease = next(lease for lease in leases if lease)
        target = await repo.prepare(lease, NOW)
        assert target.user_id == owner
        assert await repo.prepare(lease, NOW) is None
        with discovery_db.begin() as conn:
            control = conn.execute(sa.select(C)).mappings().one()
            assert control["requests_used"] == 1
            assert control["next_run_at"] == NOW + timedelta(days=1)
            conn.execute(sa.update(C).values(requests_used=150))
            conn.execute(sa.update(D).values(next_attempt_at=NOW))
        assert await repo.prepare(lease, NOW) is None
        await repo.release(lease, "complete")
        assert await repo.claim(NOW + timedelta(hours=1)) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_partial_updates_keep_known_fields_and_do_not_change_ownership(
    discovery_db,
):
    context = str(uuid4())
    owner = seed(discovery_db, context)
    engine, sessions = async_sessions(discovery_db)
    repo = DiscoveryRepository(sessions, context)
    try:
        await repo.claim(NOW - timedelta(minutes=1))
        lease = await repo.claim(NOW)
        target = await repo.prepare(lease, NOW)
        result = DiscoveryResult(
            "success",
            DiscoveryProfile(
                "987",
                target.username,
                120,
                50,
                {"name": "Creator", "biography": "Bio"},
            ),
        )
        assert (
            await repo.finish(target, result, "discovery:test", NOW)
            == "success"
        )
        with discovery_db.begin() as conn:
            before = (
                conn.execute(sa.select(P.__table__).where(P.user_id == owner))
                .mappings()
                .one()
            )
            health = (
                conn.execute(sa.select(H).where(H.c.user_id == owner))
                .mappings()
                .one()
            )
            notices = conn.scalar(
                sa.select(sa.func.count()).select_from(NOTICES)
            )
            conn.execute(
                S.__table__.insert().values(
                    user_id=owner,
                    followers_count=9999,
                    media_count=999,
                    fetched_at=NOW + timedelta(days=1),
                    raw_response={},
                )
            )
        reader = SqlAlchemyInstagramStatsRepository(sessions, True, context)
        counts = (await reader.get_audience_counts([owner]))[owner]
        assert (counts.followers_count, counts.media_count) == (120, 50)
        later = NOW + timedelta(seconds=20)
        partial = DiscoveryResult(
            "success",
            DiscoveryProfile("987", target.username, None, 0, {"name": "New"}),
        )
        await repo.finish(target, partial, "discovery:test", later)
        with discovery_db.begin() as conn:
            row = (
                conn.execute(sa.select(D).where(D.c.user_id == owner))
                .mappings()
                .one()
            )
            assert row["followers_count"] == 120
            assert row["followers_observed_at"] == NOW
            assert row["media_count"] == 0
            assert row["media_observed_at"] == later
            assert row["details"]["biography"]["observed_at"] == NOW.isoformat()
            assert row["details"]["name"]["value"] == "New"
            assert (
                conn.execute(sa.select(P.__table__).where(P.user_id == owner))
                .mappings()
                .one()
                == before
            )
            assert (
                conn.execute(sa.select(H).where(H.c.user_id == owner))
                .mappings()
                .one()
                == health
            )
            assert (
                conn.scalar(sa.select(sa.func.count()).select_from(NOTICES))
                == notices
            )
        conflict = DiscoveryResult(
            "success", DiscoveryProfile("111", target.username, 500, 500)
        )
        assert (
            await repo.finish(target, conflict, "discovery:test", later)
            == "identity_conflict"
        )
        with discovery_db.begin() as conn:
            conn.execute(
                sa.update(P)
                .where(P.user_id == owner)
                .values(instagram_user_id="new-id")
            )
        assert (
            await repo.finish(target, result, "discovery:test", later)
            == "identity_changed"
        )
        # Old snapshot cannot be used for the newly linked account.
        with discovery_db.begin() as conn:
            conn.execute(sa.delete(S).where(S.user_id == owner))
            conn.execute(
                sa.update(P)
                .where(P.user_id == owner)
                .values(instagram_followers_count=None)
            )
        assert await reader.get_audience_counts([owner]) == {}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_meta_count_beats_undated_legacy_and_failed_attempt_timestamp(
    discovery_db,
):
    context = str(uuid4())
    owner = seed(discovery_db, context)
    with discovery_db.begin() as conn:
        conn.execute(
            S.__table__.insert().values(
                user_id=owner,
                followers_count=9999,
                media_count=999,
                fetched_at=NOW,
                raw_response={},
            )
        )
    engine, sessions = async_sessions(discovery_db)
    repo = SqlAlchemyInstagramStatsRepository(sessions)
    try:
        counts = (await repo.get_audience_counts([owner]))[owner]
        assert (counts.followers_count, counts.media_count) == (110, 999)
        await repo.touch_fetched_at(owner, NOW + timedelta(days=10))
        assert (await repo.get_audience_counts([owner]))[
            owner
        ].followers_count == 110
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_scheduled_http_to_matching_on_migrated_database(discovery_db):
    context = str(uuid4())
    owner = seed(discovery_db, context)
    engine, sessions = async_sessions(discovery_db)
    repo = DiscoveryRepository(sessions, context)
    calls = []

    def handler(request):
        calls.append(request)
        assert "access_token" not in str(request.url)
        handle = (
            request.url.params["fields"].split("username(")[1].split(")")[0]
        )
        return httpx.Response(
            200,
            json={
                "business_discovery": {
                    "id": "234",
                    "username": handle,
                    "followers_count": 140,
                    "media_count": 0,
                    "has_profile_pic": True,
                }
            },
        )

    clock = NOW

    async def sleep(seconds):
        nonlocal clock
        clock += timedelta(seconds=seconds)

    try:
        assert await repo.claim(NOW - timedelta(minutes=1)) is None
        assert not calls
        lease = await repo.claim(NOW)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http:
            client = DiscoveryClient(http, credential())
            await scheduled_batch(
                repo, lease, client, now=lambda: clock, sleep=sleep
            )
        assert len(calls) == 1
        reader = SqlAlchemyInstagramStatsRepository(sessions, True, context)
        counts = (await reader.get_audience_counts([owner]))[owner]
        assert (counts.followers_count, counts.media_count) == (140, 0)
        assert await repo.claim(NOW + timedelta(hours=1)) is None
    finally:
        await engine.dispose()


def test_downgrade_refuses_to_delete_collected_state(discovery_db):
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0147_instagram_discovery"
    )
    with discovery_db.begin() as conn:
        conn.execute(C.insert().values(singleton=1, next_run_at=NOW))
    with (
        pytest.raises(DBAPIError, match="explicit_retention_decision"),
        discovery_db.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.downgrade()
    with discovery_db.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(C)) == 1


@pytest.mark.asyncio
async def test_busy_ownership_writer_aborts_enrichment_without_data_changes(
    discovery_db,
):
    context = str(uuid4())
    owner = seed(discovery_db, context)
    engine, sessions = async_sessions(discovery_db)
    repo = DiscoveryRepository(sessions, context)
    try:
        await repo.claim(NOW - timedelta(minutes=1))
        lease = await repo.claim(NOW)
        target = await repo.prepare(lease, NOW)
        result = DiscoveryResult(
            "success", DiscoveryProfile("987", target.username, 100, 10)
        )
        with discovery_db.begin() as busy:
            busy.execute(
                sa.text(
                    "SELECT user_id FROM users WHERE user_id=:id FOR UPDATE"
                ),
                {"id": owner},
            )
            with pytest.raises(DBAPIError, match="lock timeout"):
                await repo.finish(target, result, "discovery:test", NOW)
        with discovery_db.connect() as conn:
            snapshot = (
                conn.execute(sa.select(D).where(D.c.user_id == owner))
                .mappings()
                .one()
            )
            assert snapshot["observed_at"] is None
            assert snapshot["last_outcome"] == "reserved"
            assert (
                conn.scalar(sa.select(P.confirmed).where(P.user_id == owner))
                is True
            )
    finally:
        await engine.dispose()
