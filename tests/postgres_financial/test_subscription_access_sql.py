"""Paid quotas are enforced from actual submitted and delivered campaigns."""

import importlib
import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_campaign_foundation import (
    campaign_env as foundation_env,
)
from tests.postgres_financial.test_campaign_foundation import (
    command,
    execute,
)
from tests.postgres_financial.test_campaign_runtime import approved, proof
from ugc_bot.application.services.subscription_campaign_access import (
    SubscriptionCampaignAccess,
)
from ugc_bot.application.services.subscription_service import (
    SubscriptionService,
)
from ugc_bot.domain.campaign_moderation import ReviewCampaign, SubmitCampaign
from ugc_bot.domain.campaign_review import SaveCampaignDraft
from ugc_bot.infrastructure.db.repositories.subscription_campaign_usage import (
    SqlAlchemySubscriptionCampaignUsage,
)
from ugc_bot.infrastructure.db.repositories.subscriptions import (
    SqlAlchemySubscriptionRepository,
)


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated PostgreSQL test database is required")
    with isolated_financial_database(
        url, target_revision="0110_commercial_completion"
    ) as engine:
        yield engine


@pytest_asyncio.fixture
async def campaign_env(financial_pg_engine):
    async for value in foundation_env.__wrapped__(financial_pg_engine):
        yield value


def test_empty_commercial_migration_round_trip(financial_pg_engine):
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0110_commercial_completion"
    )
    with (
        financial_pg_engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
        migration.upgrade()


async def another_campaign(env, services, first):
    container = env["container"]
    async with container.transaction_manager.transaction() as db:
        draft = await container.build_bot_services()[
            "campaign_review_service"
        ].save_draft(
            SaveCampaignDraft.parse(
                first.actor_id,
                dict(
                    operation_key=str(uuid4()),
                    expected_version=0,
                    policy_version=first.policy_version,
                    terms_hash=first.terms_hash,
                    content=dict(
                        title="Second actual test campaign",
                        text="Synthetic invitation",
                    ),
                    segment={},
                ),
            ),
            session=db,
        )
    submit = SubmitCampaign(
        first.actor_id,
        str(uuid4()),
        UUID(draft["campaign_id"]),
        draft["version"],
        draft["revision_digest"],
        first.policy_version,
        first.terms_hash,
    )
    async with container.transaction_manager.transaction() as db:
        submitted = await services["campaign_submission_service"].submit(
            submit, principal=proof(env, "owner"), session=db
        )
    async with container.transaction_manager.transaction() as db:
        detail = await services["campaign_moderation_service"].review_detail(
            env["users"]["admin"].user_id,
            UUID(submitted["submission_id"]),
            principal=proof(env, "admin"),
            session=db,
        )
    async with container.transaction_manager.transaction() as db:
        await services["campaign_moderation_service"].decide(
            ReviewCampaign(
                env["users"]["admin"].user_id,
                str(uuid4()),
                submit.campaign_id,
                UUID(submitted["submission_id"]),
                submitted["version"],
                submit.revision_digest,
                detail["review_context"],
                "approve",
                "Synthetic moderation",
            ),
            principal=proof(env, "admin"),
            session=db,
        )


@pytest.mark.asyncio
async def test_actual_paid_use_opens_gate_and_owner_usage_controls_both_quotas(
    campaign_env,
):
    env = campaign_env
    paid_start = env["clock"].now()
    services, transport, first = await approved(env)
    for role in ("creator", "foreign"):
        await execute(
            env,
            command(
                env,
                "grant",
                owner_id=str(env["users"][role].user_id),
                reason="Synthetic paid pilot publisher",
            ),
        )
    repo, usage = (
        SqlAlchemySubscriptionRepository(),
        SqlAlchemySubscriptionCampaignUsage(),
    )
    subscriptions = SubscriptionService(
        repo, env["container"].transaction_manager, env["clock"]
    )
    await subscriptions.execute(
        env["users"]["admin"].user_id,
        "publish",
        "tariff",
        dict(
            version="paid-v1",
            title="Actual synthetic quota",
            price_minor=10000,
            duration_days=30,
            campaign_limit=1,
            recipient_limit=1,
            terms_reference="terms:quota",
            reason="Reviewed synthetic fixture",
        ),
        principal=proof(env, "admin"),
    )
    assert (
        await subscriptions.view(
            env["users"]["admin"].user_id, principal=proof(env, "admin")
        )
    )["paid_pilot_managers"] == 0
    for role in ("owner", "creator", "foreign"):
        await subscriptions.execute(
            env["users"]["admin"].user_id,
            "accept_payment",
            "payment:" + role,
            dict(
                member_id=str(env["users"][role].user_id),
                tariff_version="paid-v1",
                amount_minor=10000,
                currency="RUB",
                paid_at=env["clock"].now().isoformat(),
                payment_reference="synthetic-bank:" + role,
                evidence_reference="synthetic-paid-pilot",
                evidence_hash="a" * 64,
                reason="Reviewed manual receipt",
                pilot=True,
            ),
            principal=proof(env, "admin"),
        )
    assert await services["campaign_delivery_service"].run_once() == 1
    # The published test campaign policy requires 10,000 seconds between
    # invitations. Respect it while remaining in the same paid month.
    env["clock"].at += timedelta(seconds=10001)
    await another_campaign(env, services, first)
    assert await services["campaign_delivery_service"].run_once() == 1
    assert len(transport.calls) == 2
    gate = await subscriptions.execute(
        env["users"]["admin"].user_id,
        "enable_automation",
        "enable",
        dict(
            reason="Three actual paid pilots with repeated use",
            evidence_reference="synthetic-pilot-report",
            evidence_hash="b" * 64,
        ),
        principal=proof(env, "admin"),
    )
    assert gate["paid_pilot_managers"] == 3 and len(gate["reuse_evidence"]) == 2
    access = SubscriptionCampaignAccess(repo, usage)
    async with env["container"].transaction_manager.transaction() as db:
        assert await usage.usage(first.actor_id, paid_start, session=db) == (
            2,
            2,
        )
        for action in ("submit", "send"):
            with pytest.raises(PermissionError, match="quota_exceeded"):
                await access.require_access(
                    first.actor_id,
                    action=action,
                    at=env["clock"].now(),
                    session=db,
                )
            await access.require_access(
                env["users"]["foreign"].user_id,
                action=action,
                at=env["clock"].now(),
                session=db,
            )
        assert await usage.usage(
            first.actor_id, env["clock"].now() + timedelta(days=30), session=db
        ) == (0, 0)
    env["clock"].at += timedelta(seconds=10001)
    # A previously admitted job must still meet the paid gate at dispatch.
    await another_campaign(env, services, first)
    services["campaign_delivery_service"].access = access
    assert await services["campaign_delivery_service"].run_once() == 0
    assert len(transport.calls) == 2
    services["campaign_submission_service"].access = access
    with pytest.raises(PermissionError, match="quota_exceeded"):
        await another_campaign(env, services, first)
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0110_commercial_completion"
    )
    with (
        pytest.raises(RuntimeError, match="subscription_history_exists"),
        env["pg"].begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
