"""Consent binds the inviter actually displayed, not a later eligible owner."""

import pytest
from sqlalchemy import select, update

from tests.postgres_financial.test_campaign_foundation import (
    campaign_env as _campaign_env,
)
from tests.postgres_financial.test_campaign_foundation import (
    command,
    execute,
    ready,
    view,
)
from ugc_bot.domain.campaigns import CampaignConflict
from ugc_bot.infrastructure.db.campaign_models import CONSENTS
from ugc_bot.infrastructure.db.models import UserReferralBindingModel

campaign_env = _campaign_env


@pytest.mark.asyncio
@pytest.mark.parametrize("round_trip", [False, True])
@pytest.mark.parametrize("committed_before_switch", [False, True])
async def test_allow_rejects_inviter_changed_after_settings_before_command(
    campaign_env, round_trip, committed_before_switch
):
    env = campaign_env
    publication = await ready(env)
    seen = await view(env)
    payload = {
        "policy_version": publication["version"],
        "terms_hash": seen["policy"]["terms_hash"],
    }
    payload["consent_context"] = seen["consent_context"]
    intent = command(env, "consent", role="creator", **payload)
    if committed_before_switch:
        receipt = await execute(env, intent)
        assert receipt["consent_context"] == seen["consent_context"]
    await execute(
        env,
        command(
            env,
            "grant",
            owner_id=str(env["users"]["foreign"].user_id),
            reason="Another eligible publisher",
        ),
    )
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserReferralBindingModel)
            .where(
                UserReferralBindingModel.referred_user_id
                == env["users"]["creator"].user_id
            )
            .values(referrer_user_id=env["users"]["foreign"].user_id)
        )
        if round_trip:
            await db.execute(
                update(UserReferralBindingModel)
                .where(
                    UserReferralBindingModel.referred_user_id
                    == env["users"]["creator"].user_id
                )
                .values(referrer_user_id=env["users"]["owner"].user_id)
            )
    with pytest.raises(CampaignConflict, match="consent_context_changed"):
        await execute(env, intent)
    async with env["container"].transaction_manager.transaction() as db:
        saved = (
            (
                await db.execute(
                    select(CONSENTS).where(
                        CONSENTS.c.creator_id == env["users"]["creator"].user_id
                    )
                )
            )
            .mappings()
            .all()
        )
        assert len(saved) == int(committed_before_switch)
        if saved:
            assert saved[0]["owner_id"] == env["users"]["owner"].user_id
    current = await view(env)
    assert current["consent_context"] != seen["consent_context"]
    replacement = command(
        env,
        "consent",
        role="creator",
        expected=int(committed_before_switch),
        policy_version=publication["version"],
        terms_hash=current["policy"]["terms_hash"],
        consent_context=current["consent_context"],
    )
    await execute(env, replacement)
    assert (await view(env))["consent"]["effective"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["pause", "blocked", "bot_blocked", "deleted"]
)
async def test_admin_exact_lookup_keeps_inactive_grant_holder_revocable(
    campaign_env, status
):
    from ugc_bot.infrastructure.db.models import UserModel

    env = campaign_env
    await ready(env)
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["owner"].user_id)
            .values(status=status)
        )
    service = env["container"].build_bot_services()["campaign_service"]
    async with env["container"].transaction_manager.transaction() as db:
        result = await service.accounts(
            env["users"]["admin"].user_id,
            str(env["users"]["owner"].user_id),
            0,
            session=db,
        )
    assert len(result["accounts"]) == 1
    account = result["accounts"][0]
    async with env["container"].transaction_manager.transaction() as db:
        listed = await service.accounts(
            env["users"]["admin"].user_id, "", 0, session=db
        )
    assert all(row["status"] == "active" for row in listed["accounts"])
    assert (
        account["status"] == status
        and account["can_revoke"]
        and not account["can_grant"]
    )
    with pytest.raises(CampaignConflict, match="active_owner"):
        await execute(
            env,
            command(
                env,
                "grant",
                expected=1,
                owner_id=str(env["users"]["owner"].user_id),
                reason="Inactive owner must not be granted",
            ),
        )
    await execute(
        env,
        command(
            env,
            "revoke",
            expected=1,
            owner_id=str(env["users"]["owner"].user_id),
            reason="Revoke retained grant while inactive",
        ),
    )
    assert not (await view(env, "owner"))["publisher"]["active"]
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["owner"].user_id)
            .values(status="active")
        )
    assert not (await view(env, "owner"))["publisher"]["active"]
