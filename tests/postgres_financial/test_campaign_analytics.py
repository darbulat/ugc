"""Actual append-only analytics SQL and signed HTTP; synthetic evidence only."""

import os
from datetime import timedelta
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.financial_environment import isolated_financial_database
from tests.postgres_financial.test_campaign_runtime import (  # noqa: F401
    approved,
    proof,
)
from tests.postgres_financial.test_campaign_runtime import (
    campaign_env as runtime_env,
)
from ugc_bot.container.campaign_analytics_factory import (
    build_campaign_analytics,
)
from ugc_bot.domain.campaign_analytics import AnalyticsSourceSpec, MetricEvent
from ugc_bot.miniapp.campaign_analytics_api import (
    create_campaign_analytics_router,
)


@pytest_asyncio.fixture
async def campaign_env(financial_pg_engine):
    async for value in runtime_env.__wrapped__(financial_pg_engine):
        yield value


@pytest.fixture(scope="module")
def financial_pg_engine():
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="0113_campaign_analytics",
    ) as engine:
        yield engine


async def setup(env):
    _, _, submit = await approved(env)
    service = build_campaign_analytics(
        env["container"].transaction_manager, clock=env["clock"]
    )["campaign_analytics_service"]
    spec = AnalyticsSourceSpec(
        "campaign",
        submit.campaign_id,
        "synthetic-source",
        "synthetic-account:" + str(submit.campaign_id),
        env["clock"].now() - timedelta(days=2),
        env["clock"].now() - timedelta(days=1),
        10000,
        "RUB",
        ("views", "leads", "sales"),
        "synthetic:source-proof",
        "synthetic:budget-proof",
        "Synthetic admin publication",
    )
    return service, submit, spec


async def call(env, service, method, *args, role="admin", **kwargs):
    async with env["container"].transaction_manager.transaction() as db:
        return await getattr(service, method)(
            env["users"][role].user_id,
            *args,
            principal=proof(env, role),
            session=db,
            **kwargs,
        )


@pytest.mark.asyncio
async def test_actual_sql_evidence_import_costs_refunds_and_readiness(
    campaign_env,
):
    env = campaign_env
    service, submit, spec = await setup(env)
    empty = await call(
        env, service, "report", "campaign", submit.campaign_id, role="owner"
    )
    assert empty["state"] == "no_data" and empty["rates"]["cpv"] is None
    result = await call(env, service, "publish", "publish", spec)
    source = UUID(result["source_id"])
    assert await call(env, service, "publish", "publish", spec) == result
    at = spec.attribution_from + timedelta(hours=1)
    events = (
        MetricEvent("v1", "view", at, "video-1", 100),
        MetricEvent("l1", "lead", at, "lead-1"),
        MetricEvent("s1", "sale", at, "sale-1", 1, 20000),
        MetricEvent("r1", "refund", at, "sale-1", 1, 10000),
    )
    assert (
        await call(env, service, "import_events", "import", source, events)
    )["imported"] == 4
    assert (
        await call(env, service, "import_events", "reimport", source, events)
    )["imported"] == 0
    partial = await call(
        env, service, "report", "campaign", submit.campaign_id, role="owner"
    )
    assert partial["state"] == "partial" and partial["rates"]["cpv"] is None
    await call(
        env,
        service,
        "close_source",
        "finalize",
        source,
        "finalize",
        "synthetic:reconciled",
        "Synthetic final evidence",
    )
    report = await call(
        env, service, "report", "campaign", submit.campaign_id, role="owner"
    )
    assert report["rates"] == {
        "cpv": "1.000000",
        "cpl": "100.000000",
        "cpa": "100.000000",
    }
    assert report["net_sales_revenue_minor"] == "10000"
    assert report["commercial_validation_confirmed"] is False
    await call(
        env,
        service,
        "record_paid_pilot",
        "pilot",
        "campaign",
        submit.campaign_id,
        "synthetic:receipt",
        10000,
        "RUB",
        "synthetic:proof",
    )
    assert (
        await call(
            env, service, "report", "campaign", submit.campaign_id, role="owner"
        )
    )["paid_pilot_campaigns"] == 1
    assert "proof" not in str(report) and "account_label" not in str(report)
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(Exception, match="campaign_analytics_immutable"):
            await db.execute(text("DELETE FROM campaign_analytics_events"))


@pytest.mark.asyncio
async def test_actual_sql_conflicts_cutoff_authority_and_void(campaign_env):
    from dataclasses import replace

    env = campaign_env
    service, submit, spec = await setup(env)
    source = UUID(
        (await call(env, service, "publish", "publish", spec))["source_id"]
    )
    at = spec.attribution_from + timedelta(hours=1)
    await call(
        env,
        service,
        "import_events",
        "event",
        source,
        (MetricEvent("v1", "view", at, "video", 1),),
    )
    with pytest.raises(ValueError, match="analytics_event_conflict"):
        await call(
            env,
            service,
            "import_events",
            "changed",
            source,
            (MetricEvent("v1", "view", at, "video", 2),),
        )
    with pytest.raises(ValueError, match="analytics_event_outside_attribution"):
        await call(
            env,
            service,
            "import_events",
            "future",
            source,
            (MetricEvent("v2", "view", env["clock"].now(), "video"),),
        )
    with pytest.raises(ValueError, match="analytics_refund_evidence_required"):
        await call(
            env,
            service,
            "import_events",
            "orphan",
            source,
            (MetricEvent("r1", "refund", at, "missing", 1, 100),),
        )
    with pytest.raises(PermissionError):
        await call(env, service, "publish", "not-admin", spec, role="owner")
    with pytest.raises(PermissionError):
        await call(
            env,
            service,
            "report",
            "campaign",
            submit.campaign_id,
            role="foreign",
        )
    with pytest.raises(ValueError, match="analytics_operation_conflict"):
        await call(
            env, service, "publish", "publish", replace(spec, reason="Changed")
        )
    await call(
        env,
        service,
        "close_source",
        "void",
        source,
        "void",
        "synthetic:void",
        "Synthetic correction",
    )
    assert (
        await call(
            env, service, "report", "campaign", submit.campaign_id, role="owner"
        )
    )["state"] == "no_data"
    with pytest.raises(ValueError, match="analytics_source_closed"):
        await call(
            env,
            service,
            "import_events",
            "closed",
            source,
            (MetricEvent("v3", "view", at, "video"),),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_actual_signed_analytics_routes_are_strict_private_and_no_store(
    campaign_env, platform
):
    from sqlalchemy import update

    from ugc_bot.infrastructure.db.models import UserModel

    env = campaign_env
    service, submit, spec = await setup(env)
    if platform == "max":
        async with env["container"].transaction_manager.transaction() as db:
            for user in env["users"].values():
                await db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == user.user_id)
                    .values(max_id=user.telegram_id)
                )
    from ugc_bot.miniapp.campaign_principal import resolve_campaign_principal

    app = FastAPI()
    app.state.config = env["container"]._config
    app.state.dispatcher = env["container"].build_bot_services() | {
        "campaign_analytics_service": service
    }
    app.include_router(
        create_campaign_analytics_router(resolve_campaign_principal),
        prefix="/miniapp/api",
    )

    def identity(role):
        return {
            "init_data": generate_init_data(
                "test-token", int(env["users"][role].telegram_id), "synthetic"
            ),
            "platform": platform,
        }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        publish = await client.post(
            "/miniapp/api/analytics/admin/sources/publish",
            json=identity("admin")
            | {"operation_key": "publish", **spec.document()},
        )
        assert publish.status_code == 200, publish.text
        source = publish.json()["source_id"]
        event = MetricEvent(
            "v1",
            "view",
            spec.attribution_from + timedelta(hours=1),
            "video",
            100,
        )
        imported = await client.post(
            "/miniapp/api/analytics/admin/events/import",
            json=identity("admin")
            | {
                "operation_key": "import",
                "source_id": source,
                "events": [event.document()],
            },
        )
        assert imported.status_code == 200, imported.text
        report = await client.post(
            "/miniapp/api/analytics/owned/report",
            json=identity("owner")
            | {
                "subject_type": "campaign",
                "subject_id": str(submit.campaign_id),
            },
        )
        assert report.status_code == 200, report.text
        assert (
            report.headers["cache-control"] == "no-store"
            and report.json()["rates"]["cpv"] is None
        )
        denied = await client.post(
            "/miniapp/api/analytics/admin/sources/publish",
            json=identity("owner")
            | {"operation_key": "denied", **spec.document()},
        )
        assert (
            denied.status_code == 403
            and denied.headers["cache-control"] == "no-store"
        )
        foreign = await client.post(
            "/miniapp/api/analytics/owned/report",
            json=identity("admin")
            | {
                "subject_type": "campaign",
                "subject_id": str(submit.campaign_id),
            },
        )
        assert foreign.status_code == 403
        invalid = await client.post(
            "/miniapp/api/analytics/owned/report",
            json=identity("owner")
            | {
                "subject_type": "campaign",
                "subject_id": str(submit.campaign_id),
                "owner_id": str(submit.actor_id),
            },
        )
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_batch_rollback_and_replay_recheck_current_admin(
    campaign_env,
):
    from sqlalchemy import update

    from ugc_bot.infrastructure.db.models import UserModel

    env = campaign_env
    service, submit, spec = await setup(env)
    source = UUID(
        (await call(env, service, "publish", "publish", spec))["source_id"]
    )
    at = spec.attribution_from + timedelta(hours=1)
    valid = MetricEvent("atomic-view", "view", at, "video", 17)
    invalid = MetricEvent(
        "outside-window", "view", env["clock"].now(), "video", 99
    )
    with pytest.raises(ValueError, match="analytics_event_outside_attribution"):
        await call(
            env,
            service,
            "import_events",
            "atomic-import",
            source,
            (valid, invalid),
        )
    report = await call(
        env, service, "report", "campaign", submit.campaign_id, role="owner"
    )
    assert report["counts"]["views"] == 0
    assert (
        await call(
            env, service, "import_events", "atomic-import", source, (valid,)
        )
    )["imported"] == 1
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["users"]["admin"].user_id)
            .values(admin=False)
        )
    with pytest.raises(
        PermissionError, match="analytics_current_actor_required"
    ):
        await call(env, service, "publish", "publish", spec)


@pytest.mark.asyncio
async def test_actual_order_analytics_and_absent_or_rebound_principals(
    campaign_env,
):
    from dataclasses import replace
    from uuid import uuid4

    from tests.helpers.factories import create_test_order

    env = campaign_env
    service = build_campaign_analytics(
        env["container"].transaction_manager, clock=env["clock"]
    )["campaign_analytics_service"]
    order = await create_test_order(
        env["container"].build_repos()["order_repo"],
        env["users"]["owner"].user_id,
    )
    result = await call(
        env, service, "report", "order", order.order_id, role="owner"
    )
    assert result["state"] == "no_data"
    with pytest.raises(LookupError, match="analytics_subject_not_found"):
        await call(env, service, "report", "order", uuid4(), role="owner")
    with pytest.raises(ValueError, match="analytics_subject_required"):
        await call(
            env, service, "report", "invented", order.order_id, role="owner"
        )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(
            PermissionError, match="analytics_current_actor_required"
        ):
            await service.report(
                env["users"]["owner"].user_id,
                "order",
                order.order_id,
                principal=replace(proof(env, "owner"), external_id="rebound"),
                session=db,
            )
    async with env["container"].transaction_manager.transaction() as db:
        with pytest.raises(LookupError, match="analytics_source_not_found"):
            await service.repository.source(uuid4(), session=db)


@pytest.mark.asyncio
async def test_duplicate_budget_entities_and_unfinished_coverage_fail_closed(
    campaign_env,
):
    from dataclasses import replace

    env = campaign_env
    service, submit, spec = await setup(env)
    source = UUID(
        (await call(env, service, "publish", "publish", spec))["source_id"]
    )
    with pytest.raises(ValueError, match="analytics_source_required"):
        await call(env, service, "publish", "untyped", {})
    with pytest.raises(ValueError, match="analytics_currency_mismatch"):
        await call(
            env, service, "publish", "currency", replace(spec, currency="USD")
        )
    with pytest.raises(ValueError, match="analytics_budget_reference_reused"):
        await call(env, service, "publish", "duplicate-budget", spec)
    with pytest.raises(ValueError, match="analytics_event_batch_required"):
        await call(env, service, "import_events", "bad-batch", source, [])
    at = spec.attribution_from + timedelta(hours=1)
    events = (MetricEvent("unique-lead", "lead", at, "lead"),)
    receipt = await call(env, service, "import_events", "lead", source, events)
    assert (
        await call(env, service, "import_events", "lead", source, events)
        == receipt
    )
    with pytest.raises(ValueError, match="analytics_entity_already_recorded"):
        await call(
            env,
            service,
            "import_events",
            "duplicate-lead",
            source,
            (MetricEvent("another-id", "lead", at, "lead"),),
        )
    with pytest.raises(ValueError, match="analytics_metric_not_declared"):
        await call(
            env,
            service,
            "import_events",
            "undeclared-click",
            source,
            (MetricEvent("click", "click", at, "link"),),
        )
    with pytest.raises(ValueError, match="analytics_action_required"):
        await call(
            env,
            service,
            "close_source",
            "bad-action",
            source,
            "edit",
            "proof",
            "reason",
        )
    final = await call(
        env,
        service,
        "close_source",
        "final",
        source,
        "finalize",
        "proof",
        "reason",
    )
    assert (
        await call(
            env,
            service,
            "close_source",
            "final",
            source,
            "finalize",
            "proof",
            "reason",
        )
        == final
    )
    await call(
        env, service, "close_source", "void", source, "void", "proof", "reason"
    )
    with pytest.raises(ValueError, match="analytics_source_closed"):
        await call(
            env,
            service,
            "close_source",
            "closed",
            source,
            "finalize",
            "proof",
            "reason",
        )
    future = UUID(
        (
            await call(
                env,
                service,
                "publish",
                "future",
                replace(
                    spec,
                    budget_reference="future-budget",
                    attribution_until=env["clock"].now() + timedelta(days=1),
                ),
            )
        )["source_id"]
    )
    with pytest.raises(
        ValueError, match="analytics_future_coverage_unconfirmed"
    ):
        await call(
            env,
            service,
            "close_source",
            "future-final",
            future,
            "finalize",
            "proof",
            "reason",
        )
    with pytest.raises(ValueError, match="analytics_currency_required"):
        await call(
            env,
            service,
            "record_paid_pilot",
            "bad-currency",
            "campaign",
            submit.campaign_id,
            "receipt",
            100,
            "JPY",
            "proof",
        )
    pilot = await call(
        env,
        service,
        "record_paid_pilot",
        "pilot",
        "campaign",
        submit.campaign_id,
        "unique:" + str(submit.campaign_id),
        100,
        "RUB",
        "proof",
    )
    assert (
        await call(
            env,
            service,
            "record_paid_pilot",
            "pilot",
            "campaign",
            submit.campaign_id,
            "unique:" + str(submit.campaign_id),
            100,
            "RUB",
            "proof",
        )
        == pilot
    )
    with pytest.raises(ValueError, match="analytics_pilot_evidence_reused"):
        await call(
            env,
            service,
            "record_paid_pilot",
            "duplicate-pilot",
            "campaign",
            submit.campaign_id,
            "other-receipt",
            100,
            "RUB",
            "proof",
        )
