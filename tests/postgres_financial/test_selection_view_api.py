"""Signed selection reads reveal only the current client's actual sources."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, text, update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.postgres_financial.test_paid_selection_delivery import (
    delivery_env as _delivery_env,
)
from tests.postgres_financial.test_paid_selection_interest import (
    capture,
    seed_creators,
    service,
)
from tests.postgres_financial.test_v1_capture import capture_env as _capture_env
from ugc_bot.config import AppConfig, MaxBotConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.miniapp.api import router

capture_env = _capture_env
delivery_env = _delivery_env


def configuration(env, *, enabled=True):
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": env["pg"].url.render_as_string(hide_password=False),
            "FINANCIAL_CORE_ENABLED": enabled,
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    config.max_bot = MaxBotConfig(MAX_BOT_TOKEN="max-test-token")
    return config


def app(container):
    value = FastAPI()
    value.include_router(router, prefix="/miniapp")
    value.state.config = container._config
    value.state.dispatcher = container.build_bot_services()
    return value


def signed(external_id, platform="telegram"):
    return dict(
        init_data=generate_init_data(
            "test-token" if platform == "telegram" else "max-test-token",
            int(external_id),
            "synthetic-client",
        ),
        platform=platform,
    )


def identity(env, user_id):
    external = str(uuid4().int % 10**12 + 1)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == user_id)
            .values(telegram_id=external, max_id=external, country="ru")
        )
    return external


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_own_ready_selection_survives_rebuilt_container(
    capture_env, platform
):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    interest = await service(env).respond(env["order"], creator)
    external = identity(env, env["client"])
    path = f"/miniapp/api/financial/orders/{env['order']}/selection"
    for enabled in (True, False):
        container = Container(configuration(env, enabled=enabled))
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app(container)),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    path, json=signed(external, platform)
                )
                assert response.status_code == 200, response.text
                data = response.json()
                assert data["writes_paused"] is not enabled
                assert data["order_id"] == str(env["order"])
                assert data["policy_version"] == env["version"]
                assert data["waitlist_count"] == 0
                first, second = data["positions"]
                assert first["assignment_id"] == str(interest.assignment_id)
                assert first["creator_id"] == str(creator)
                assert first["delivery_state"] == "ready" and first["current"]
                assert first["delivered_at"] is first["fulfilled_at"] is None
                assert first["deliveries"] == []
                assert first["selection_minor"] == 50000
                assert first["accompaniment_minor"] == 120000
                assert second["assignment_id"] is None
                assert second["delivery_state"] == "unassigned"
                assert "provider_reference" not in response.text
        finally:
            await container.dispose()


@pytest.mark.asyncio
async def test_foreign_client_forgery_and_current_role_revocation(capture_env):
    env = capture_env
    creator, stranger, *_ = seed_creators(env)
    await capture(env)
    await service(env).respond(env["order"], creator)
    own_external = identity(env, env["client"])
    foreign_external = identity(env, stranger)
    with Session(env["pg"]) as db, db.begin():
        db.add(AdvertiserProfileModel(user_id=stranger, contact="foreign"))
    container = Container(configuration(env))
    path = f"/miniapp/api/financial/orders/{env['order']}/selection"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(container)),
            base_url="http://testserver",
        ) as client:
            response = await client.post(path, json=signed(foreign_external))
            assert response.status_code == 404
            assert str(creator) not in response.text
            for extra in (
                {"client_id": str(env["client"])},
                {"accepted": True},
                {"provider_reference": "forged"},
            ):
                response = await client.post(
                    path, json={**signed(own_external), **extra}
                )
                assert response.status_code == 422
            assert (
                await client.post(
                    path + "?client_id=forged", json=signed(own_external)
                )
            ).status_code == 422
            assert (
                await client.post(path, json={"init_data": "forged"})
            ).status_code == 401
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    update(UserModel)
                    .where(UserModel.user_id == env["client"])
                    .values(status=UserStatus.BLOCKED)
                )
            assert (
                await client.post(path, json=signed(own_external))
            ).status_code == 403
    finally:
        await container.dispose()


@pytest.mark.asyncio
async def test_accepted_history_does_not_mark_replacement_as_delivered(
    delivery_env,
):
    from datetime import timedelta

    from ugc_bot.infrastructure.db.repositories.item_assignments import (
        SqlAlchemyItemAssignmentRepository,
    )

    env = delivery_env
    await env["worker"].run_once()
    viewer = env["container"].build_bot_services()["selection_view_service"]
    before = await viewer.view(env["order"], env["client"])
    first = before["positions"][0]
    assert first["delivery_state"] == "accepted"
    assert first["delivered_at"] == first["fulfilled_at"]
    assert first["deliveries"][0]["current"] is True
    async with env["factory"].begin() as db:
        replacement = await SqlAlchemyItemAssignmentRepository().replace(
            paid_item_id=env["interest"].paid_item_id,
            expected_version=1,
            creator_id=env["other_creator"],
            manager_id=None,
            actor_id=env["client"],
            reason="actual client replacement before work",
            at=env["worker"].clock.at + timedelta(seconds=1),
            session=db,
        )
        replacement_id = replacement.assignment_id
    after = await viewer.view(env["order"], env["client"])
    current = after["positions"][0]
    assert current["assignment_id"] == replacement_id
    assert current["creator_id"] == env["other_creator"]
    assert current["delivered_at"] is None
    assert current["delivery_state"] == "unknown"
    assert current["fulfilled_at"] == first["fulfilled_at"]
    assert current["deliveries"][0]["current"] is False
    assert current["deliveries"][0]["creator_id"] == env["creator"]


@pytest.mark.asyncio
async def test_snapshot_does_not_mix_concurrent_new_interest(
    capture_env, monkeypatch
):
    from ugc_bot.infrastructure.db.repositories import selection_view as module

    env = capture_env
    first, second, *_ = seed_creators(env)
    await capture(env)
    await service(env).respond(env["order"], first)
    container = Container(configuration(env))
    real_rows, changed = module._rows, False

    async def concurrent_write(db, statement):
        nonlocal changed
        result = await real_rows(db, statement)
        if not changed:
            changed = True
            await service(env).respond(env["order"], second)
        return result

    monkeypatch.setattr(module, "_rows", concurrent_write)
    try:
        viewer = container.build_bot_services()["selection_view_service"]
        observed = await viewer.view(env["order"], env["client"])
        assert observed["positions"][1]["assignment_id"] is None
        refreshed = await viewer.view(env["order"], env["client"])
        assert refreshed["positions"][1]["creator_id"] == second
    finally:
        await container.dispose()


@pytest.mark.asyncio
async def test_accepted_queue_projection_without_receipt_is_unknown(
    capture_env,
):
    from ugc_bot.infrastructure.db.paid_selection_models import JOBS

    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    interest = await service(env).respond(env["order"], creator)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(JOBS)
            .where(JOBS.c.job_id == interest.job_id)
            .values(state="accepted")
        )
    container = Container(configuration(env))
    try:
        data = await container.build_bot_services()[
            "selection_view_service"
        ].view(env["order"], env["client"])
        assert data["positions"][0]["delivery_state"] == "unknown"
        assert data["positions"][0]["fulfilled_at"] is None
    finally:
        await container.dispose()


@pytest.mark.asyncio
async def test_unproven_refund_projection_is_not_reported_as_refunded(
    capture_env,
):
    env = capture_env
    creator, *_ = seed_creators(env)
    await capture(env)
    interest = await service(env).respond(env["order"], creator)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(OrderItemModel)
            .where(OrderItemModel.paid_item_id == interest.paid_item_id)
            .values(selection_state="refunded")
        )
    container = Container(configuration(env))
    try:
        data = await container.build_bot_services()[
            "selection_view_service"
        ].view(env["order"], env["client"])
        assert data["positions"][0]["delivery_state"] == "unknown"
        assert data["positions"][0]["fulfilled_at"] is None
    finally:
        await container.dispose()


@pytest.mark.asyncio
async def test_missing_role_legacy_scope_and_missing_migration_fail_explicitly(
    capture_env,
):
    env = capture_env
    seed_creators(env)
    container = Container(configuration(env))
    legacy = uuid4()
    with Session(env["pg"]) as db, db.begin():
        db.add(
            OrderModel(
                order_id=legacy,
                advertiser_id=env["client"],
                product_link="legacy",
                offer_text="legacy",
                price=1,
                bloggers_needed=2,
                status="active",
            )
        )
    viewer = container.build_bot_services()["selection_view_service"]
    try:
        with pytest.raises(
            ValueError, match="selection_order_has_no_financial_version"
        ):
            await viewer.view(legacy, env["client"])
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                text(
                    "ALTER TABLE paid_selection_accepted_deliveries "
                    "RENAME TO paid_selection_missing_deliveries"
                )
            )
        try:
            with pytest.raises(
                ValueError, match="selection_history_unavailable"
            ):
                await viewer.view(env["order"], env["client"])
        finally:
            with Session(env["pg"]) as db, db.begin():
                db.execute(
                    text(
                        "ALTER TABLE paid_selection_missing_deliveries "
                        "RENAME TO paid_selection_accepted_deliveries"
                    )
                )
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                delete(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == env["client"]
                )
            )
        with pytest.raises(
            PermissionError, match="selection_client_role_required"
        ):
            await viewer.view(env["order"], env["client"])
    finally:
        await container.dispose()
