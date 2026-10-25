"""Automation pilot reuse is proved by actual accepted campaign outcomes."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from tests.helpers.factories import create_test_user
from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_campaign_foundation import command, execute
from tests.postgres_financial.test_campaign_runtime import approved, proof
from tests.postgres_financial.test_campaign_runtime import (
    campaign_env as runtime_env,
)
from ugc_bot.application.services.subscription_service import (
    SubscriptionService,
)
from ugc_bot.domain.campaign_moderation import ReviewCampaign, SubmitCampaign
from ugc_bot.domain.campaign_review import SaveCampaignDraft
from ugc_bot.infrastructure.db.repositories.subscriptions import (
    SqlAlchemySubscriptionRepository,
)


@pytest.fixture(scope="module")
def financial_pg_engine():
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="0110_commercial_completion",
    ) as engine:
        yield engine


@pytest_asyncio.fixture
async def campaign_env(financial_pg_engine):
    async for value in runtime_env.__wrapped__(financial_pg_engine):
        yield value


async def next_campaign(env, services, original):
    env["clock"].at += timedelta(seconds=10001)
    async with env["container"].transaction_manager.transaction() as db:
        draft = (
            await env["container"]
            .build_bot_services()["campaign_review_service"]
            .save_draft(
                SaveCampaignDraft.parse(
                    original.actor_id,
                    {
                        "operation_key": str(uuid4()),
                        "expected_version": 0,
                        "policy_version": original.policy_version,
                        "terms_hash": original.terms_hash,
                        "content": {
                            "title": "Synthetic repeat use",
                            "text": "Synthetic opted-in invitation",
                        },
                        "segment": {},
                    },
                ),
                session=db,
            )
        )
    cmd = SubmitCampaign(
        original.actor_id,
        str(uuid4()),
        UUID(draft["campaign_id"]),
        draft["version"],
        draft["revision_digest"],
        original.policy_version,
        original.terms_hash,
    )
    async with env["container"].transaction_manager.transaction() as db:
        submitted = await services["campaign_submission_service"].submit(
            cmd, principal=proof(env, "owner"), session=db
        )
    async with env["container"].transaction_manager.transaction() as db:
        review = await services["campaign_moderation_service"].review_detail(
            env["users"]["admin"].user_id,
            UUID(submitted["submission_id"]),
            principal=proof(env, "admin"),
            session=db,
        )
    decision = ReviewCampaign(
        env["users"]["admin"].user_id,
        str(uuid4()),
        cmd.campaign_id,
        UUID(submitted["submission_id"]),
        submitted["version"],
        cmd.revision_digest,
        review["review_context"],
        "approve",
        "Synthetic approved repeat",
    )
    async with env["container"].transaction_manager.transaction() as db:
        await services["campaign_moderation_service"].decide(
            decision, principal=proof(env, "admin"), session=db
        )
    return cmd


@pytest.mark.asyncio
async def test_paid_pilots_require_two_accepted_campaigns_and_freeze_provenance(
    campaign_env,
):
    env = campaign_env
    services, transport, original = await approved(env)
    worker = services["campaign_delivery_service"]
    assert (
        await worker.run_once() == 1
    )  # Before pilot payment: never counts as paid reuse.
    env["clock"].at += timedelta(seconds=1)
    subscriptions = SubscriptionService(
        SqlAlchemySubscriptionRepository(),
        env["container"].transaction_manager,
        env["clock"],
    )
    tariff = {
        "version": "synthetic-pilot-tariff",
        "title": "Synthetic manual pilot",
        "price_minor": 10000,
        "duration_days": 30,
        "campaign_limit": 100,
        "recipient_limit": 100,
        "terms_reference": "synthetic:terms",
        "reason": "Synthetic published tariff",
    }
    admin = env["users"]["admin"].user_id
    await subscriptions.execute(
        admin, "publish", "tariff", tariff, principal=proof(env, "admin")
    )
    env["users"]["pilot3"] = await create_test_user(
        env["container"].build_repos()["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
    )
    for index, role in enumerate(("owner", "foreign", "pilot3")):
        if role != "owner":
            await execute(
                env,
                command(
                    env,
                    "grant",
                    owner_id=str(env["users"][role].user_id),
                    reason="Synthetic pilot publisher",
                ),
            )
        payload = {
            "member_id": str(env["users"][role].user_id),
            "tariff_version": tariff["version"],
            "amount_minor": 10000,
            "currency": "RUB",
            "paid_at": env["clock"].at.isoformat(),
            "payment_reference": f"synthetic-paid:{index}",
            "evidence_reference": "synthetic:not-real-receipt",
            "evidence_hash": "a" * 64,
            "reason": "Synthetic actual receipt fixture",
            "pilot": True,
        }
        await subscriptions.execute(
            admin,
            "accept_payment",
            f"pay:{index}",
            payload,
            principal=proof(env, "admin"),
        )
    payload = payload | {
        "member_id": str(original.actor_id),
        "payment_reference": "synthetic-renewal",
    }
    await subscriptions.execute(
        admin,
        "accept_payment",
        "renewal",
        payload,
        principal=proof(env, "admin"),
    )
    gate = {
        "reason": "Synthetic pilot gate review",
        "evidence_reference": "synthetic:review",
        "evidence_hash": "b" * 64,
    }
    with pytest.raises(ValueError, match="actual_paid_reuse"):
        await subscriptions.execute(
            admin,
            "enable_automation",
            "renewal-is-not-use",
            gate,
            principal=proof(env, "admin"),
        )
    env["clock"].at += timedelta(seconds=1)
    second = await next_campaign(env, services, original)
    assert await worker.run_once() == 1
    with pytest.raises(ValueError, match="actual_paid_reuse"):
        await subscriptions.execute(
            admin,
            "enable_automation",
            "one-campaign",
            gate,
            principal=proof(env, "admin"),
        )
    third = await next_campaign(env, services, original)
    transport.fail = True
    assert await worker.run_once() == 1
    with pytest.raises(ValueError, match="actual_paid_reuse"):
        await subscriptions.execute(
            admin,
            "enable_automation",
            "unknown-not-accepted",
            gate,
            principal=proof(env, "admin"),
        )
    transport.fail = False
    fourth = await next_campaign(env, services, original)
    assert await worker.run_once() == 1
    receipt = await subscriptions.execute(
        admin,
        "enable_automation",
        "actual-reuse",
        gate,
        principal=proof(env, "admin"),
    )
    evidence = receipt["reuse_evidence"]
    assert receipt["repeated_paid_use"] is True
    assert {row["campaign_id"] for row in evidence} == {
        str(second.campaign_id),
        str(fourth.campaign_id),
    }
    assert {row["member_id"] for row in evidence} == {str(original.actor_id)}
    assert all(UUID(row["outcome_id"]).int for row in evidence)
    assert str(original.campaign_id) not in str(evidence) and str(
        third.campaign_id
    ) not in str(evidence)
    assert (
        await subscriptions.execute(
            admin,
            "enable_automation",
            "actual-reuse",
            gate,
            principal=proof(env, "admin"),
        )
        == receipt
    )
