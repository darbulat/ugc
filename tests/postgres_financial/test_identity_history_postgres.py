"""Actual PostgreSQL immutable observations, as-of counts and writer races."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.postgres_financial.test_creator_social import seed_profile, seed_user


def instant(connection):
    return connection.scalar(text("SELECT clock_timestamp()"))


def direct_binding(connection, partner, creator, created_at=None):
    connection.execute(
        text(
            "INSERT INTO user_referral_bindings "
            "(referrer_user_id,referred_user_id,created_at) "
            "VALUES (:partner,:creator,:created)"
        ),
        {
            "partner": partner,
            "creator": creator,
            "created": created_at or instant(connection),
        },
    )


async def count_at(engine, partner, as_of, *, session=None):
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )

    async_engine = create_async_engine(engine.url)
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    try:
        return await CreatorIdentityHistoryService(
            SqlAlchemyCreatorIdentityHistoryRepository(factory)
        ).count_verified_direct_creators(partner, as_of, session=session)
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_real_history_cutover_and_pre_cutover_unknown(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        marker = (
            connection.execute(text("SELECT * FROM creator_identity_coverage"))
            .mappings()
            .one()
        )
        partner = seed_user(connection)
        now = instant(connection)
    assert (
        await count_at(financial_pg_engine, partner, now)
    ).verified_count == 0
    with pytest.raises(ValueError, match="coverage"):
        await count_at(
            financial_pg_engine,
            partner,
            marker["covered_from"] - timedelta(microseconds=1),
        )


@pytest.mark.asyncio
async def test_profile_insert_proof_rename_revoke_preserves_exact_old_count(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        direct_binding(connection, partner, creator)
        before = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE blogger_profiles SET confirmed=true WHERE "
                "user_id=:creator"
            ),
            {"creator": creator},
        )
        verified = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE blogger_profiles SET instagram_url=:url WHERE "
                "user_id=:creator"
            ),
            {
                "creator": creator,
                "url": "https://instagram.com/renamed_" + uuid4().hex,
            },
        )
        renamed = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE blogger_profiles SET confirmed=false WHERE "
                "user_id=:creator"
            ),
            {"creator": creator},
        )
        revoked = instant(connection)
    assert (
        await count_at(financial_pg_engine, partner, before)
    ).verified_count == 0
    assert (
        await count_at(financial_pg_engine, partner, verified)
    ).verified_count == 1
    assert (
        await count_at(financial_pg_engine, partner, renamed)
    ).verified_count == 1
    assert (
        await count_at(financial_pg_engine, partner, revoked)
    ).verified_count == 0
    with financial_pg_engine.connect() as connection:
        facts = (
            connection.execute(
                text(
                    "SELECT * FROM creator_identity_observations WHERE "
                    "creator_user_id=:creator ORDER BY observation_sequence"
                ),
                {"creator": creator},
            )
            .mappings()
            .all()
        )
    assert all(f["fact_at"] is None for f in facts)
    assert {f["source"] for f in facts} == {"canonical_profile_observed"}


@pytest.mark.asyncio
async def test_binding_correction_and_deletion_never_rewrite_old_network(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        first, second = seed_user(connection), seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, first, creator)
        before = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE user_referral_bindings SET "
                "referrer_user_id=:new,created_at=:old WHERE "
                "referred_user_id=:creator"
            ),
            {
                "new": second,
                "old": before - timedelta(days=100),
                "creator": creator,
            },
        )
        corrected = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM user_referral_bindings WHERE "
                "referred_user_id=:creator"
            ),
            {"creator": creator},
        )
        deleted = instant(connection)
    assert (
        await count_at(financial_pg_engine, first, before)
    ).verified_count == 1
    assert (
        await count_at(financial_pg_engine, second, before)
    ).verified_count == 0
    assert (
        await count_at(financial_pg_engine, first, corrected)
    ).verified_count == 0
    assert (
        await count_at(financial_pg_engine, second, corrected)
    ).verified_count == 1
    assert (
        await count_at(financial_pg_engine, second, deleted)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_id_switch_and_merge_preserve_old_canonical_ids(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        partner, merged = seed_user(connection), seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, partner, creator)
        before = instant(connection)
    with financial_pg_engine.begin() as connection:
        new_id = str(uuid4())
        connection.execute(
            text(
                "UPDATE blogger_profiles SET instagram_user_id=:id WHERE "
                "user_id=:creator"
            ),
            {"id": new_id, "creator": creator},
        )
        switched = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text("UPDATE blogger_profiles SET user_id=:new WHERE user_id=:old"),
            {"new": merged, "old": creator},
        )
        connection.execute(
            text(
                "UPDATE user_referral_bindings SET referred_user_id=:new "
                "WHERE referred_user_id=:old"
            ),
            {"new": merged, "old": creator},
        )
        connection.execute(
            text("DELETE FROM users WHERE user_id=:old"), {"old": creator}
        )
        after = instant(connection)
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM creator_identity_observations WHERE "
                    "creator_user_id=:old"
                ),
                {"old": creator},
            )
            > 0
        )
    for at in (before, switched, after):
        assert (
            await count_at(financial_pg_engine, partner, at)
        ).verified_count == 1


@pytest.mark.parametrize(
    "table",
    [
        "creator_identity_observations",
        "creator_direct_binding_observations",
        "creator_identity_coverage",
    ],
)
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_history_and_coverage_are_database_immutable(
    financial_pg_engine, table, operation
):
    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, partner, creator)
    statement = {
        "DELETE": f"DELETE FROM {table}",
        "UPDATE": f"UPDATE {table} SET source=source",
        "TRUNCATE": f"TRUNCATE TABLE {table}",
    }[operation]
    with (
        pytest.raises(DBAPIError, match="immutable"),
        financial_pg_engine.begin() as connection,
    ):
        connection.execute(text(statement))


@pytest.mark.asyncio
async def test_sql_repository_proof_and_history_rollback_with_caller(
    financial_pg_engine,
):
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        direct_binding(connection, partner, creator)
        fact_time = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    try:
        async with factory() as session:
            profile = await repo.get_by_user_id(creator, session=session)
            with identity_evidence(
                IdentityEvidence(
                    "instagram_webhook", "proof:" + str(uuid4()), fact_time
                )
            ):
                await repo.save(
                    replace(profile, confirmed=True), session=session
                )
            as_of = await session.scalar(text("SELECT clock_timestamp()"))
            assert (
                await count_at(
                    financial_pg_engine, partner, as_of, session=session
                )
            ).verified_count == 1
            proof = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM creator_identity_observations "
                            "WHERE creator_user_id=:creator ORDER BY "
                            "observation_sequence DESC LIMIT 1"
                        ),
                        {"creator": creator},
                    )
                )
                .mappings()
                .one()
            )
            assert proof["source"] == "instagram_webhook"
            assert proof["fact_at"] == fact_time
            await session.rollback()
        assert (
            await count_at(financial_pg_engine, partner, as_of)
        ).verified_count == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_proof_replay_has_one_immutable_business_fact(
    financial_pg_engine,
):
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        direct_binding(connection, partner, creator)
        fact_time = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    evidence = IdentityEvidence(
        "instagram_webhook", "proof:" + str(uuid4()), fact_time
    )
    try:
        profile = await repo.get_by_user_id(creator)

        async def attempt():
            with identity_evidence(evidence):
                await repo.save(replace(profile, confirmed=True))

        await asyncio.gather(attempt(), attempt())
        with financial_pg_engine.connect() as connection:
            proof_rows = connection.scalar(
                text(
                    "SELECT count(*) FROM creator_identity_observations WHERE "
                    "creator_user_id=:creator AND source='instagram_webhook'"
                ),
                {"creator": creator},
            )
            as_of = instant(connection)
        assert proof_rows == 1
        assert (
            await count_at(financial_pg_engine, partner, as_of)
        ).verified_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_missing_seed_detected_inside_caller_transaction(
    financial_pg_engine,
):
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO creator_identity_observations "
                    "(creator_user_id,instagram_user_id,active,source,busin"
                    "ess_key) VALUES "
                    "(:creator,'fake-seed',true,'canonical_profile_cutover'"
                    ",:key)"
                ),
                {"creator": uuid4(), "key": str(uuid4())},
            )
            as_of = await session.scalar(text("SELECT clock_timestamp()"))
            with pytest.raises(ValueError, match="coverage"):
                await count_at(
                    financial_pg_engine, uuid4(), as_of, session=session
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_history_reader_only_returns_requested_direct_network(
    financial_pg_engine,
):
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )

    with financial_pg_engine.begin() as connection:
        own, other = seed_user(connection), seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        stranger = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, own, creator)
        direct_binding(connection, other, stranger)
        at = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    try:
        facts = await SqlAlchemyCreatorIdentityHistoryRepository(
            async_sessionmaker(engine)
        ).read_network(own, at)
        assert {o.creator_user_id for o in facts.identities} == {creator}
        assert {b.referrer_user_id for b in facts.bindings} == {own}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    ["creator_identity_coverage", "blogger_profiles", "user_referral_bindings"],
)
async def test_missing_canonical_table_is_explicit_unknown(
    financial_pg_engine, table
):
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(
                text(f"ALTER TABLE {table} RENAME TO hidden_identity_source")
            )
            at = await session.scalar(text("SELECT clock_timestamp()"))
            with pytest.raises(ValueError, match="coverage"):
                await count_at(
                    financial_pg_engine, uuid4(), at, session=session
                )
            with pytest.raises(ValueError, match="coverage"):
                await attribution_at(
                    financial_pg_engine, uuid4(), at, session=session
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table,trigger",
    [
        ("blogger_profiles", "creator_profile_observation"),
        ("blogger_profiles", "creator_profile_write_barrier"),
        ("user_referral_bindings", "creator_binding_write_barrier"),
    ],
)
async def test_disabled_canonical_capture_is_out_of_coverage(
    financial_pg_engine,
    table,
    trigger,
):
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            await session.execute(
                text(f"ALTER TABLE {table} DISABLE TRIGGER {trigger}")
            )
            at = await session.scalar(text("SELECT clock_timestamp()"))
            with pytest.raises(ValueError, match="coverage"):
                await count_at(
                    financial_pg_engine, uuid4(), at, session=session
                )
            with pytest.raises(ValueError, match="coverage"):
                await attribution_at(
                    financial_pg_engine, uuid4(), at, session=session
                )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_account_id_round_trip_then_new_merge_emits_each_revocation(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        first, second, third = (
            seed_user(connection),
            seed_user(connection),
            seed_user(connection),
        )
        original = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, first, original)
        for old, new in [
            (original, second),
            (second, original),
            (original, third),
        ]:
            connection.execute(
                text(
                    "UPDATE blogger_profiles SET user_id=:new WHERE "
                    "user_id=:old"
                ),
                {"old": old, "new": new},
            )
            connection.execute(
                text(
                    "UPDATE user_referral_bindings SET referred_user_id=:new "
                    "WHERE referred_user_id=:old"
                ),
                {"old": old, "new": new},
            )
        latest = connection.execute(
            text(
                "SELECT active FROM creator_identity_observations WHERE "
                "creator_user_id=:old ORDER BY observation_sequence DESC "
                "LIMIT 1"
            ),
            {"old": original},
        ).scalar_one()
        assert latest is False
        at = instant(connection)
    assert (await count_at(financial_pg_engine, first, at)).verified_count == 1


@pytest.mark.asyncio
async def test_cutover_has_complete_seed_and_unknown_original_fact_time(
    financial_pg_engine,
):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.creator_identity_his"
        "tory_v1"
    )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            connection = await session.connection()

            def reset_and_cutover(sync_connection):
                sync_connection.execute(
                    text(
                        "DROP TRIGGER creator_profile_observation ON "
                        "blogger_profiles"
                    )
                )
                sync_connection.execute(
                    text(
                        "DROP TRIGGER creator_binding_observation ON "
                        "user_referral_bindings"
                    )
                )
                sync_connection.execute(
                    text(
                        "DROP TABLE "
                        "creator_identity_observations,creator_direct_bindi"
                        "ng_observations,creator_identity_coverage CASCADE"
                    )
                )
                partner = seed_user(sync_connection)
                creator = seed_profile(sync_connection, stable_id=str(uuid4()))
                direct_binding(
                    sync_connection,
                    partner,
                    creator,
                    instant(sync_connection) - timedelta(days=100),
                )
                with Operations.context(
                    MigrationContext.configure(sync_connection)
                ):
                    migration.upgrade()
                return partner, creator

            partner, creator = await connection.run_sync(reset_and_cutover)
            marker = (
                (
                    await session.execute(
                        text("SELECT * FROM creator_identity_coverage")
                    )
                )
                .mappings()
                .one()
            )
            baseline = (
                (
                    await session.execute(
                        text(
                            "SELECT * FROM creator_identity_observations "
                            "WHERE creator_user_id=:creator"
                        ),
                        {"creator": creator},
                    )
                )
                .mappings()
                .one()
            )
            assert baseline["fact_at"] is None
            assert baseline["observed_at"] == marker["covered_from"]
            assert baseline["source"] == "canonical_profile_cutover"
            result = await count_at(
                financial_pg_engine,
                partner,
                marker["covered_from"],
                session=session,
            )
            assert result.verified_count == 1
            with pytest.raises(ValueError, match="coverage"):
                await count_at(
                    financial_pg_engine,
                    partner,
                    marker["covered_from"] - timedelta(microseconds=1),
                    session=session,
                )
            with pytest.raises(RuntimeError, match="immutable"):
                migration.downgrade()
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_write_cannot_leak_proof_into_later_sql(
    financial_pg_engine, monkeypatch
):
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        fact_at = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    try:
        async with factory() as session:
            profile = await repo.get_by_user_id(creator, session=session)

            async def invalid_merge(*args, **kwargs):
                raise ValueError("invalid_profile_payload")

            monkeypatch.setattr(session, "merge", invalid_merge)
            with (
                identity_evidence(
                    IdentityEvidence(
                        "instagram_webhook", "must-not-leak", fact_at
                    )
                ),
                pytest.raises(ValueError, match="invalid_profile"),
            ):
                await repo.save(
                    replace(profile, confirmed=True), session=session
                )
            assert (
                await session.scalar(
                    text("SELECT current_setting('ugc.identity_key', true)")
                )
                == ""
            )
            await session.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_deletion_is_a_revocation_not_history_deletion(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, partner, creator)
        before = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM blogger_profiles WHERE user_id=:creator"),
            {"creator": creator},
        )
        after = instant(connection)
    assert (
        await count_at(financial_pg_engine, partner, before)
    ).verified_count == 1
    assert (
        await count_at(financial_pg_engine, partner, after)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_concurrent_duplicate_instagram_loser_leaves_no_verified_fact(
    financial_pg_engine,
):
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )
    from ugc_bot.domain.social import CreatorIdentityConflict
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creators = [seed_profile(connection, confirmed=False) for _ in range(2)]
        for creator in creators:
            direct_binding(connection, partner, creator)
        fact_time = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    stable_id = str(uuid4())
    try:

        async def attempt(creator):
            profile = await repo.get_by_user_id(creator)
            with identity_evidence(
                IdentityEvidence("instagram_webhook", str(uuid4()), fact_time)
            ):
                await repo.save(
                    replace(
                        profile, confirmed=True, instagram_user_id=stable_id
                    )
                )

        outcomes = await asyncio.gather(
            *(attempt(creator) for creator in creators), return_exceptions=True
        )
        assert (
            sum(
                isinstance(result, CreatorIdentityConflict)
                for result in outcomes
            )
            == 1
        )
        assert sum(result is None for result in outcomes) == 1
        with financial_pg_engine.connect() as connection:
            at = instant(connection)
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM creator_identity_observations "
                        "WHERE instagram_user_id=:id AND active"
                    ),
                    {"id": stable_id},
                )
                == 1
            )
        assert (
            await count_at(financial_pg_engine, partner, at)
        ).verified_count == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_conflicting_proof_replay_rolls_back_state_and_partial_revocation(
    financial_pg_engine,
):
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        at = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    evidence = IdentityEvidence("instagram_webhook", str(uuid4()), at)
    try:
        profile = await repo.get_by_user_id(creator)
        with identity_evidence(evidence):
            await repo.save(replace(profile, confirmed=True))
        with (
            identity_evidence(evidence),
            pytest.raises(DBAPIError, match="replay"),
        ):
            await repo.save(
                replace(profile, confirmed=True, instagram_user_id=str(uuid4()))
            )
        assert (
            await repo.get_by_user_id(creator)
        ).instagram_user_id == profile.instagram_user_id
        with financial_pg_engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM creator_identity_observations "
                        "WHERE creator_user_id=:creator AND "
                        "source='instagram_webhook'"
                    ),
                    {"creator": creator},
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_future_proof_fact_time_is_rejected_by_database(
    financial_pg_engine,
):
    from ugc_bot.application.identity_history_ports import (
        IdentityEvidence,
        identity_evidence,
    )
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        at = instant(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    try:
        profile = await repo.get_by_user_id(creator)
        with (
            identity_evidence(
                IdentityEvidence(
                    "instagram_webhook", str(uuid4()), at + timedelta(days=1)
                )
            ),
            pytest.raises(DBAPIError, match="future"),
        ):
            await repo.save(replace(profile, confirmed=True))
        assert (await repo.get_by_user_id(creator)).confirmed is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_pending_referral_is_not_a_direct_network_binding(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        connection.execute(
            text(
                "INSERT INTO user_referral_pending (user_id,referrer_user_id) "
                "VALUES (:creator,:partner)"
            ),
            {"creator": creator, "partner": partner},
        )
        at = instant(connection)
    assert (
        await count_at(financial_pg_engine, partner, at)
    ).verified_count == 0


@pytest.mark.parametrize(
    "table", ["blogger_profiles", "user_referral_bindings"]
)
def test_canonical_truncate_cannot_bypass_row_observations(
    financial_pg_engine, table
):
    with (
        financial_pg_engine.begin() as connection,
        pytest.raises(DBAPIError, match="observations"),
    ):
        connection.execute(text(f"TRUNCATE TABLE {table} CASCADE"))


async def attribution_at(engine, referred, as_of, *, session=None):
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )

    async_engine = create_async_engine(engine.url)
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    try:
        return await CreatorIdentityHistoryService(
            SqlAlchemyCreatorIdentityHistoryRepository(factory)
        ).resolve_direct_binding(referred, as_of, session=session)
    finally:
        await async_engine.dispose()


@pytest.mark.asyncio
async def test_direct_attribution_preserves_registration_and_correction_history(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        creator, first, second = (seed_user(connection) for _ in range(3))
        registered = instant(connection) - timedelta(days=400)
        connection.execute(
            text("UPDATE users SET created_at=:at WHERE user_id=:id"),
            {"at": registered, "id": creator},
        )
        direct_binding(
            connection, first, creator, registered + timedelta(days=10)
        )
        paid = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE users SET created_at=clock_timestamp() WHERE "
                "user_id=:id"
            ),
            {"id": creator},
        )
        connection.execute(
            text(
                "UPDATE user_referral_bindings SET referrer_user_id=:new WHERE "
                "referred_user_id=:id"
            ),
            {"new": second, "id": creator},
        )
        corrected = instant(connection)
    old = await attribution_at(financial_pg_engine, creator, paid)
    new = await attribution_at(financial_pg_engine, creator, corrected)
    assert old.referrer_user_id == first
    assert new.referrer_user_id == second
    assert old.registered_at == new.registered_at == registered
    assert old.binding_created_at == registered + timedelta(days=10)
    assert old.binding_effective_at <= paid
    assert old.observation_sequence < new.observation_sequence
    assert old.coverage_version == "creator_identity_history_v1"


@pytest.mark.asyncio
async def test_attribution_distinguishes_absent_revoked_and_unknown(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        partner, creator = seed_user(connection), seed_user(connection)
        before = instant(connection)
        direct_binding(
            connection, partner, creator, before - timedelta(days=20)
        )
        active = instant(connection)
    with financial_pg_engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM user_referral_bindings WHERE referred_user_id=:id"
            ),
            {"id": creator},
        )
        deleted = instant(connection)
        cutover = connection.scalar(
            text("SELECT covered_from FROM creator_identity_coverage")
        )
    absent = await attribution_at(financial_pg_engine, creator, before)
    assert absent.referrer_user_id is None and absent.reason == "unbound"
    assert absent.registered_at is None
    assert (
        await attribution_at(financial_pg_engine, creator, active)
    ).referrer_user_id == partner
    revoked = await attribution_at(financial_pg_engine, creator, deleted)
    assert revoked.referrer_user_id is None and revoked.reason == "revoked"
    assert revoked.observation_sequence is not None
    with pytest.raises(ValueError, match="coverage"):
        await attribution_at(
            financial_pg_engine, creator, cutover - timedelta(microseconds=1)
        )


@pytest.mark.asyncio
async def test_future_binding_replacement_never_resurrects_old_recipient(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        first, second = seed_user(connection), seed_user(connection)
        creator = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, first, creator)
        paid = instant(connection)
    with financial_pg_engine.begin() as connection:
        future = instant(connection) + timedelta(days=1)
        connection.execute(
            text(
                "UPDATE user_referral_bindings SET "
                "referrer_user_id=:new,created_at=:future WHERE "
                "referred_user_id=:id"
            ),
            {"new": second, "future": future, "id": creator},
        )
        gap = instant(connection)
        facts = (
            connection.execute(
                text(
                    "SELECT active FROM creator_direct_binding_observations "
                    "WHERE referred_user_id=:id ORDER BY observation_sequence"
                ),
                {"id": creator},
            )
            .scalars()
            .all()
        )
    assert facts == [True, False, True]
    assert (
        await attribution_at(financial_pg_engine, creator, paid)
    ).referrer_user_id == first
    result = await attribution_at(financial_pg_engine, creator, gap)
    assert result.referrer_user_id is None
    assert result.reason == "not_yet_effective"
    assert result.binding_effective_at == future
    assert (await count_at(financial_pg_engine, first, gap)).verified_count == 0
    assert (
        await count_at(financial_pg_engine, second, gap)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_direct_attribution_self_referral_is_ineligible_and_not_counted(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        creator = seed_profile(connection, stable_id=str(uuid4()))
        direct_binding(connection, creator, creator)
        at = instant(connection)
    result = await attribution_at(financial_pg_engine, creator, at)
    assert result.referrer_user_id is None
    assert result.reason == "self_referral"
    assert (
        await count_at(financial_pg_engine, creator, at)
    ).verified_count == 0


@pytest.mark.asyncio
async def test_direct_attribution_reads_caller_transaction_and_rollback(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        creator, partner = seed_user(connection), seed_user(connection)
    engine = create_async_engine(financial_pg_engine.url)
    try:
        async with async_sessionmaker(engine)() as session:
            await session.begin()
            await session.execute(
                text(
                    "INSERT INTO user_referral_bindings "
                    "(referrer_user_id,referred_user_id,created_at) VALUES "
                    "(:partner,:creator,clock_timestamp())"
                ),
                {"partner": partner, "creator": creator},
            )
            at = await session.scalar(text("SELECT clock_timestamp()"))
            observed = await attribution_at(
                financial_pg_engine, creator, at, session=session
            )
            assert observed.referrer_user_id == partner
            await session.rollback()
        result = await attribution_at(financial_pg_engine, creator, at)
        assert result.referrer_user_id is None and result.reason == "unbound"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_cutover_marker_is_unknown_for_count_and_attribution(
    financial_pg_engine,
):
    engine = create_async_engine(financial_pg_engine.url)
    try:
        async with async_sessionmaker(engine)() as session:
            await session.execute(
                text(
                    "ALTER TABLE creator_identity_coverage DISABLE TRIGGER "
                    "creator_coverage_immutable"
                )
            )
            await session.execute(text("DELETE FROM creator_identity_coverage"))
            await session.execute(
                text(
                    "ALTER TABLE creator_identity_coverage ENABLE TRIGGER "
                    "creator_coverage_immutable"
                )
            )
            at = await session.scalar(text("SELECT clock_timestamp()"))
            for reader in (count_at, attribution_at):
                with pytest.raises(ValueError, match="coverage"):
                    await reader(
                        financial_pg_engine, uuid4(), at, session=session
                    )
            await session.rollback()
    finally:
        await engine.dispose()


async def history_service(engine):
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )

    return CreatorIdentityHistoryService(
        SqlAlchemyCreatorIdentityHistoryRepository(async_sessionmaker(engine))
    )


async def wait_for_advisory_waiter(engine, pid, task):
    async with engine.connect() as connection:
        for _ in range(300):
            if task.done():
                await task
                raise AssertionError("history barrier did not wait")
            blocked = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                    "WHERE pid=:pid AND locktype='advisory' AND NOT granted)"
                ),
                {"pid": pid},
            )
            if blocked:
                return
            await asyncio.sleep(0.01)
    raise AssertionError("history barrier never entered advisory wait")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["profile", "binding"])
@pytest.mark.parametrize("commit", [True, False])
async def test_snapshot_barrier_waits_for_uncommitted_canonical_writer(
    financial_pg_engine, source, commit
):
    with financial_pg_engine.begin() as connection:
        partner = seed_user(connection)
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
        if source == "profile":
            direct_binding(connection, partner, creator)
        else:
            connection.execute(
                text(
                    "UPDATE blogger_profiles SET confirmed=true WHERE "
                    "user_id=:id"
                ),
                {"id": creator},
            )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine)
    service = await history_service(engine)
    try:
        async with factory() as writer, factory() as reader:
            await writer.begin()
            await reader.begin()
            if source == "profile":
                await writer.execute(
                    text(
                        "UPDATE blogger_profiles SET confirmed=true WHERE "
                        "user_id=:id"
                    ),
                    {"id": creator},
                )
            else:
                await writer.execute(
                    text(
                        "INSERT INTO user_referral_bindings "
                        "(referrer_user_id,referred_user_id,created_at) VALUES "
                        "(:partner,:creator,clock_timestamp())"
                    ),
                    {"partner": partner, "creator": creator},
                )
            payment_at = await reader.scalar(text("SELECT clock_timestamp()"))
            reader_pid = await reader.scalar(text("SELECT pg_backend_pid()"))
            waiting = asyncio.create_task(
                service.acquire_snapshot_barrier(session=reader)
            )
            try:
                await wait_for_advisory_waiter(engine, reader_pid, waiting)
                if commit:
                    await writer.commit()
                else:
                    await writer.rollback()
                await asyncio.wait_for(waiting, timeout=3)
                count = await service.count_verified_direct_creators(
                    partner, payment_at, session=reader
                )
                assert count.verified_count == (1 if commit else 0)
            finally:
                if not waiting.done():
                    waiting.cancel()
                    await asyncio.gather(waiting, return_exceptions=True)
            await reader.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_shared_snapshot_readers_coexist_and_block_later_writer(
    financial_pg_engine,
):
    with financial_pg_engine.begin() as connection:
        creator = seed_profile(
            connection, confirmed=False, stable_id=str(uuid4())
        )
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine)
    service = await history_service(engine)
    try:
        async with factory() as first, factory() as second, factory() as writer:
            for session in (first, second, writer):
                await session.begin()
            await service.acquire_snapshot_barrier(session=first)
            await asyncio.wait_for(
                service.acquire_snapshot_barrier(session=second), timeout=1
            )
            pid = await writer.scalar(text("SELECT pg_backend_pid()"))
            blocked = asyncio.create_task(
                writer.execute(
                    text(
                        "UPDATE blogger_profiles SET confirmed=true WHERE "
                        "user_id=:id"
                    ),
                    {"id": creator},
                )
            )
            try:
                await wait_for_advisory_waiter(engine, pid, blocked)
                await first.rollback()
                assert not blocked.done()
                await second.rollback()
                await asyncio.wait_for(blocked, timeout=3)
                await writer.commit()
            finally:
                if not blocked.done():
                    blocked.cancel()
                    await asyncio.gather(blocked, return_exceptions=True)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_api_and_direct_insert_have_compatible_lock_order(
    financial_pg_engine,
):
    from tests.postgres_financial.test_creator_social import profile_values
    from ugc_bot.domain.entities import BloggerProfile
    from ugc_bot.infrastructure.db.models import BloggerProfileModel
    from ugc_bot.infrastructure.db.repositories.profiles import (
        SqlAlchemyBloggerProfileRepository,
    )

    with financial_pg_engine.begin() as connection:
        creator = seed_user(connection)
    engine = create_async_engine(financial_pg_engine.url)
    factory = async_sessionmaker(engine)
    repo = SqlAlchemyBloggerProfileRepository(factory)
    service = await history_service(engine)
    try:
        async with factory() as direct, factory() as api:
            await direct.begin()
            await api.begin()
            # Shared readers exclude writers until their transaction ends.
            await service.acquire_snapshot_barrier(session=direct)
            pid = await api.scalar(text("SELECT pg_backend_pid()"))
            values = profile_values(creator, stable_id=str(uuid4()))
            values.pop("topics")
            profile = BloggerProfile(
                **values,
                topics={},
                updated_at=await direct.scalar(
                    text("SELECT clock_timestamp()")
                ),
            )
            blocked = asyncio.create_task(repo.save(profile, session=api))
            try:
                await wait_for_advisory_waiter(engine, pid, blocked)
                # Upgrading our shared lock is safe: the API writer only holds
                # a compatible user NO KEY UPDATE lock, never a profile row.
                await asyncio.wait_for(
                    direct.execute(
                        BloggerProfileModel.__table__.insert().values(
                            **profile_values(
                                creator, stable_id=profile.instagram_user_id
                            )
                        )
                    ),
                    timeout=3,
                )
                await direct.commit()
                await asyncio.wait_for(blocked, timeout=3)
                await api.commit()
            finally:
                if not blocked.done():
                    blocked.cancel()
                    await asyncio.gather(blocked, return_exceptions=True)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_barrier_requires_active_caller_transaction(
    financial_pg_engine,
):
    engine = create_async_engine(financial_pg_engine.url)
    service = await history_service(engine)
    try:
        with pytest.raises(ValueError, match="transaction"):
            await service.acquire_snapshot_barrier(session=None)
        async with async_sessionmaker(engine)() as session:
            with pytest.raises(ValueError, match="transaction"):
                await service.acquire_snapshot_barrier(session=session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_barrier_rejects_stale_repeatable_read_snapshot(
    financial_pg_engine,
):
    engine = create_async_engine(
        financial_pg_engine.url, isolation_level="REPEATABLE READ"
    )
    service = await history_service(engine)
    try:
        async with async_sessionmaker(engine)() as session:
            await session.begin()
            with pytest.raises(ValueError, match="read_committed"):
                await service.acquire_snapshot_barrier(session=session)
    finally:
        await engine.dispose()
