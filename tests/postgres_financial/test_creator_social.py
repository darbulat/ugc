"""Real PostgreSQL creator identities, social races and caller transactions."""

import asyncio
import importlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel


def seed_user(connection, *, telegram_id=None):
    owner = uuid4()
    connection.execute(
        UserModel.__table__.insert().values(
            user_id=owner,
            telegram_id=telegram_id or str(owner),
            messenger_type="telegram",
            username="creator",
            status="active",
        )
    )
    return owner


def profile_values(owner, *, stable_id=None, confirmed=True):
    return dict(
        user_id=owner,
        instagram_url=f"https://instagram.com/u{owner.hex}",
        confirmed=confirmed,
        city="Moscow",
        topics={},
        audience_gender="all",
        audience_age_min=18,
        audience_age_max=40,
        audience_geo="Moscow",
        price=1000,
        barter=False,
        work_format="ugc_only",
        instagram_user_id=stable_id,
    )


def seed_profile(connection, *, stable_id=None, confirmed=True):
    owner = seed_user(connection)
    values = profile_values(owner, stable_id=stable_id, confirmed=confirmed)
    connection.execute(BloggerProfileModel.__table__.insert().values(**values))
    return owner


@pytest.fixture
def social_owner(financial_pg_engine):
    with financial_pg_engine.begin() as connection:
        return seed_profile(connection, stable_id=str(uuid4()))


def test_stable_instagram_identity_has_database_unique_guard(
    financial_pg_engine,
):
    stable_id = str(uuid4())
    with financial_pg_engine.begin() as connection:
        seed_profile(connection, stable_id=stable_id)
    with (
        pytest.raises(IntegrityError),
        financial_pg_engine.begin() as connection,
    ):
        seed_profile(connection, stable_id=stable_id)


def test_confirmed_legacy_profiles_without_stable_id_remain_valid(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        first = seed_profile(connection)
        second = seed_profile(connection)
        assert first != second


def test_instagram_identity_concurrent_verifications_have_one_winner(
    financial_pg_engine,
):
    stable_id = str(uuid4())
    barrier = Barrier(2)

    def attempt():
        try:
            with financial_pg_engine.begin() as connection:
                owner = seed_user(connection)
                barrier.wait(timeout=10)
                connection.execute(
                    BloggerProfileModel.__table__.insert().values(
                        **profile_values(owner, stable_id=stable_id)
                    )
                )
            return True
        except IntegrityError:
            return False

    with ThreadPoolExecutor(2) as workers:
        outcomes = list(workers.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == [False, True]


def test_telegram_identity_cannot_register_two_canonical_creators(
    financial_pg_engine,
):
    telegram_id = str(uuid4())
    with financial_pg_engine.begin() as connection:
        seed_user(connection, telegram_id=telegram_id)
    with (
        pytest.raises(IntegrityError),
        financial_pg_engine.begin() as connection,
    ):
        seed_user(connection, telegram_id=telegram_id)


def test_social_schema_has_nullable_observed_metrics(financial_pg_engine):
    columns = {
        c["name"]: c
        for c in inspect(financial_pg_engine).get_columns(
            "creator_social_accounts"
        )
    }
    for name in ("followers_count", "metrics_source", "metrics_fetched_at"):
        assert columns[name]["nullable"] is True


@pytest.mark.parametrize(
    "changes",
    [
        {"platform": "unsupported"},
        {"verified": True},
        {"external_id": "invented-id"},
        {
            "followers_count": -1,
            "metrics_source": "public_api",
            "metrics_fetched_at": datetime.now(timezone.utc),
        },
        {"followers_count": 500},
        {"metrics_source": "public_api"},
        {"work_format": "invalid"},
    ],
)
def test_database_rejects_untruthful_social_state(
    financial_pg_engine, social_owner, changes
):
    values = (
        dict(
            account_id=uuid4(),
            user_id=social_owner,
            platform="telegram",
            url="https://t.me/creator",
            handle="creator",
            verified=False,
            work_format="ugc_only",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        | changes
    )
    with (
        pytest.raises(IntegrityError),
        financial_pg_engine.begin() as connection,
    ):
        from ugc_bot.infrastructure.db.social_models import SocialAccountModel

        connection.execute(
            SocialAccountModel.__table__.insert().values(**values)
        )


@pytest.mark.asyncio
async def test_sql_service_round_trip_and_owner_checked_removal(
    financial_pg_engine, social_owner
):
    from ugc_bot.application.services.social_account_service import (
        SocialAccountService,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )
    from ugc_bot.infrastructure.db.repositories.social import (
        SqlAlchemySocialAccountRepository,
    )
    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemySocialAccountRepository(factory)
    service = SocialAccountService(
        repo,
        SqlAlchemyBloggerProfileRepository(factory),
        SessionTransactionManager(factory),
    )
    try:
        account = await service.save_account(
            social_owner, "telegram", "https://t.me/creator"
        )
        persisted = await repo.get_by_id(account.account_id)
        assert persisted == account
        assert persisted.followers_count is None
        assert await repo.remove(uuid4(), account.account_id) is False
        assert (
            await service.remove_account(social_owner, account.account_id)
            is True
        )
        assert await repo.get_by_id(account.account_id) is None
        assert await repo.list_accounts(social_owner) == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_social_upsert_race_preserves_one_account(
    financial_pg_engine, social_owner
):
    from ugc_bot.application.services.social_account_service import (
        SocialAccountService,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )
    from ugc_bot.infrastructure.db.repositories.social import (
        SqlAlchemySocialAccountRepository,
    )

    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemySocialAccountRepository(factory)
    service = SocialAccountService(
        repo, SqlAlchemyBloggerProfileRepository(factory)
    )
    try:
        one, two = await asyncio.gather(
            service.save_account(
                social_owner, "telegram", "https://t.me/first"
            ),
            service.save_account(
                social_owner, "telegram", "https://t.me/second"
            ),
        )
        assert one.account_id == two.account_id
        assert one.created_at == two.created_at
        assert len(await repo.list_accounts(social_owner)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_social_respects_caller_rollback(
    financial_pg_engine, social_owner
):
    from ugc_bot.application.services.social_account_service import (
        SocialAccountService,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )
    from ugc_bot.infrastructure.db.repositories.social import (
        SqlAlchemySocialAccountRepository,
    )

    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemySocialAccountRepository(factory)
    service = SocialAccountService(
        repo, SqlAlchemyBloggerProfileRepository(factory)
    )
    try:
        async with factory() as session:
            account = await service.save_account(
                social_owner,
                "telegram",
                "https://t.me/creator",
                session=session,
            )
            assert (
                len(await service.list_accounts(social_owner, session=session))
                == 2
            )
            assert (
                await service.next_platform(social_owner, session=session)
                == "tiktok"
            )
            await session.rollback()
        assert await repo.get_by_id(account.account_id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sql_profile_identity_lookup_and_conflict_translation(
    financial_pg_engine, social_owner
):
    from ugc_bot.domain.social import CreatorIdentityConflict
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    try:
        profile = await repo.get_by_user_id(social_owner)
        assert (
            await repo.get_by_instagram_user_id(profile.instagram_user_id)
            == profile
        )
        assert await repo.get_by_instagram_user_id("missing") is None
        with financial_pg_engine.begin() as connection:
            other = seed_profile(connection, confirmed=False)
        other_profile = await repo.get_by_user_id(other)
        with pytest.raises(CreatorIdentityConflict):
            await repo.save(
                replace(
                    other_profile,
                    confirmed=True,
                    instagram_user_id=profile.instagram_user_id,
                )
            )
        assert (await repo.get_by_user_id(other)).confirmed is False
    finally:
        await engine.dispose()


def test_migration_duplicate_preflight_preserves_existing_profiles(
    financial_pg_engine,
):
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.creator_social_v1"
    )
    with financial_pg_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DROP TABLE creator_social_accounts"))
            connection.execute(
                text("DROP INDEX uq_blogger_verified_instagram_identity")
            )
            stable_id = str(uuid4())
            first = seed_profile(connection, stable_id=stable_id)
            second = seed_profile(connection, stable_id=stable_id)
            with (
                Operations.context(MigrationContext.configure(connection)),
                pytest.raises(RuntimeError, match="duplicate.*Instagram"),
            ):
                migration.upgrade()
            assert (
                connection.scalar(
                    select(text("count(*)"))
                    .select_from(BloggerProfileModel)
                    .where(BloggerProfileModel.user_id.in_([first, second]))
                )
                == 2
            )
        finally:
            transaction.rollback()


def test_legacy_identity_cutover_preserves_unknown_verification_date(
    financial_pg_engine,
):
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.creator_social_v1"
    )
    with financial_pg_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("DROP TABLE creator_social_accounts"))
            connection.execute(
                text("DROP INDEX uq_blogger_verified_instagram_identity")
            )
            known = seed_profile(connection, stable_id="cutover-known-id")
            unknown = seed_profile(connection)
            unconfirmed = seed_profile(
                connection, stable_id="unconfirmed-id", confirmed=False
            )
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            row = (
                connection.execute(
                    text(
                        "SELECT * FROM creator_social_accounts "
                        "WHERE user_id = :owner"
                    ),
                    {"owner": known},
                )
                .mappings()
                .one()
            )
            assert row["verified_at"] is None
            assert row["verification_observed_at"] is not None
            assert row["verification_source"] == "legacy_profile_cutover"
            assert row["external_id"] == "cutover-known-id"
            assert row["followers_count"] is None
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM creator_social_accounts "
                        "WHERE user_id IN (:unknown, :unconfirmed)"
                    ),
                    {"unknown": unknown, "unconfirmed": unconfirmed},
                )
                == 0
            )
        finally:
            transaction.rollback()


@pytest.mark.parametrize("empty", [True, False])
def test_social_downgrade_never_discards_existing_links(
    financial_pg_engine, social_owner, empty
):
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.creator_social_v1"
    )
    with financial_pg_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "INSERT INTO creator_social_accounts "
                    "(account_id, user_id, platform, url, handle, verified, "
                    "work_format, created_at, updated_at) VALUES "
                    "(:account, :owner, 'telegram', 'https://t.me/creator', "
                    "'creator', false, 'ugc_only', now(), now())"
                ),
                {"account": uuid4(), "owner": social_owner},
            )
            if empty:
                connection.execute(text("DELETE FROM creator_social_accounts"))
            with Operations.context(MigrationContext.configure(connection)):
                if empty:
                    migration.downgrade()
                    assert (
                        connection.scalar(
                            text(
                                "SELECT to_regclass('creator_social_accounts')"
                            )
                        )
                        is None
                    )
                    migration.upgrade()
                else:
                    with pytest.raises(RuntimeError, match="discard"):
                        migration.downgrade()
                    assert (
                        connection.scalar(
                            text(
                                "SELECT count(*) FROM creator_social_accounts "
                                "WHERE user_id = :owner"
                            ),
                            {"owner": social_owner},
                        )
                        == 1
                    )
        finally:
            transaction.rollback()
