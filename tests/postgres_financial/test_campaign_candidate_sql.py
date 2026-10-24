"""Campaign eligibility does not depend on unrelated financial user columns."""

from decimal import Decimal

import pytest
from sqlalchemy import update

from tests.postgres_financial.test_campaign_drafts import (
    campaign_env as campaign_env,
)
from tests.postgres_financial.test_campaign_drafts import (
    configure,
    draft_command,
    preview,
    save,
)
from ugc_bot.infrastructure.db.models import UserModel

__all__ = ["campaign_env"]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["creator", "owner"])
async def test_valid_referral_rate_does_not_disable_campaign_preview(
    campaign_env, role
):
    env = campaign_env
    await configure(env)
    saved = await save(env, draft_command(env))
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"][role].user_id)
            .values(referral_payout_rate=Decimal("0.1250"))
        )
    result = await preview(env, saved)
    assert result["eligible_count"] == 1 and result["exclusions"] == {}
    async with env["container"].transaction_manager.transaction() as db:
        repository = env["container"].build_repos()["campaign_review_repo"]
        rows = [
            row
            async for row in repository.candidates(
                env["users"]["owner"].user_id, session=db
            )
        ]
    context = rows[0]["context"]
    assert set(context["actor"]) == {
        "user_id",
        "status",
        "telegram_id",
        "telegram_usable",
    }
    assert set(context["inviter"]) == {"user_id", "status"}
