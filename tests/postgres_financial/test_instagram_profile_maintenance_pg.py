"""Real migrated PostgreSQL: observations, ownership races and notice leases."""

import asyncio
import importlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_creator_social import (
    profile_values,
    seed_user,
)
from ugc_bot.application.ports import InstagramProfileInfo
from ugc_bot.application.services.instagram_profile_maintenance import (
    InstagramProfileMaintenance,
)
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
    VerificationSuccess,
)
from ugc_bot.application.services.social_account_service import (
    instagram_account,
)
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.instagram_maintenance_models import (
    HEALTH,
    NOTICES,
    OBSERVATIONS,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    InteractionModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.instagram import (
    SqlAlchemyInstagramVerificationRepository,
)
from ugc_bot.infrastructure.db.repositories.instagram_maintenance import (
    SqlAlchemyInstagramMaintenanceRepository,
)
from ugc_bot.infrastructure.db.repositories.profiles import (
    SqlAlchemyBloggerProfileRepository,
)
from ugc_bot.infrastructure.db.repositories.social import (
    SqlAlchemySocialAccountRepository,
)
from ugc_bot.infrastructure.db.repositories.user import SqlAlchemyUserRepository
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInstagramGraphApiClient,
)

NOW = datetime(2026, 11, 19, 9, tzinfo=timezone.utc)  # 12:00 MSK


@pytest_asyncio.fixture
async def runtime(financial_pg_engine):
    with financial_pg_engine.begin() as conn:
        owner = seed_user(conn, telegram_id=str(uuid4().int)[:12])
        values = profile_values(owner, stable_id=str(uuid4()))
        values["instagram_url"] = "https://instagram.com/p" + owner.hex[:20]
        values["instagram_followers_count"] = 80
        values["instagram_stats_fetched_at"] = NOW - timedelta(days=10)
        conn.execute(BloggerProfileModel.__table__.insert().values(**values))
    engine = create_async_engine(financial_pg_engine.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    profiles = SqlAlchemyBloggerProfileRepository(sessions)
    tx = SessionTransactionManager(sessions)
    repo = SqlAlchemyInstagramMaintenanceRepository(profiles, "ig:app:umc")
    service = InstagramProfileMaintenance(repo, tx)
    async with tx.transaction() as db:
        profile = await profiles.get_by_user_id(owner, session=db)
    try:
        yield owner, profile, repo, service, tx, profiles, sessions
    finally:
        await engine.dispose()


async def rows(tx, table, owner):
    async with tx.transaction() as db:
        column = table.c.user_id if "user_id" in table.c else table.c.creator_id
        return (
            (await db.execute(sa.select(table).where(column == owner)))
            .mappings()
            .all()
        )


@pytest.mark.asyncio
async def test_rename_preserves_metrics_proof_and_appends_history(runtime):
    owner, profile, repo, service, tx, profiles, sessions = runtime
    social = SqlAlchemySocialAccountRepository(sessions)
    account = replace(
        instagram_account(profile),
        verified_at=NOW - timedelta(days=20),
        verification_observed_at=NOW - timedelta(days=20),
        verification_source="legacy_profile_cutover",
    )
    async with tx.transaction() as db:
        await social.save(account, session=db)
    handle = "renamed" + owner.hex[:12]
    assert await service.observe(
        profile, InstagramProfileInfo(username=handle), NOW
    )
    async with tx.transaction() as db:
        updated = await profiles.get_by_user_id(owner, session=db)
        stored = (await social.list_accounts(owner, session=db))[0]
    assert updated.instagram_user_id == profile.instagram_user_id
    assert updated.confirmed and updated.instagram_followers_count == 80
    assert (
        updated.instagram_stats_fetched_at == profile.instagram_stats_fetched_at
    )
    assert updated.instagram_url == f"https://www.instagram.com/{handle}"
    assert stored.handle == handle and stored.verified_at == account.verified_at
    assert stored.verification_source == "legacy_profile_cutover"
    history = await rows(tx, OBSERVATIONS, owner)
    assert history[0]["new_handle"] == handle
    assert history[0]["id_kind"] == "legacy_meta_id"
    assert await rows(tx, NOTICES, owner) == []
    with pytest.raises(DBAPIError, match="history_required"):
        async with tx.transaction() as db:
            await db.execute(
                sa.delete(OBSERVATIONS).where(OBSERVATIONS.c.user_id == owner)
            )


@pytest.mark.asyncio
async def test_repeated_unavailability_queues_once_recovers_without_unconfirm(
    runtime,
):
    owner, profile, repo, service, tx, profiles, _ = runtime
    for hours in (0, 1, 6, 12):
        assert not await service.observe(
            profile, None, NOW + timedelta(hours=hours), error="100/33"
        )
    health = (await rows(tx, HEALTH, owner))[0]
    assert health["failure_count"] == 3 and health["status"] == "review"
    jobs = await rows(tx, NOTICES, owner)
    assert len(jobs) == 1 and jobs[0]["not_before"].hour == 15  # 18:00 MSK
    async with tx.transaction() as db:
        assert (await profiles.get_by_user_id(owner, session=db)).confirmed
        assert owner not in await profiles.list_confirmed_user_ids(session=db)
        checks = await profiles.list_confirmed_with_instagram_id(
            1000, session=db
        )
        assert owner in {p.user_id for p in checks}
    assert await service.observe(
        profile,
        InstagramProfileInfo(username=health["handle"], followers_count=81),
        NOW + timedelta(hours=24),
    )
    assert (await rows(tx, NOTICES, owner))[0]["state"] == "obsolete"
    assert (await rows(tx, HEALTH, owner))[0]["status"] == "healthy"
    async with tx.transaction() as db:
        assert owner in await profiles.list_confirmed_user_ids(session=db)


@pytest.mark.asyncio
async def test_stale_lookup_cannot_overwrite_owner_edits_or_new_identity(
    runtime,
):
    owner, profile, repo, service, tx, profiles, _ = runtime
    async with tx.transaction() as db:
        await profiles.save(
            replace(profile, instagram_url="https://instagram.com/new"),
            session=db,
        )
    assert not await service.observe(
        profile, InstagramProfileInfo(username="stale"), NOW
    )
    assert not await service.observe(profile, None, NOW, error="100/33")
    assert await rows(tx, HEALTH, owner) == []


@pytest.mark.asyncio
async def test_global_errors_and_older_results_do_not_quarantine(runtime):
    owner, profile, repo, service, tx, _, _ = runtime
    assert not await service.observe(profile, None, NOW, error="190")
    assert await rows(tx, HEALTH, owner) == []
    await service.observe(profile, None, NOW, error="not_found")
    await service.observe(
        profile, None, NOW - timedelta(hours=1), error="100/33"
    )
    assert (await rows(tx, HEALTH, owner))[0]["failure_count"] == 1


async def quarantine(runtime):
    owner, profile, repo, service, tx, profiles, _ = runtime
    for hours in (0, 6):
        await service.observe(
            profile, None, NOW + timedelta(hours=hours), error="100/33"
        )
    return NOW + timedelta(hours=6)


@pytest.mark.asyncio
async def test_two_workers_claim_only_once_and_expired_sender_is_unknown(
    runtime,
):
    owner, _, repo, _, tx, _, _ = runtime
    due = await quarantine(runtime)

    async def claim():
        async with tx.transaction() as db:
            return await repo.claim(due, session=db)

    notices = await asyncio.gather(claim(), claim())
    notice = next(n for n in notices if n is not None)
    assert sum(n is not None for n in notices) == 1
    assert notice.card.callbacks[0].data == "instagram:refresh"
    async with tx.transaction() as db:
        assert await repo.claim(due + timedelta(minutes=6), session=db) is None
        await repo.finish(notice, "sent", due, reference="late", session=db)
    job = (await rows(tx, NOTICES, owner))[0]
    assert job["state"] == "unknown" and job["provider_reference"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [False, True])
async def test_night_waiting_job_rechecks_current_contact_and_block(
    runtime, blocked
):
    owner, _, repo, _, tx, _, _ = runtime
    due = await quarantine(runtime)
    new_address = str(uuid4().int)[:12]
    async with tx.transaction() as db:
        await db.execute(
            sa.update(UserModel)
            .where(UserModel.user_id == owner)
            .values(
                telegram_id=new_address,
                status="bot_blocked" if blocked else "active",
            )
        )
        assert await repo.claim(due.replace(hour=20), session=db) is None
        notice = await repo.claim(due, session=db)
    if blocked:
        assert notice is None
        assert (await rows(tx, NOTICES, owner))[0]["state"] == "obsolete"
    else:
        assert notice.address == new_address
        async with tx.transaction() as db:
            await repo.finish(
                notice, "sent", due, reference="telegram:42", session=db
            )
        assert (await rows(tx, NOTICES, owner))[0][
            "provider_reference"
        ] == "telegram:42"


@pytest.mark.asyncio
async def test_fresh_proof_clears_review_and_types_scoped_id(
    runtime,
):
    owner, profile, repo, service, tx, profiles, _ = runtime
    due = await quarantine(runtime)
    confirmed = replace(
        profile,
        instagram_user_id="fresh" + owner.hex,
        instagram_url="https://instagram.com/proven" + owner.hex[:12],
    )
    async with tx.transaction() as db:
        await profiles.save(confirmed, session=db)
        await service.verified(
            confirmed, due + timedelta(minutes=1), session=db
        )
    health = (await rows(tx, HEALTH, owner))[0]
    assert health["meta_id"] == confirmed.instagram_user_id
    assert health["id_kind"] == "instagram_scoped_id"
    assert health["identity_context"] == "ig:app:umc"
    assert health["failure_count"] == 0
    assert (await rows(tx, NOTICES, owner))[0]["state"] == "obsolete"


def test_empty_context_and_nontransactional_calls_rejected():
    with pytest.raises(ValueError, match="context"):
        SqlAlchemyInstagramMaintenanceRepository(None, " ")


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["none", "closed", "owner", "profile"])
async def test_customer_gets_latest_link_only_for_current_active_order(
    runtime, financial_pg_engine, change
):
    owner, profile, repo, service, tx, profiles, _ = runtime
    with financial_pg_engine.begin() as conn:
        customer = seed_user(conn, telegram_id=str(uuid4().int)[:12])
        order = uuid4()
        conn.execute(
            OrderModel.__table__.insert().values(
                order_id=order,
                advertiser_id=customer,
                status="active",
                product_link="https://example.test/product",
                offer_text="test",
                price=1000,
                bloggers_needed=1,
            )
        )
        conn.execute(
            InteractionModel.__table__.insert().values(
                interaction_id=uuid4(),
                order_id=order,
                blogger_id=owner,
                advertiser_id=customer,
                status="pending",
            )
        )
    handle = "customer" + owner.hex[:12]
    await service.observe(profile, InstagramProfileInfo(handle), NOW)
    # Subsequent successful checks of the same handle do not duplicate notices.
    async with tx.transaction() as db:
        current = await profiles.get_by_user_id(owner, session=db)
    await service.observe(
        current, InstagramProfileInfo(handle), NOW + timedelta(minutes=1)
    )
    jobs = await rows(tx, NOTICES, owner)
    assert len(jobs) == 1 and jobs[0]["recipient_id"] == customer
    async with tx.transaction() as db:
        if change == "closed":
            await db.execute(
                sa.update(OrderModel)
                .where(OrderModel.order_id == order)
                .values(status="closed")
            )
        elif change == "owner":
            await db.execute(
                sa.update(OrderModel)
                .where(OrderModel.order_id == order)
                .values(advertiser_id=owner)
            )
        elif change == "profile":
            await profiles.save(replace(current, confirmed=False), session=db)
        notice = await repo.claim(NOW + timedelta(minutes=2), session=db)
    if change == "none":
        assert notice is not None
        assert f"https://www.instagram.com/{handle}" in notice.text
        assert notice.card.callbacks == ()
        async with tx.transaction() as db:
            await repo.finish(
                notice, "sent", NOW, reference="customer:1", session=db
            )
    else:
        assert notice is None
        assert (await rows(tx, NOTICES, owner))[0]["state"] == "obsolete"


@pytest.mark.asyncio
@pytest.mark.parametrize("has_chat", [False, True])
async def test_max_current_address_kind_is_not_assumed(runtime, has_chat):
    owner, _, repo, _, tx, _, _ = runtime
    due = await quarantine(runtime)
    address = str(uuid4().int)[:12]
    async with tx.transaction() as db:
        await db.execute(
            sa.update(UserModel)
            .where(UserModel.user_id == owner)
            .values(
                messenger_type="max",
                max_id=address,
                max_chat_id="-" + address if has_chat else None,
            )
        )
        notice = await repo.claim(due, session=db)
        assert notice.channel == "max"
        assert notice.address_kind == ("chat_id" if has_chat else "user_id")
        assert notice.address == ("-" + address if has_chat else address)
        await repo.finish(notice, "sent", due, reference="max:1", session=db)


@pytest.mark.asyncio
async def test_nontransactional_observer_rejected(runtime):
    _, profile, repo, _, _, _, _ = runtime
    with pytest.raises(ValueError, match="transaction_required"):
        await repo.observe(profile, None, NOW, error="100/33", session=object())


@pytest.mark.asyncio
async def test_scoped_id_cannot_be_reinterpreted_in_another_meta_app(runtime):
    owner, profile, _, service, tx, profiles, _ = runtime
    await service.observe(profile, None, NOW, error="100/33")
    other = InstagramProfileMaintenance(
        SqlAlchemyInstagramMaintenanceRepository(profiles, "other:app"), tx
    )
    assert not await other.observe(
        profile, InstagramProfileInfo("wrong_app"), NOW
    )
    async with tx.transaction() as db:
        current = await profiles.get_by_user_id(owner, session=db)
    assert current.instagram_url == profile.instagram_url
    assert (await rows(tx, HEALTH, owner))[0][
        "identity_context"
    ] == "ig:app:umc"
    # Only a new successful ownership proof may bind a new context.
    async with tx.transaction() as db:
        await other.verified(current, NOW, session=db)
    assert (await rows(tx, HEALTH, owner))[0]["identity_context"] == "other:app"


@pytest.mark.asyncio
async def test_real_verification_transaction_restores_owner_and_clears_queue(
    runtime,
    monkeypatch,
):
    owner, profile, _, maintenance, tx, profiles, sessions = runtime
    await quarantine(runtime)
    handle, scoped_id = "proof" + owner.hex[:12], "scoped" + owner.hex
    async with tx.transaction() as db:
        await profiles.save(
            replace(
                profile,
                confirmed=False,
                instagram_url=f"https://instagram.com/{handle}",
            ),
            session=db,
        )
    verification = InstagramVerificationService(
        user_repo=SqlAlchemyUserRepository(sessions),
        blogger_repo=profiles,
        verification_repo=SqlAlchemyInstagramVerificationRepository(sessions),
        social_repo=SqlAlchemySocialAccountRepository(sessions),
        instagram_api_client=InMemoryInstagramGraphApiClient(
            username_map={scoped_id: handle}
        ),
        transaction_manager=tx,
        profile_maintenance=maintenance,
    )
    # Docker Desktop and the host can differ by a few milliseconds. The
    # ownership trigger intentionally rejects facts later than the DB clock.
    async with tx.transaction() as db:
        proof_at = await db.scalar(sa.select(sa.func.clock_timestamp()))

    class ProofClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (proof_at - timedelta(seconds=1)).astimezone(tz)

    monkeypatch.setattr(
        "ugc_bot.application.services.instagram_verification_service.datetime",
        ProofClock,
    )
    code = await verification.generate_code(
        owner, channel=MessengerType.TELEGRAM
    )
    outcome = await verification.verify_code_by_instagram_sender(
        instagram_sender_id=scoped_id,
        code=code.code,
        admin_instagram_username="usemycontent",
    )
    assert isinstance(outcome, VerificationSuccess)
    async with tx.transaction() as db:
        confirmed = await profiles.get_by_user_id(owner, session=db)
        social = await SqlAlchemySocialAccountRepository(
            sessions
        ).list_accounts(owner, session=db)
    assert confirmed.confirmed and confirmed.instagram_user_id == scoped_id
    assert social[0].verified and social[0].external_id == scoped_id
    assert (await rows(tx, HEALTH, owner))[0][
        "id_kind"
    ] == "instagram_scoped_id"
    assert (await rows(tx, NOTICES, owner))[0]["state"] == "obsolete"


def test_downgrade_preserves_history(financial_pg_engine):
    with financial_pg_engine.begin() as conn:
        owner = seed_user(conn)
        conn.execute(
            sa.insert(OBSERVATIONS).values(
                observation_id=uuid4(),
                user_id=owner,
                meta_id="legacy",
                id_kind="legacy_meta_id",
                identity_context="app:umc",
                old_handle="old",
                new_handle="new",
                outcome="available",
                observed_at=NOW,
            )
        )
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0145_instagram_profile_maintenance"
    )
    with (
        pytest.raises(DBAPIError, match="history_required"),
        financial_pg_engine.begin() as conn,
        Operations.context(MigrationContext.configure(conn)),
    ):
        migration.downgrade()
