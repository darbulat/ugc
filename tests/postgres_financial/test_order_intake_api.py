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
from ugc_bot.domain.enums import UserStatus
from ugc_bot.infrastructure.db.models import AdvertiserProfileModel, UserModel
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
async def test_incomplete_registration_blocks_new_intake_but_keeps_orders(
    intake_env,
):
    env = intake_env
    payload = body(env)
    auth = {"init_data": payload["init_data"]}
    prefix = "/miniapp/api"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app(env, env["container"])),
        base_url="http://test",
    ) as client:
        first = await client.post(f"{prefix}/financial/orders", json=payload)
        assert first.status_code == 200, first.text
        order_id = first.json()["order_id"]
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(AdvertiserProfileModel)
                .where(AdvertiserProfileModel.user_id == env["user"].user_id)
                .values(agreement_confirmed_at=None)
            )

        me = await client.post(f"{prefix}/me", json=auth)
        assert me.json()["advertiser_profile"]["agreement_confirmed"] is False
        retry = await client.post(f"{prefix}/financial/orders", json=payload)
        assert retry.json() == first.json()
        listed = await client.post(f"{prefix}/orders/list", json=auth)
        assert listed.json()["orders"][0]["order_id"] == order_id
        invalid_filter = await client.post(
            f"{prefix}/orders/list", json=auth | {"status": "unknown"}
        )
        assert invalid_filter.status_code == 422
        assert invalid_filter.json() == {"detail": "order_status_invalid"}
        detail = await client.post(
            f"{prefix}/orders/get", json=auth | {"order_id": order_id}
        )
        assert detail.json()["order_id"] == order_id

        new_payload = payload | {"operation_key": uuid4().hex}
        denied = await client.post(
            f"{prefix}/financial/orders",
            json=new_payload,
            headers={"X-UMC-Agreement-Recovery": "1"},
        )
        assert denied.status_code == 403
        assert denied.json() == {"detail": "registration_agreement_required"}
        legacy_page = await client.post(
            f"{prefix}/financial/orders", json=new_payload
        )
        assert legacy_page.status_code == 401
        assert legacy_page.json() == {
            "detail": "registration_agreement_required"
        }
        confirmed = await client.post(
            f"{prefix}/register/advertiser/confirm-agreement", json=auth
        )
        assert confirmed.status_code == 200
        me = await client.post(f"{prefix}/me", json=auth)
        assert me.json()["advertiser_profile"]["agreement_confirmed"] is True
        created = await client.post(
            f"{prefix}/financial/orders", json=new_payload
        )
        assert created.status_code == 200, created.text
        assert created.json()["order_id"] != order_id

        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(UserModel)
                .where(UserModel.user_id == env["user"].user_id)
                .values(status=UserStatus.BLOCKED)
            )
        forbidden = await client.post(f"{prefix}/orders/list", json=auth)
        assert forbidden.status_code == 403
        assert forbidden.json() == {"detail": "active_advertiser_required"}


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


@pytest.mark.asyncio
async def test_consultation_selection_payment_and_targeted_delivery(intake_env):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock
    from urllib.parse import urlsplit
    from uuid import UUID

    from pydantic import SecretStr
    from sqlalchemy import select

    from ugc_bot.domain.browser_checkout import BrowserInvoice, BrowserPayment
    from ugc_bot.infrastructure.db.consultation_models import (
        CONSULTATION_ATTEMPTS,
    )
    from ugc_bot.infrastructure.db.order_notice_models import (
        CONSULTATION_DELIVERIES,
    )

    env = intake_env
    config = env["config"]
    container = env["container"]
    config.webhook.webhook_base_url = "https://bot.example.test"
    config.financial.yookassa_browser_enabled = True
    config.financial.yookassa_browser_shop_id = "123"
    config.financial.yookassa_browser_secret_key = SecretStr("synthetic")
    config.financial.yookassa_browser_test_mode = False
    other_admin = await create_test_user(
        env["repos"]["user_repo"], external_id="1234567", admin=True
    )
    unrelated = await create_test_user(
        env["repos"]["user_repo"], external_id="7654321", admin=True
    )
    allowed = frozenset((env["admin"].telegram_id, other_admin.telegram_id))
    config.admin.browser_paid_order_telegram_recipients = allowed
    config.admin.business_order_telegram_recipients = allowed | {
        unrelated.telegram_id
    }
    mobile_app = app(env, container)
    endpoint = "/miniapp/api/financial/orders"
    payload = body(env) | {
        "position_count": 10,
        "accompaniment_ordinals": None,
        "consultation_requested": True,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mobile_app),
        base_url="http://testserver",
    ) as client:
        assert (await client.post(endpoint, json=payload)).status_code == 400
        ready = mobile_app.state.dispatcher["order_intake_service"]
        ready.config.consultation_enabled = True
        signed = {key: payload[key] for key in ("init_data", "platform")}
        policies = await client.post(endpoint + "/policies", json=signed)
        assert policies.json()["consultation_minor"] == 500000
        response = await client.post(endpoint, json=payload)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["total_minor"] == 1700000
        assert result["project_total_minor"] == 2200000
        assert result["consultation_minor"] == 500000
        token = UUID(urlsplit(result["consultation_url"]).fragment)
        selected = await client.post(
            f"{endpoint}/{result['order_id']}/selection", json=signed
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()["consultation_url"] == result["consultation_url"]
        assert (await client.post(endpoint, json=payload)).json() == result
        conflict = await client.post(
            endpoint, json=payload | {"consultation_requested": False}
        )
        assert conflict.status_code == 409

    order_id = UUID(result["order_id"])
    receipt = scoped_rows(env, "order_intake_receipts", order_id)[0]
    assert str(token) not in str(receipt)
    checkout = container.build_consultation_checkout()
    invoice_id = f"in-{uuid4()}"
    hosted = "https://yookassa.ru/my/i/consultation"
    payment_id = str(uuid4())
    gateway = AsyncMock()
    checkout.gateway = gateway
    with pytest.raises(LookupError):
        await checkout.buyer_view(uuid4())
    assert await checkout.buyer_view(token) == {"state": "available"}
    gateway.observe.return_value = BrowserInvoice(invoice_id, "pending", hosted)
    await checkout.start(token, "buyer@example.test")
    attempt = gateway.observe.call_args.args[0]
    assert attempt.request["payment_data"]["amount"] == {
        "value": "5000.00",
        "currency": "RUB",
    }
    assert (
        attempt.request["payment_data"]["receipt"]["customer"]["email"]
        == "buyer@example.test"
    )
    await checkout.start(token, "buyer@example.test")
    gateway.observe.assert_awaited_once()
    assert (await checkout.buyer_view(token))["url"] == hosted
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            update(CONSULTATION_ATTEMPTS)
            .where(CONSULTATION_ATTEMPTS.c.order_id == order_id)
            .values(next_check_at=datetime.now(UTC))
        )
    gateway.observe.return_value = BrowserInvoice(
        invoice_id,
        "paid",
        payment=BrowserPayment(
            invoice_id, payment_id, "123", 500000, datetime.now(UTC)
        ),
    )
    assert await checkout.run_once(order_id)
    assert (await checkout.buyer_view(token))["state"] == "paid"
    order = await env["repos"]["order_repo"].get_by_id(order_id)
    quote = await container.build_order_notice_details_service().for_order(
        order
    )
    assert quote["consultation_state"] == "paid"
    assert quote["total_minor"] == 1700000
    await checkout.start(token, "buyer@example.test")
    assert gateway.observe.await_count == 2
    assert scoped_rows(env, "payments", order_id) == []
    assert scoped_rows(env, "financial_obligations", order_id) == []
    assert (
        len(scoped_rows(env, "consultation_checkout_attempts", order_id)) == 1
    )

    messenger = AsyncMock()
    worker = container.build_consultation_notice_delivery(messenger)
    for _ in range(4):
        assert await worker.run_once()
    assert not await worker.run_once()
    with Session(env["pg"]) as db:
        deliveries = (
            db.execute(
                select(CONSULTATION_DELIVERIES).where(
                    CONSULTATION_DELIVERIES.c.order_id == order_id
                )
            )
            .mappings()
            .all()
        )
    assert {
        (row["event_kind"], row["recipient"], row["state"])
        for row in deliveries
    } == {
        (kind, recipient, "sent")
        for kind in ("created", "paid")
        for recipient in allowed
    }
    assert {
        call.kwargs["chat_id"] for call in messenger.send_text.await_args_list
    } == allowed
    assert all(
        str(token) not in call.kwargs["text"]
        for call in messenger.send_text.await_args_list
    )
