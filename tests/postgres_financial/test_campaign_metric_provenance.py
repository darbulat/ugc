"""A real failed collection touch is not a successful campaign measurement."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import insert

from tests.postgres_financial.test_campaign_drafts import (
    campaign_env as _campaign_env,
)
from tests.postgres_financial.test_campaign_drafts import (
    configure,
    draft_command,
    preview,
    save,
)
from ugc_bot.application.services.instagram_stats_collector_service import (
    InstagramStatsCollectorService,
)
from ugc_bot.domain.entities import InstagramStats
from ugc_bot.infrastructure.db.social_models import SocialAccountModel

campaign_env = _campaign_env


@pytest.mark.asyncio
async def test_failed_collection_touch_never_refreshes_campaign_measurement(
    campaign_env,
):
    env = campaign_env
    await configure(env)
    saved = await save(env, draft_command(env, numeric=True))
    repos = env["container"].build_repos()
    creator = env["users"]["creator"].user_id
    profile = await repos["blogger_repo"].get_by_user_id(creator)
    before = datetime.now(timezone.utc) - timedelta(days=100)
    stats = repos["instagram_stats_repo"]
    await stats.save(
        InstagramStats(
            creator,
            {"real_fixture_measurement": 1234},
            before,
            followers_count=1234,
            instagram_id=profile.instagram_user_id,
            provider="synthetic-successful-old-provider",
        )
    )

    class ProfileScope:
        # Limit this public collector run to its own real SQL-backed fixture.
        async def list_confirmed_with_instagram_id(self, **kwargs):
            return [await repos["blogger_repo"].get_by_user_id(creator)]

    class OfflineFailure:
        async def get_profile_stats_with_provider(self, username):
            raise RuntimeError("synthetic offline collection failure")

    collector = InstagramStatsCollectorService(
        ProfileScope(),
        stats,
        OfflineFailure(),
        env["container"].transaction_manager,
        delay_seconds=0,
    )
    result = await collector.run_once()
    assert result.errors == 1 and result.updated == 0
    retained = await stats.get_by_user_id(creator)
    assert retained.followers_count == 1234 and retained.fetched_at > before
    assert retained.instagram_id == profile.instagram_user_id
    result = await preview(env, saved)
    assert result["eligible_count"] == 0 and result["exclusions"] == {
        "metric_unknown": 1
    }
    assert result["metric_capability"] == "successful_observation_unavailable"
    assert "metrics_fetched_at" not in str(
        result
    ) and "successful_observed_at" not in str(result)


@pytest.mark.asyncio
async def test_legacy_profile_social_projection_is_not_metric_proof(
    campaign_env,
):
    env = campaign_env
    await configure(env)
    saved = await save(env, draft_command(env, numeric=True))
    creator = env["users"]["creator"].user_id
    profile = (
        await env["container"]
        .build_repos()["blogger_repo"]
        .get_by_user_id(creator)
    )
    at = datetime.now(timezone.utc)
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            insert(SocialAccountModel).values(
                account_id=uuid4(),
                user_id=creator,
                platform="instagram",
                url=profile.instagram_url,
                handle="synthetic",
                verified=True,
                external_id=profile.instagram_user_id,
                work_format="ugc_only",
                followers_count=999999,
                metrics_source="legacy_profile",
                metrics_fetched_at=at,
                created_at=at,
                updated_at=at,
                verification_observed_at=at,
                verification_source="manual_code",
            )
        )
    result = await preview(env, saved)
    assert result["eligible_count"] == 0 and result["exclusions"] == {
        "metric_unknown": 1
    }
