"""Real SQL submission/review/outbox with synthetic transport only."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_campaign_foundation import (
    campaign_env as foundation_env,
)
from tests.postgres_financial.test_campaign_foundation import (
    command,
    execute,
    policy_payload,
    view,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.domain.campaign_moderation import ReviewCampaign, SubmitCampaign
from ugc_bot.domain.campaign_review import SaveCampaignDraft


@pytest_asyncio.fixture
async def campaign_env(financial_pg_engine):
    async for value in foundation_env.__wrapped__(financial_pg_engine):
        yield value


@pytest.fixture(scope="module")
def financial_pg_engine():
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="00f0_campaign_runtime",
    ) as engine:
        yield engine


def proof(env, role):
    user = env["users"][role]
    return AuthenticatedMessengerPrincipal(
        user.user_id, "telegram", user.telegram_id
    )


class Transport:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def send(self, attempt):
        self.calls.append(attempt)
        if self.fail:
            raise DeliveryFailure("synthetic_unknown", uncertain=True)
        return DeliveryReceipt("telegram", "synthetic:" + str(attempt.job_id))


async def approved(env, *, limits=None, recipients=("creator",)):
    from ugc_bot.container.campaign_runtime_factory import (
        build_campaign_runtime,
    )

    payload = policy_payload()
    payload["limits"] = dict.fromkeys(payload["limits"], 10000)
    payload["limits"].update(limits or {})
    published = await execute(env, command(env, "publish", **payload))
    await execute(
        env,
        command(
            env,
            "grant",
            owner_id=str(env["users"]["owner"].user_id),
            reason="Synthetic approval",
        ),
    )
    for role in recipients:
        settings = await view(env, role=role)
        await execute(
            env,
            command(
                env,
                "consent",
                role=role,
                policy_version=published["version"],
                terms_hash=settings["policy"]["terms_hash"],
                consent_context=settings["consent_context"],
            ),
        )
    container, transport = env["container"], Transport()
    services = build_campaign_runtime(
        container._config,
        container.transaction_manager,
        miniapp_url="https://example.test/miniapp/app.html",
        clock=env["clock"],
        transport=transport,
        delivery_enabled=True,
    )
    async with container.transaction_manager.transaction() as db:
        draft = await container.build_bot_services()[
            "campaign_review_service"
        ].save_draft(
            SaveCampaignDraft.parse(
                env["users"]["owner"].user_id,
                {
                    "operation_key": str(uuid4()),
                    "expected_version": 0,
                    "policy_version": published["version"],
                    "terms_hash": settings["policy"]["terms_hash"],
                    "content": {
                        "title": "Synthetic task",
                        "text": "Synthetic creator invitation",
                    },
                    "segment": {},
                },
            ),
            session=db,
        )
    submit = SubmitCampaign(
        env["users"]["owner"].user_id,
        str(uuid4()),
        UUID(draft["campaign_id"]),
        draft["version"],
        draft["revision_digest"],
        published["version"],
        settings["policy"]["terms_hash"],
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
    decision = ReviewCampaign(
        env["users"]["admin"].user_id,
        str(uuid4()),
        submit.campaign_id,
        UUID(submitted["submission_id"]),
        submitted["version"],
        submit.revision_digest,
        detail["review_context"],
        "approve",
        "Synthetic moderation",
    )
    async with container.transaction_manager.transaction() as db:
        await services["campaign_moderation_service"].decide(
            decision, principal=proof(env, "admin"), session=db
        )
    return services, transport, submit


@pytest.mark.asyncio
async def test_real_submit_review_deliver_once_response_and_private_report(
    campaign_env,
):
    env = campaign_env
    services, transport, submit = await approved(env)
    worker = services["campaign_delivery_service"]
    assert await worker.run_once() == 1
    assert await worker.run_once() == 0 and len(transport.calls) == 1
    async with env["container"].transaction_manager.transaction() as db:
        result = await services["campaign_response_service"].respond(
            env["users"]["creator"].user_id,
            submit.campaign_id,
            "interested",
            0,
            "interested",
            principal=proof(env, "creator"),
            session=db,
        )
        assert result["version"] == 1
    async with env["container"].transaction_manager.transaction() as db:
        report = await services["campaign_response_service"].report(
            env["users"]["owner"].user_id,
            submit.campaign_id,
            principal=proof(env, "owner"),
            session=db,
        )
    assert report["delivery"] == {"accepted": 1}
    assert report["responses"] == {"interested": 1}
    assert "telegram_id" not in str(report) and "address" not in str(report)
    from ugc_bot.infrastructure.db.repositories import (
        subscription_campaign_usage,
    )

    # Keep production usage counting tied to actual SQL runtime events.
    from_subscription_usage = (
        subscription_campaign_usage.SqlAlchemySubscriptionCampaignUsage
    )

    async with env["container"].transaction_manager.transaction() as db:
        assert await from_subscription_usage().usage(
            submit.actor_id,
            env["clock"].now() - timedelta(seconds=1),
            session=db,
        ) == (1, 1)
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(PermissionError):
            await services["campaign_response_service"].report(
                env["users"]["foreign"].user_id,
                submit.campaign_id,
                principal=proof(env, "foreign"),
                session=db,
            )


@pytest.mark.asyncio
async def test_unknown_send_never_retried_and_optout_before_prepare_skips(
    campaign_env,
):
    env = campaign_env
    services, transport, submit = await approved(env)
    transport.fail = True
    assert await services["campaign_delivery_service"].run_once() == 1
    assert await services["campaign_delivery_service"].run_once() == 0
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_optout_before_start_skips_without_provider_call(campaign_env):
    env = campaign_env
    services, transport, submit = await approved(env)
    await execute(env, command(env, "unsubscribe", role="creator", expected=1))
    assert await services["campaign_delivery_service"].run_once() == 0
    assert not transport.calls
    async with env["container"].transaction_manager.transaction() as db:
        report = await services["campaign_response_service"].report(
            env["users"]["owner"].user_id,
            submit.campaign_id,
            principal=proof(env, "owner"),
            session=db,
        )
    assert report["delivery"] == {"skipped": 1}


@pytest.mark.asyncio
async def test_cancel_and_admin_revocation_prevent_new_starts(campaign_env):
    from ugc_bot.domain.campaign_moderation import CancelCampaign

    env = campaign_env
    services, transport, submit = await approved(env)
    async with env["container"].transaction_manager.transaction() as db:
        current = await services[
            "campaign_moderation_service"
        ].repository.state(submit.campaign_id, context=None, session=db)
        await services["campaign_moderation_service"].cancel(
            CancelCampaign(
                submit.actor_id,
                "cancel",
                submit.campaign_id,
                current.version.campaign_version,
                "Synthetic cancellation",
            ),
            principal=proof(env, "owner"),
            session=db,
        )
    assert await services["campaign_delivery_service"].run_once() == 0
    assert not transport.calls


@pytest.mark.asyncio
async def test_two_workers_cannot_start_one_job_twice(campaign_env):
    import asyncio

    env = campaign_env
    services, transport, _ = await approved(env)
    worker = services["campaign_delivery_service"]
    results = await asyncio.gather(worker.run_once(), worker.run_once())
    assert sum(results) == 1 and len(transport.calls) == 1


@pytest.mark.asyncio
async def test_crash_after_committed_attempt_becomes_unknown_without_resend(
    campaign_env,
):
    env = campaign_env
    services, transport, _ = await approved(env)
    worker = services["campaign_delivery_service"]
    async with env["container"].transaction_manager.transaction() as db:
        jobs = await worker.repository.pending(
            env["clock"].now(), 1, session=db
        )
    async with env["container"].transaction_manager.transaction() as db:
        attempt = await worker.repository.prepare(
            jobs[0], env["clock"].now(), access=None, session=db
        )
    assert attempt
    env["clock"].at += timedelta(seconds=121)
    assert await worker.run_once() == 0
    assert not transport.calls


@pytest.mark.asyncio
async def test_response_idempotence_and_withdrawal_after_consent_revoked(
    campaign_env,
):
    env = campaign_env
    services, _, submit = await approved(env)
    service = services["campaign_response_service"]
    actor = env["users"]["creator"].user_id
    async with env["container"].transaction_manager.transaction() as db:
        first = await service.respond(
            actor,
            submit.campaign_id,
            "same-key",
            0,
            "interested",
            principal=proof(env, "creator"),
            session=db,
        )
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await service.respond(
                actor,
                submit.campaign_id,
                "same-key",
                0,
                "interested",
                principal=proof(env, "creator"),
                session=db,
            )
            == first
        )
    await execute(env, command(env, "unsubscribe", role="creator", expected=1))
    async with env["container"].transaction_manager.transaction() as db:
        current = await service.view(
            actor,
            submit.campaign_id,
            principal=proof(env, "creator"),
            session=db,
        )
    assert current["allowed_choices"] == ["withdrawn"]
    async with env["container"].transaction_manager.transaction() as db:
        result = await service.respond(
            actor,
            submit.campaign_id,
            "withdraw",
            1,
            "withdrawn",
            principal=proof(env, "creator"),
            session=db,
        )
    assert result["choice"] == "withdrawn" and result["version"] == 2


@pytest.mark.asyncio
async def test_foreign_recipient_cannot_read_and_no_edit_after_submission(
    campaign_env,
):
    env = campaign_env
    services, _, submit = await approved(env)
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(LookupError):
            await services["campaign_response_service"].view(
                env["users"]["foreign"].user_id,
                submit.campaign_id,
                principal=proof(env, "foreign"),
                session=db,
            )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(ValueError, match="campaign_not_editable"):
            await (
                env["container"]
                .build_bot_services()["campaign_review_service"]
                .save_draft(
                    SaveCampaignDraft.parse(
                        submit.actor_id,
                        {
                            "campaign_id": str(submit.campaign_id),
                            "operation_key": "edit-approved",
                            "expected_version": 3,
                            "policy_version": submit.policy_version,
                            "terms_hash": submit.terms_hash,
                            "content": {
                                "title": "Altered",
                                "text": "Must not change accepted invitation",
                            },
                            "segment": {},
                        },
                    ),
                    session=db,
                )
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_signed_runtime_routes_replay_privacy_and_strict_bodies(
    campaign_env, platform
):
    import httpx
    from fastapi import FastAPI
    from sqlalchemy import update

    from tests.e2e.miniapp_helpers import generate_init_data
    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.miniapp.api import router

    env = campaign_env
    _, _, submit = await approved(env)
    container = env["container"]
    if platform == "max":
        async with container.transaction_manager.transaction() as db:
            for user in env["users"].values():
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == user.user_id)
                    .values(max_id=user.telegram_id)
                )
    app = FastAPI()
    app.state.config = container._config
    app.state.dispatcher = container.build_bot_services()
    app.include_router(router, prefix="/miniapp")

    def body(role):
        return {
            "init_data": generate_init_data(
                "test-token", int(env["users"][role].telegram_id), "synthetic"
            ),
            "platform": platform,
            "campaign_id": str(submit.campaign_id),
        }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/miniapp/api/campaigns/recipient/view", json=body("creator")
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["allowed_choices"] == ["interested", "declined"]
        foreign = await client.post(
            "/miniapp/api/campaigns/owned/report", json=body("foreign")
        )
        assert foreign.status_code == 403
        malformed = await client.post(
            "/miniapp/api/campaigns/recipient/view",
            json=body("creator") | {"recipient_id": str(submit.actor_id)},
        )
        assert malformed.status_code == 422
        replay = await client.post(
            "/miniapp/api/campaigns/owned/submit",
            json={
                **body("owner"),
                "operation_key": submit.operation_key,
                "expected_version": submit.expected_version,
                "revision_digest": submit.revision_digest,
                "policy_version": submit.policy_version,
                "terms_hash": submit.terms_hash,
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["current_state"] == "approved_waiting"


@pytest.mark.asyncio
async def test_paid_access_denial_before_attempt_skips_without_transport(
    campaign_env,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    env = campaign_env
    services, transport, _ = await approved(env)
    worker = services["campaign_delivery_service"]
    access = SimpleNamespace(
        require_access=AsyncMock(
            side_effect=PermissionError("campaign_subscription_required")
        )
    )
    worker.access = access
    assert await worker.run_once() == 0 and not transport.calls
    assert access.require_access.await_args.kwargs["action"] == "send"


@pytest.mark.asyncio
async def test_late_provider_acceptance_retains_fact_without_replacing_unknown(
    campaign_env,
):
    from sqlalchemy import select

    from ugc_bot.infrastructure.db.campaign_runtime_models import (
        OBSERVATIONS,
        OUTCOMES,
    )

    env = campaign_env
    services, transport, _ = await approved(env)
    worker = services["campaign_delivery_service"]
    async with env["container"].transaction_manager.transaction() as db:
        job = (
            await worker.repository.pending(env["clock"].now(), 1, session=db)
        )[0]
    async with env["container"].transaction_manager.transaction() as db:
        attempt = await worker.repository.prepare(
            job, env["clock"].now(), access=None, session=db
        )
    env["clock"].at += timedelta(seconds=121)
    assert await worker.run_once() == 0
    async with env["container"].transaction_manager.transaction() as db:
        await worker.repository.finish(
            attempt,
            "accepted",
            "synthetic:late-proof",
            None,
            env["clock"].now(),
            session=db,
        )
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await db.scalar(
                select(OUTCOMES.c.state).where(OUTCOMES.c.job_id == job)
            )
            == "unknown"
        )
        observed = (
            (
                await db.execute(
                    select(OBSERVATIONS.c.state).where(
                        OBSERVATIONS.c.job_id == job
                    )
                )
            )
            .scalars()
            .all()
        )
        assert observed == ["accepted"]
    assert not transport.calls


@pytest.mark.asyncio
async def test_recipient_conflicts_current_actor_and_retained_scope(
    campaign_env,
):
    from sqlalchemy import update

    from ugc_bot.infrastructure.db.models import UserModel

    env = campaign_env
    services, _, submit = await approved(env)
    service = services["campaign_response_service"]

    async def respond(key, version, choice):
        async with env["container"].transaction_manager.transaction() as db:
            return await service.respond(
                env["users"]["creator"].user_id,
                submit.campaign_id,
                key,
                version,
                choice,
                principal=proof(env, "creator"),
                session=db,
            )

    with pytest.raises(ValueError, match="campaign_not_active"):
        await respond("no-response", 0, "withdrawn")
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(LookupError, match="campaign_submission_not_found"):
            await service.respond(
                env["users"]["foreign"].user_id,
                submit.campaign_id,
                "foreign",
                0,
                "interested",
                principal=proof(env, "foreign"),
                session=db,
            )
    await respond("same", 0, "interested")
    with pytest.raises(ValueError, match="campaign_operation_conflict"):
        await respond("same", 0, "declined")
    with pytest.raises(ValueError, match="campaign_version_conflict"):
        await respond("new", 0, "declined")
    await execute(env, command(env, "unsubscribe", role="creator", expected=1))
    with pytest.raises(
        PermissionError, match="campaign_recipient_no_longer_eligible"
    ):
        await respond("revoked", 1, "interested")
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["creator"].user_id)
            .values(status="pause")
        )
    with pytest.raises(PermissionError, match="campaign_active_actor_required"):
        await respond("paused", 1, "withdrawn")


@pytest.mark.asyncio
async def test_current_admin_queue_expiry_and_sql_scope_barriers(campaign_env):
    from dataclasses import replace

    from ugc_bot.domain.campaign_moderation import SettleCampaignExpiry

    env = campaign_env
    services, _, submit = await approved(env)
    moderation = services["campaign_moderation_service"]
    repo = moderation.repository
    async with env["container"].transaction_manager.transaction() as db:
        queue = await moderation.queue(
            env["users"]["admin"].user_id,
            0,
            principal=proof(env, "admin"),
            session=db,
        )
        assert queue["submissions"] == []
    async with env["container"].transaction_manager.transaction() as db:
        assert await repo.state(uuid4(), context=None, session=db) is None
        with pytest.raises(
            LookupError, match="existing_campaign_account_required"
        ):
            await repo._actor(uuid4(), db)
    async with env["container"].transaction_manager.transaction() as db:
        pre = await repo.preflight(
            submit.actor_id,
            submit.campaign_id,
            None,
            purpose="cancel",
            session=db,
        )
        incomplete = replace(
            pre,
            user_ids=tuple(
                x for x in pre.user_ids if x != env["users"]["creator"].user_id
            ),
        )
        with pytest.raises(ValueError, match="campaign_scope_changed"):
            await repo.prepare(
                incomplete, principal=proof(env, "owner"), session=db
            )
    async with env["container"].transaction_manager.transaction() as first:
        pre = await repo.preflight(
            submit.actor_id,
            submit.campaign_id,
            None,
            purpose="cancel",
            session=first,
        )
        context = await repo.prepare(
            pre, principal=proof(env, "owner"), session=first
        )
        async with env["container"].transaction_manager.transaction() as second:
            with pytest.raises(
                ValueError, match="campaign_caller_transaction_required"
            ):
                await repo.authority(
                    submit.actor_id, context=context, session=second
                )
    env["clock"].at += timedelta(seconds=10001)
    async with env["container"].transaction_manager.transaction() as db:
        result = await services["campaign_capacity_service"].settle_expired(
            SettleCampaignExpiry(
                env["users"]["admin"].user_id,
                "expire",
                submit.policy_version,
                "Synthetic elapsed dispatch TTL",
            ),
            principal=proof(env, "admin"),
            session=db,
        )
        assert result["settled_count"] >= 1


@pytest.mark.asyncio
async def test_transport_outcomes_require_exact_committed_attempt(campaign_env):
    from dataclasses import replace

    from sqlalchemy import select

    from ugc_bot.infrastructure.db.campaign_runtime_models import JOBS

    env = campaign_env
    services, _, submit = await approved(env)
    repo = services["campaign_delivery_service"].repository
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(LookupError, match="campaign_submission_not_found"):
            await repo.prepare(
                uuid4(), env["clock"].now(), access=None, session=db
            )
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
    for changed in (
        replace(attempt, job_id=uuid4()),
        replace(attempt, attempt_id=uuid4()),
    ):
        async with env["container"].transaction_manager.transaction() as db:
            with pytest.raises(ValueError, match="campaign_attempt_mismatch"):
                await repo.finish(
                    changed,
                    "accepted",
                    "synthetic:mismatch",
                    None,
                    env["clock"].now(),
                    session=db,
                )
