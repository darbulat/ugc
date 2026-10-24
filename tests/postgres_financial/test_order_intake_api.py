"""Signed Telegram/MAX creation uses production factories and server pricing."""

from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.orm import Session

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.postgres_financial.test_order_intake import (
    command,
    scoped_rows,
)
from tests.postgres_financial.test_order_intake import (
    intake_env as _intake_env,
)
from ugc_bot.config import MaxBotConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.miniapp.api import router


@pytest_asyncio.fixture
async def intake_env(financial_pg_engine):
    async for env in _intake_env.__wrapped__(financial_pg_engine):
        yield env


def app(env, container):
    value = FastAPI()
    value.include_router(router, prefix="/miniapp")
    value.state.config = container._config
    value.state.dispatcher = container.build_bot_services()
    return value


def body(env, platform="telegram"):
    source = command(env)
    return dict(
        init_data=generate_init_data(
            "test-token" if platform == "telegram" else "max-test-token",
            int(env["user"].telegram_id),
            "advertiser",
        ),
        platform=platform,
        operation_key=source.operation_key,
        policy_version=source.policy_version,
        product_link=source.product_link,
        offer_text=source.offer_text,
        honorarium=str(source.honorarium),
        selection_due_at=source.selection_due_at.isoformat(),
        contact_reference=source.contact_reference,
        service_mode="with_manager",
        accompaniment_ordinals=[1, 7],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_intake_survives_new_container(intake_env, platform):
    env = intake_env
    config = env["config"].model_copy(
        update={"max_bot": MaxBotConfig(MAX_BOT_TOKEN="max-test-token")}
    )
    if platform == "max":
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["user"].user_id)
                .values(max_id=env["user"].telegram_id)
            )
    containers = [Container(config), Container(config)]
    payload = body(env, platform)
    original = None
    try:
        for container in containers:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app(env, container)),
                base_url="http://testserver",
            ) as client:
                response = await client.post(
                    "/miniapp/api/financial/orders", json=payload
                )
                assert response.status_code == 200, response.text
                data = response.json()
                assert data["total_minor"] == 1740000
                assert data["selection_base_minor"] == 1500000
                assert data["honorarium_payment"] == "paid_direct"
                assert len(data["items"]) == 30
                assert data.get("invoice_url") is None
                if original is not None:
                    assert data == original
                original = data
        from uuid import UUID

        assert (
            len(
                scoped_rows(
                    env, "accompaniment_leads", UUID(original["order_id"])
                )
            )
            == 1
        )
    finally:
        for container in containers:
            await container.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_public_intake_rejects_authority_fields_and_changed_payload(
    intake_env,
):
    env = intake_env
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://testserver",
    ) as client:
        payload = body(env)
        for name, value in {
            "client_id": str(uuid4()),
            "order_id": str(uuid4()),
            "manager_id": str(env["admin"].user_id),
            "selection_minor": 1,
            "approved_at": env["clock"].at.isoformat(),
        }.items():
            response = await client.post(
                "/miniapp/api/financial/orders", json={**payload, name: value}
            )
            assert response.status_code == 422
        response = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
        assert response.status_code == 200, response.text
        conflict = await client.post(
            "/miniapp/api/financial/orders",
            json={
                **payload,
                "service_mode": "self_service",
                "accompaniment_ordinals": [],
            },
        )
        assert conflict.status_code == 409
        unsigned = await client.post(
            "/miniapp/api/financial/orders",
            json={**payload, "init_data": "bad"},
        )
        assert unsigned.status_code == 401
        duplicate = await client.post(
            "/miniapp/api/financial/orders",
            json={
                **payload,
                "operation_key": "duplicates",
                "accompaniment_ordinals": [1, 1],
            },
        )
        assert duplicate.status_code == 422
        client._transport.app.state.dispatcher["order_intake_service"] = None
        unavailable = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
        assert unavailable.status_code == 503


@pytest.mark.asyncio
async def test_intake_factory_is_default_off_and_uses_current_role(intake_env):
    env = intake_env
    payload = body(env)
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["user"].user_id)
            .values(status="blocked")
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
        assert response.status_code == 403
    disabled = Container(
        env["config"].model_copy(
            update={
                "financial": env["config"].financial.model_copy(
                    update={"core_enabled": False}
                )
            }
        )
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app(env, disabled)),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/miniapp/api/financial/orders", json=payload
            )
            assert response.status_code == 503
    finally:
        await disabled.session_factory.kw["bind"].dispose()


@pytest.mark.asyncio
async def test_signed_client_cannot_bypass_policy_or_deadline(
    intake_env,
):
    from datetime import timedelta

    env = intake_env
    outside = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], outside.user_id
    )
    payload = body(env)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://testserver",
    ) as client:
        forbidden = await client.post(
            "/miniapp/api/financial/orders",
            json={
                **payload,
                "init_data": generate_init_data(
                    "test-token", int(outside.telegram_id), "other"
                ),
            },
        )
        assert forbidden.status_code == 403
        invalid = await client.post(
            "/miniapp/api/financial/orders",
            json={
                **payload,
                "selection_due_at": (
                    env["clock"].at - timedelta(days=1)
                ).isoformat(),
            },
        )
        assert invalid.status_code == 400
        assert invalid.json()["detail"] == "agreed_selection_due_at_required"


@pytest.mark.asyncio
async def test_v1_own_order_list_exposes_real_policy_without_legacy_pay_action(
    intake_env,
):
    env = intake_env
    env["config"].bot.bot_username = "synthetic_test_bot"
    payload = body(env)
    auth = {
        key: value
        for key, value in payload.items()
        if key in ("init_data", "platform")
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/miniapp/api/financial/orders", json=payload
        )
        assert created.status_code == 200
        listed = await client.post("/miniapp/api/orders/list", json=auth)
        assert listed.status_code == 200
        item = next(
            value
            for value in listed.json()["orders"]
            if value["order_id"] == created.json()["order_id"]
        )
        assert item["financial_version"] == env["policy"]
        assert item["payment_link"] == ""
