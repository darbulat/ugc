"""Real persisted own draft revisions and authoritative read-only previews."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from tests.postgres_financial.test_campaign_foundation import (
    campaign_env as _campaign_env,
)
from tests.postgres_financial.test_campaign_foundation import (
    command,
    execute,
    ready,
    view,
)
from ugc_bot.domain.campaign_review import SaveCampaignDraft
from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.infrastructure.db.models import UserReferralBindingModel

campaign_env = _campaign_env


def services(env):
    graph = env["container"].build_bot_services()
    return graph["campaign_review_service"], graph["campaign_audience_service"]


def draft_command(env, *, identifier=None, version=0, key=None, numeric=False):
    return SaveCampaignDraft.parse(
        env["users"]["owner"].user_id,
        {
            "operation_key": key or "synthetic-draft-" + uuid4().hex,
            "campaign_id": str(identifier) if identifier else None,
            "expected_version": version,
            "policy_version": env["publication"]["version"],
            "terms_hash": env["settings"]["policy"]["terms_hash"],
            "content": {"title": "Task", "text": "Brief"},
            "segment": {"social": {"platform": "instagram", "followers_min": 0}}
            if numeric
            else {},
        },
    )


async def configure(env):
    env["publication"] = await ready(env)
    env["settings"] = await view(env)
    consent = command(
        env,
        "consent",
        role="creator",
        policy_version=env["publication"]["version"],
        terms_hash=env["settings"]["policy"]["terms_hash"],
        consent_context=env["settings"]["consent_context"],
    )
    await execute(env, consent)
    return consent


async def save(env, command):
    service, _ = services(env)
    async with env["container"].transaction_manager.transaction() as db:
        return await service.save_draft(command, session=db)


async def preview(env, saved):
    _, audience = services(env)
    async with env["container"].transaction_manager.transaction() as db:
        return await audience.preview(
            env["users"]["owner"].user_id,
            UUID(saved["campaign_id"]),
            saved["revision_digest"],
            session=db,
        )


@pytest.mark.asyncio
async def test_actual_draft_replay_retains_all_revisions_and_own_scope(
    campaign_env,
):
    from ugc_bot.infrastructure.db.campaign_review_models import REVISIONS

    env = campaign_env
    await configure(env)
    first_command = draft_command(env)
    first = await save(env, first_command)
    assert (await save(env, first_command))["revision_digest"] == first[
        "revision_digest"
    ]
    second = await save(
        env, draft_command(env, identifier=first["campaign_id"], version=1)
    )
    assert second["version"] == 2
    assert (await save(env, first_command))["is_current"] is False
    service, _ = services(env)
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(REVISIONS)
                .where(REVISIONS.c.campaign_id == UUID(first["campaign_id"]))
            )
            == 2
        )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(LookupError):
            await service.detail(
                env["users"]["foreign"].user_id,
                UUID(first["campaign_id"]),
                session=db,
            )
    result = await preview(env, second)
    assert result["eligible_count"] == 1 and result["exclusions"] == {}
    assert "telegram_id" not in str(result) and "phone" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("same_transaction", [False, True])
async def test_binding_round_trip_invalidates_settings_and_preview(
    campaign_env, same_transaction
):
    env = campaign_env
    original = await configure(env)
    saved = await save(env, draft_command(env))
    container = env["container"]
    creator = env["users"]["creator"].user_id
    async with container.transaction_manager.transaction() as db:
        await db.execute(
            update(UserReferralBindingModel)
            .where(UserReferralBindingModel.referred_user_id == creator)
            .values(referrer_user_id=env["users"]["foreign"].user_id)
        )
        if same_transaction:
            await db.execute(
                update(UserReferralBindingModel)
                .where(UserReferralBindingModel.referred_user_id == creator)
                .values(referrer_user_id=env["users"]["owner"].user_id)
            )
    if not same_transaction:
        async with container.transaction_manager.transaction() as db:
            await db.execute(
                update(UserReferralBindingModel)
                .where(UserReferralBindingModel.referred_user_id == creator)
                .values(referrer_user_id=env["users"]["owner"].user_id)
            )
    settings = await view(env)
    assert not settings["consent"]["effective"] and settings["can_consent"]
    assert (await preview(env, saved))["exclusions"] == {
        "consent_binding_changed": 1
    }
    with pytest.raises(CampaignConflict, match="context_changed"):
        await execute(env, original)
    await execute(
        env,
        command(
            env,
            "consent",
            role="creator",
            expected=1,
            policy_version=env["publication"]["version"],
            terms_hash=settings["policy"]["terms_hash"],
            consent_context=settings["consent_context"],
        ),
    )
    assert (await preview(env, saved))["eligible_count"] == 1


@pytest.mark.asyncio
async def test_concurrent_draft_edits_one_wins_and_rollback_keeps_no_facts(
    campaign_env,
):
    import asyncio

    from ugc_bot.container import Container
    from ugc_bot.infrastructure.db.campaign_review_models import (
        COMMANDS,
        REVISIONS,
    )

    env = campaign_env
    await configure(env)
    initial = await save(env, draft_command(env))
    independent = Container(env["container"]._config)
    other = {**env, "container": independent}
    try:
        results = await asyncio.gather(
            save(
                env,
                draft_command(
                    env, identifier=initial["campaign_id"], version=1
                ),
            ),
            save(
                other,
                draft_command(
                    other, identifier=initial["campaign_id"], version=1
                ),
            ),
            return_exceptions=True,
        )
    finally:
        await independent.session_factory.kw["bind"].dispose()
    assert sum(isinstance(result, CampaignConflict) for result in results) == 1
    assert (
        sum(
            isinstance(result, dict) and result["version"] == 2
            for result in results
        )
        == 1
    )
    command_to_rollback = draft_command(env)
    service, _ = services(env)
    with pytest.raises(RuntimeError, match="synthetic rollback"):
        async with env["container"].transaction_manager.transaction() as db:
            await service.save_draft(command_to_rollback, session=db)
            raise RuntimeError("synthetic rollback")
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(COMMANDS)
                .where(
                    COMMANDS.c.actor_id == command_to_rollback.actor_id,
                    COMMANDS.c.operation_key
                    == command_to_rollback.operation_key,
                )
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(REVISIONS)
                .where(REVISIONS.c.campaign_id == UUID(initial["campaign_id"]))
            )
            == 2
        )


@pytest.mark.asyncio
async def test_actual_read_snapshot_and_all_draft_facts_are_immutable(
    campaign_env,
):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from ugc_bot.infrastructure.db.campaign_review_models import TABLES

    env = campaign_env
    await configure(env)
    saved = await save(env, draft_command(env))
    service, _ = services(env)
    async with env["container"].transaction_manager.transaction() as db:
        await service.detail(
            env["users"]["owner"].user_id,
            UUID(saved["campaign_id"]),
            session=db,
        )
        assert await db.scalar(text("SHOW transaction_read_only")) == "on"
        assert (
            await db.scalar(text("SHOW transaction_isolation"))
            == "repeatable read"
        )
    for table in TABLES:
        for verb in ("DELETE FROM", "TRUNCATE"):
            with pytest.raises(DBAPIError, match="campaign_fact_immutable"):
                async with env[
                    "container"
                ].transaction_manager.transaction() as db:
                    suffix = " CASCADE" if verb == "TRUNCATE" else ""
                    await db.execute(text(f"{verb} {table.name}{suffix}"))
        with pytest.raises(DBAPIError, match="campaign_fact_immutable"):
            async with env["container"].transaction_manager.transaction() as db:
                column = next(iter(table.c)).name
                await db.execute(
                    text(f"UPDATE {table.name} SET {column}={column}")
                )


@pytest.mark.asyncio
async def test_current_grant_loss_blocks_replay_but_not_own_history(
    campaign_env,
):
    env = campaign_env
    await configure(env)
    intent = draft_command(env)
    saved = await save(env, intent)
    await execute(
        env,
        command(
            env,
            "revoke",
            expected=1,
            owner_id=str(env["users"]["owner"].user_id),
            reason="Synthetic current grant loss",
        ),
    )
    with pytest.raises(PermissionError, match="current_publisher"):
        await save(env, intent)
    with pytest.raises(PermissionError, match="current_publisher"):
        await preview(env, saved)
    service, _ = services(env)
    async with env["container"].transaction_manager.transaction() as db:
        result = await service.detail(
            env["users"]["owner"].user_id,
            UUID(saved["campaign_id"]),
            session=db,
        )
        assert result["version"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("consented", [False, True])
async def test_identical_binding_witness_neither_revokes_nor_creates_consent(
    campaign_env, consented
):
    from sqlalchemy import insert

    from ugc_bot.infrastructure.db.identity_history_models import (
        BINDING_OBSERVATIONS,
    )

    env = campaign_env
    if consented:
        await configure(env)
    else:
        env["publication"] = await ready(env)
        env["settings"] = await view(env)
    saved = await save(env, draft_command(env))
    before = await view(env)
    async with env["container"].transaction_manager.transaction() as db:
        original = dict(
            (
                await db.execute(
                    select(BINDING_OBSERVATIONS).where(
                        BINDING_OBSERVATIONS.c.referred_user_id
                        == env["users"]["creator"].user_id
                    )
                )
            )
            .mappings()
            .one()
        )
        # Immutable duplicate witnesses may predate epoch normalization.
        # Their different sequence must neither fabricate nor destroy intent.
        del original["observation_sequence"]
        original["business_key"] = "synthetic-identical-witness-" + uuid4().hex
        await db.execute(insert(BINDING_OBSERVATIONS).values(**original))
        await db.execute(
            update(UserReferralBindingModel)
            .where(
                UserReferralBindingModel.referred_user_id
                == env["users"]["creator"].user_id
            )
            .values(referrer_user_id=env["users"]["owner"].user_id)
        )
    after = await view(env)
    assert after["consent_context"] == before["consent_context"]
    assert after["consent"]["effective"] is consented
    result = await preview(env, saved)
    assert result["eligible_count"] == int(consented)
    assert result["exclusions"] == ({} if consented else {"consent_absent": 1})


@pytest.mark.asyncio
async def test_draft_waits_for_current_grant_revocation_and_refreshes(
    campaign_env,
):
    import asyncio

    from ugc_bot.container import Container

    env = campaign_env
    await configure(env)
    independent = Container(env["container"]._config)
    other = {**env, "container": independent}
    service = env["container"].build_bot_services()["campaign_service"]
    pending = None
    try:
        async with env["container"].transaction_manager.transaction() as db:
            await service.execute(
                command(
                    env,
                    "revoke",
                    expected=1,
                    owner_id=str(env["users"]["owner"].user_id),
                    reason="Synthetic pending grant revocation",
                ),
                session=db,
            )
            pending = asyncio.create_task(save(other, draft_command(other)))
            await asyncio.sleep(0.05)
            assert not pending.done()
        with pytest.raises(PermissionError, match="current_publisher"):
            await pending
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await independent.session_factory.kw["bind"].dispose()
