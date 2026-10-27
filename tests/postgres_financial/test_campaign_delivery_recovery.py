"""Small published batches must progress without retrying ambiguous sends."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import insert, select, update

from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_campaign_runtime import (
    approved,
    proof,
)
from tests.postgres_financial.test_campaign_runtime import campaign_env as _env
from ugc_bot.domain.campaign_capacity import window_at
from ugc_bot.domain.campaign_moderation import SubmitCampaign
from ugc_bot.domain.campaign_review import SaveCampaignDraft
from ugc_bot.infrastructure.db.campaign_runtime_models import (
    ATTEMPTS,
    JOBS,
    OBSERVATIONS,
    OUTCOMES,
    STATES,
)
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    UserReferralBindingModel,
)


@pytest.fixture
def financial_pg_engine():
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="00f0_campaign_runtime",
    ) as engine:
        yield engine


@pytest_asyncio.fixture
async def campaign_env(financial_pg_engine):
    async for env in _env.__wrapped__(financial_pg_engine):
        yield env


async def add_creator(env):
    repos = env["container"].build_repos()
    user = await create_test_user(
        repos["user_repo"], external_id=str(uuid4().int % 10**12 + 1)
    )
    env["users"]["second_creator"] = user
    await create_test_blogger_profile(
        repos["blogger_repo"],
        user.user_id,
        instagram_url="https://instagram.com/synthetic_" + uuid4().hex,
    )
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == user.user_id)
            .values(
                confirmed=True, instagram_user_id="canonical-" + uuid4().hex
            )
        )
        await db.execute(
            insert(UserReferralBindingModel).values(
                referrer_user_id=env["users"]["owner"].user_id,
                referred_user_id=user.user_id,
            )
        )


async def report(env, services, submit):
    async with env["container"].transaction_manager.transaction() as db:
        return await services["campaign_response_service"].report(
            env["users"]["owner"].user_id,
            submit.campaign_id,
            principal=proof(env, "owner"),
            session=db,
        )


async def submit_another(env, services, original):
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
                            "title": "Synthetic task",
                            "text": "Another task",
                        },
                        "segment": {},
                    },
                ),
                session=db,
            )
        )
    command = SubmitCampaign(
        original.actor_id,
        str(uuid4()),
        UUID(draft["campaign_id"]),
        draft["version"],
        draft["revision_digest"],
        original.policy_version,
        original.terms_hash,
    )
    async with env["container"].transaction_manager.transaction() as db:
        await services["campaign_submission_service"].submit(
            command, principal=proof(env, "owner"), session=db
        )


@pytest.mark.asyncio
async def test_live_first_attempt_does_not_starve_later_queued_recipient(
    campaign_env,
):
    env = campaign_env
    await add_creator(env)
    services, transport, submit = await approved(
        env,
        limits={"claim_batch_size": 1},
        recipients=("creator", "second_creator"),
    )
    worker = services["campaign_delivery_service"]
    async with env["container"].transaction_manager.transaction() as db:
        first = (
            await worker.repository.pending(env["clock"].now(), 1, session=db)
        )[0]
    async with env["container"].transaction_manager.transaction() as db:
        attempt = await worker.repository.prepare(
            first, env["clock"].now(), access=None, session=db
        )
    assert attempt is not None

    assert await worker.run_once() == 1
    assert len(transport.calls) == 1 and transport.calls[0].job_id != first
    assert (await report(env, services, submit))["delivery"] == {
        "preparing": 1,
        "accepted": 1,
    }
    env["clock"].at += timedelta(seconds=121)
    assert await worker.run_once() == 0
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_window_expiry_settles_reservations_before_starting_queued_work(
    campaign_env,
):
    env = campaign_env
    await add_creator(env)
    services, transport, submit = await approved(
        env,
        limits={"claim_batch_size": 1, "window_seconds": 60},
        recipients=("creator", "second_creator"),
    )
    worker = services["campaign_delivery_service"]
    env["clock"].at = window_at(env["clock"].now(), 60).end

    assert await worker.run_once() == 1
    assert (await report(env, services, submit))["delivery"] == {
        "queued": 1,
        "accepted": 1,
    }
    assert await worker.run_once() == 1
    assert len(transport.calls) == 2
    assert (await report(env, services, submit))["delivery"] == {"accepted": 2}
    async with env["container"].transaction_manager.transaction() as db:
        attempts = await db.scalars(
            select(ATTEMPTS.c.attempt_id)
            .join(JOBS, JOBS.c.job_id == ATTEMPTS.c.job_id)
            .where(JOBS.c.campaign_id == submit.campaign_id)
        )
        assert len(tuple(attempts)) == 2


@pytest.mark.asyncio
async def test_bounded_expiry_settlement_defers_valid_job_until_next_pass(
    campaign_env,
):
    env = campaign_env
    services, transport, submit = await approved(
        env, limits={"claim_batch_size": 1, "review_ttl_seconds": 1}
    )
    await submit_another(env, services, submit)
    await submit_another(env, services, submit)
    env["clock"].at += timedelta(seconds=1)
    worker = services["campaign_delivery_service"]

    assert await worker.run_once() == 0
    assert not transport.calls
    assert (await report(env, services, submit))["delivery"] == {"queued": 1}
    async with env["container"].transaction_manager.transaction() as db:
        expired = await db.scalars(
            select(STATES.c.campaign_id).where(STATES.c.state == "expired")
        )
        assert len(tuple(expired)) == 1

    assert await worker.run_once() == 1
    assert len(transport.calls) == 1
    assert (await report(env, services, submit))["delivery"] == {"accepted": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_result_time", [False, True])
async def test_late_provider_acceptance_without_recovery_preserves_unknown(
    campaign_env, stale_result_time
):
    env = campaign_env
    services, transport, submit = await approved(env)
    repo = services["campaign_delivery_service"].repository
    async with env["container"].transaction_manager.transaction() as db:
        job = await db.scalar(
            select(JOBS.c.job_id).where(
                JOBS.c.campaign_id == submit.campaign_id
            )
        )
    async with env["container"].transaction_manager.transaction() as db:
        attempt = await repo.prepare(
            job, env["clock"].now(), access=None, session=db
        )
    env["clock"].at = attempt.deadline
    async with env["container"].transaction_manager.transaction() as db:
        await repo.finish(
            attempt,
            "accepted",
            "synthetic:late-without-recovery",
            None,
            attempt.started_at if stale_result_time else env["clock"].now(),
            session=db,
        )

    assert (await report(env, services, submit))["delivery"] == {"unknown": 1}
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await db.scalar(
                select(OUTCOMES.c.provider_reference).where(
                    OUTCOMES.c.job_id == job
                )
            )
            is None
        )
        assert (
            await db.scalar(
                select(OBSERVATIONS.c.provider_reference).where(
                    OBSERVATIONS.c.job_id == job
                )
            )
            == "synthetic:late-without-recovery"
        )
    assert not transport.calls
