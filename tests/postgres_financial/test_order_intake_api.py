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


async def _business_cards(cards, messenger, order_id):
    for _ in range(100):
        if not await cards.run_once():
            break
    return [
        call.kwargs
        for call in messenger.send_text.await_args_list
        if call.kwargs.get("keyboard")
        and any(
            button.url and str(order_id) in button.url
            for row in call.kwargs["keyboard"].rows
            for button in row
        )
    ]


def _assert_created_cards(created_cards, allowed):
    assert {card["chat_id"] for card in created_cards} == allowed
    assert len(created_cards) == len(allowed)
    for card in created_cards:
        assert card["parse_mode"] == "HTML"
        assert "🟠 Ожидает оплаты" in card["text"]
        assert (
            "<b>Менеджер</b> · нужен для всех креаторов · 12 000 ₽"
            in card["text"]
        )
        assert "<b>Консультация</b> · 5 000 ₽ · ожидает оплаты" in card["text"]
        assert "<b>Счёт за услуги</b> · 22 000 ₽" in card["text"]
        assert "Позиции:" not in card["text"]
        assert [
            button.text for row in card["keyboard"].rows for button in row
        ] == [
            "Открыть в админке",
            "Продукт",
            "Скопировать для GPT",
        ]


def _assert_paid_cards(paid_cards, allowed):
    assert len(paid_cards) == len(allowed)
    assert {card["chat_id"] for card in paid_cards} == allowed
    for card in paid_cards:
        assert "✅ Заказ оплачен" in card["text"]
        assert "<b>Консультация</b> · 5 000 ₽ · оплачена" in card["text"]
        assert "<b>Счёт за услуги</b> · 22 000 ₽" in card["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("combined", [False, True])
async def test_consultation_selection_payment_and_targeted_delivery(
    intake_env, combined, monkeypatch
):
    from datetime import UTC, datetime, timedelta
    from importlib import import_module
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from urllib.parse import urlsplit
    from uuid import UUID

    from pydantic import SecretStr
    from sqlalchemy import select

    from tests.helpers.correction_approval_pg import ApprovalRuntime
    from ugc_bot.application.errors import OrderCreationError
    from ugc_bot.domain.browser_checkout import BrowserInvoice, BrowserPayment
    from ugc_bot.domain.checkout import CheckoutActor
    from ugc_bot.infrastructure.db.browser_checkout_models import (
        BROWSER_ATTEMPTS,
    )
    from ugc_bot.infrastructure.db.consultation_models import (
        CONSULTATION_ATTEMPTS,
    )
    from ugc_bot.infrastructure.db.models import OutboxEventModel
    from ugc_bot.infrastructure.db.order_notice_models import (
        CONSULTATION_DELIVERIES,
    )
    from ugc_bot.infrastructure.db.repositories.consultation_checkout import (
        consultation_notices,
    )
    from ugc_bot.infrastructure.db.repositories.entitlements import (
        SqlAlchemyClientEntitlementRepository,
    )

    env = intake_env
    config = env["config"]
    container = env["container"]
    config.webhook.webhook_base_url = "https://bot.example.test"
    config.admin.admin_base_url = "https://admin.example.test/admin"
    config.financial.yookassa_browser_enabled = True
    config.financial.yookassa_browser_shop_id = "123"
    config.financial.yookassa_browser_secret_key = SecretStr("synthetic")
    config.financial.yookassa_browser_test_mode = False
    config.financial.combined_checkout_enabled = combined
    config.bot.telegram_payment_account_id = "synthetic-telegram-account"
    other_admin = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        admin=True,
    )
    unrelated = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        admin=True,
    )
    allowed = frozenset((env["admin"].telegram_id, other_admin.telegram_id))
    config.admin.browser_paid_order_telegram_recipients = allowed
    config.admin.business_order_telegram_recipients = allowed
    mobile_app = app(env, container)
    endpoint = "/miniapp/api/financial/orders"
    payload = body(env) | {
        "position_count": 10,
        "accompaniment_ordinals": None,
        "consultation_requested": True,
    }
    payload.pop("contact_reference")
    link_key = "checkout_url" if combined else "consultation_url"
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
        assert result["combined_checkout"] is combined
        if combined:
            assert result["consultation_url"] is None
        token = UUID(urlsplit(result[link_key]).fragment)
        selected = await client.post(
            f"{endpoint}/{result['order_id']}/selection", json=signed
        )
        assert selected.status_code == 200, selected.text
        assert selected.json()[link_key] == result[link_key]
        assert (await client.post(endpoint, json=payload)).json() == result
        conflict = await client.post(
            endpoint, json=payload | {"consultation_requested": False}
        )
        assert conflict.status_code == 409

    order_id = UUID(result["order_id"])
    messenger = AsyncMock()
    if combined:
        # Simulate legacy delivery jobs expanded before the scheduler update.
        async with container.transaction_manager.transaction() as db:
            old_job = await consultation_notices().claim(
                datetime.now(UTC), tuple(allowed), session=db
            )
        assert old_job.order_id == order_id and old_job.event_kind == "created"
    separate = container.build_consultation_notice_delivery(messenger)
    assert not await separate.run_once()
    messenger.send_text.assert_not_awaited()
    cards = container.build_order_notice_delivery(messenger)

    created_cards = await _business_cards(cards, messenger, order_id)
    _assert_created_cards(created_cards, allowed)
    messenger.send_text.reset_mock()

    receipt = scoped_rows(env, "order_intake_receipts", order_id)[0]
    assert str(token) not in str(receipt)
    lead = scoped_rows(env, "accompaniment_leads", order_id)[0]
    assert lead["contact_reference"] == f"telegram:{env['user'].telegram_id}"
    checkout = (
        container.build_browser_checkout()
        if combined
        else container.build_consultation_checkout()
    )
    invoice_id = f"in-{uuid4()}"
    hosted = "https://yookassa.ru/my/i/consultation"
    payment_id = str(uuid4())
    gateway = AsyncMock()
    checkout.gateway = gateway
    with pytest.raises(LookupError):
        await checkout.buyer_view(uuid4())
    if combined:
        with pytest.raises(LookupError):
            await container.build_consultation_checkout().buyer_view(token)
        assert len(scoped_rows(env, "browser_only_orders", order_id)) == 1
    if combined:
        owned_link = await checkout.view(
            order_id, client_id=env["user"].user_id
        )
        foreign_link = await checkout.view(order_id, client_id=uuid4())
        assert owned_link["url"] == result["checkout_url"]
        assert foreign_link["url"] is None
        assert await checkout.view(uuid4()) is None
    assert (await checkout.buyer_view(token))["state"] == "available"
    gateway.observe.return_value = BrowserInvoice(invoice_id, "pending", hosted)
    await checkout.start(token, "buyer@example.test")
    attempt = gateway.observe.call_args.args[0]
    amount_minor = 2200000 if combined else 500000
    assert attempt.request["payment_data"]["amount"] == {
        "value": "22000.00" if combined else "5000.00",
        "currency": "RUB",
    }
    assert (
        attempt.request["payment_data"]["receipt"]["customer"]["email"]
        == "buyer@example.test"
    )
    if combined:
        assert [
            line["amount"]["value"]
            for line in attempt.request["payment_data"]["receipt"]["items"]
        ] == ["5000.00", "12000.00", "5000.00"]
        assert len(attempt.request["cart"]) == 3
    await checkout.start(token, "buyer@example.test")
    gateway.observe.assert_awaited_once()
    assert (await checkout.buyer_view(token))["url"] == hosted
    attempts = BROWSER_ATTEMPTS if combined else CONSULTATION_ATTEMPTS

    def clear_cooldown():
        with Session(env["pg"]) as db, db.begin():
            db.execute(
                update(attempts)
                .where(attempts.c.order_id == order_id)
                .values(next_check_at=datetime.now(UTC))
            )

    clear_cooldown()
    if combined:
        gateway.observe.return_value = BrowserInvoice(
            invoice_id,
            "paid",
            payment=BrowserPayment(
                invoice_id, payment_id, "123", 1700000, datetime.now(UTC)
            ),
        )
        assert await checkout.run_once(order_id)
        assert (await checkout.buyer_view(token))["state"] == "review"
        (unconfirmed,) = scoped_rows(env, "payments", order_id)
        assert unconfirmed["captured_minor"] is None
        clear_cooldown()
    gateway.observe.return_value = BrowserInvoice(
        invoice_id,
        "paid",
        payment=BrowserPayment(
            invoice_id, payment_id, "123", amount_minor, datetime.now(UTC)
        ),
    )
    assert await checkout.run_once(order_id)
    assert (await checkout.buyer_view(token))["state"] == "paid"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mobile_app),
        base_url="http://testserver",
    ) as client:
        paid_selection = await client.post(
            f"{endpoint}/{order_id}/selection", json=signed
        )
    assert paid_selection.status_code == 200, paid_selection.text
    assert paid_selection.json()["consultation_state"] == "paid"
    assert "consultation_url" not in paid_selection.json()
    assert "consultation_token" not in paid_selection.json()
    order = await env["repos"]["order_repo"].get_by_id(order_id)
    quote = await container.build_order_notice_details_service().for_order(
        order
    )
    assert quote["consultation_state"] == "paid"
    assert quote["total_minor"] == 1700000
    if combined:
        assert paid_selection.json()["checkout_paid"] is True
        assert "checkout_url" not in paid_selection.json()
        (payment,) = scoped_rows(env, "payments", order_id)
        assert payment["captured_minor"] == 1700000
        (attempt,) = scoped_rows(env, "browser_checkout_attempts", order_id)
        assert attempt["amount_minor"] == 2200000
        assert attempt["state"] == "paid"
        assert (
            scoped_rows(env, "consultation_checkout_attempts", order_id) == []
        )
        actor = CheckoutActor(
            env["user"].user_id, "telegram", env["user"].telegram_id
        )
        status = await mobile_app.state.dispatcher["checkout_service"].status(
            order_id, actor
        )
        assert status["capture_state"] == "confirmed"
        async with container.transaction_manager.transaction() as db:
            event = await db.scalar(
                select(OutboxEventModel).where(
                    OutboxEventModel.aggregate_id == str(order_id),
                    OutboxEventModel.event_type
                    == "financial.client_snapshot_requested",
                )
            )
            facts = await SqlAlchemyClientEntitlementRepository().load_capture(
                event, session=db
            )
            assert facts.payment_id == payment["payment_id"]
        captured_at = attempt["captured_at"]
        proof = BrowserPayment(
            invoice_id, payment_id, "123", amount_minor, captured_at
        )
        async with container.transaction_manager.transaction() as db:
            with pytest.raises(
                OrderCreationError,
                match="combined_consultation_allocation_mismatch",
            ):
                await checkout.repository.capture.capture_browser(
                    order_id,
                    actor.user_id,
                    proof,
                    session=db,
                    consultation_minor=1,
                )
            with pytest.raises(
                OrderCreationError, match="browser_capture_proof_required"
            ):
                from dataclasses import replace

                await checkout.repository.capture.capture_browser(
                    order_id,
                    actor.user_id,
                    replace(proof, amount_minor=1700000),
                    session=db,
                    consultation_minor=500000,
                )
        migration = import_module(
            "ugc_bot.infrastructure.db.migrations.versions.0153_combined_checkout"
        )
        with env["pg"].connect() as db:
            monkeypatch.setattr(migration.op, "get_bind", lambda: db)
            with pytest.raises(RuntimeError, match="existing orders"):
                migration.downgrade()
        env["clock"].at = datetime.fromisoformat(
            result["selection_due_at"]
        ) + timedelta(seconds=1)
        refund_order = SimpleNamespace(
            order_id=order_id,
            items=[
                SimpleNamespace(paid_item_id=UUID(item["paid_item_id"]))
                for item in result["items"]
            ],
        )
        refunds = ApprovalRuntime(
            env, {"order": refund_order, "client": env["user"].user_id}
        )
        requested = await refunds.execute(await refunds.request())
        approved = await refunds.execute(refunds.review(requested))
        assert approved.get("approval_id")
    else:
        await checkout.start(token, "buyer@example.test")
        assert scoped_rows(env, "payments", order_id) == []
        assert scoped_rows(env, "financial_obligations", order_id) == []
        assert (
            len(scoped_rows(env, "consultation_checkout_attempts", order_id))
            == 1
        )
    assert gateway.observe.await_count == (3 if combined else 2)

    for _ in range(0 if combined else 2):
        assert await separate.run_once()
    assert not await separate.run_once()
    standalone = [call.kwargs for call in messenger.send_text.await_args_list]
    with Session(env["pg"]) as db:
        actual = (
            db.execute(
                select(CONSULTATION_DELIVERIES).where(
                    CONSULTATION_DELIVERIES.c.order_id == order_id
                )
            )
            .mappings()
            .all()
        )
    expected_kind, expected_state = (
        ("created", "failed") if combined else ("paid", "sent")
    )
    assert {
        (row["event_kind"], row["recipient"], row["state"]) for row in actual
    } == {(expected_kind, recipient, expected_state) for recipient in allowed}
    if combined:
        assert all(
            row["last_error"] == "included_in_business_order_card"
            for row in actual
        )
    assert {card["chat_id"] for card in standalone} == (
        set() if combined else allowed
    )

    paid_cards = await _business_cards(cards, messenger, order_id)
    if combined:
        _assert_paid_cards(paid_cards, allowed)
    else:
        assert paid_cards == []
    assert all(
        str(token) not in card["text"] for card in standalone + paid_cards
    )
    assert not any(
        card["chat_id"] == unrelated.telegram_id
        for card in created_cards + standalone + paid_cards
    )


@pytest.mark.asyncio
async def test_city_lookup_requires_signed_buyer_session(intake_env):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    env = intake_env
    mobile_app = app(env, env["container"])
    resolver = AsyncMock(side_effect=[("Казань", "Татарстан", "ru"), None])
    mobile_app.state.dispatcher["blogger_registration_service"] = (
        SimpleNamespace(resolve_city_identity=resolver)
    )
    signed = body(env)["init_data"]
    endpoint = "/miniapp/api/financial/orders/city"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mobile_app),
        base_url="http://testserver",
    ) as client:
        denied = await client.post(
            endpoint, json={"init_data": "invalid", "city": "Казань"}
        )
        assert denied.status_code == 401
        resolver.assert_not_awaited()
        found = await client.post(
            endpoint, json={"init_data": signed, "city": " Казанб "}
        )
        assert found.status_code == 200
        assert found.json() == {
            "city": "Казань",
            "region": "Татарстан",
            "country": "ru",
        }
        resolver.assert_awaited_once_with("Казанб")
        missing = await client.post(
            endpoint, json={"init_data": signed, "city": "Неизвестный город"}
        )
        assert missing.status_code == 404
        assert missing.json()["detail"] == "intake_city_not_found"


@pytest.mark.asyncio
async def test_checkout_gate_and_company_invoice_use_verified_contact(
    intake_env,
):
    from datetime import datetime
    from uuid import UUID

    env = intake_env
    env["config"].financial.combined_checkout_enabled = True
    mobile_app = app(env, env["container"])
    payload = body(env)
    endpoint = "/miniapp/api/financial/orders"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mobile_app),
        base_url="http://testserver",
    ) as client:
        policies = await client.post(
            endpoint + "/policies", json={"init_data": payload["init_data"]}
        )
        assert policies.json()["writes_paused"] is True
        blocked = await client.post(endpoint, json=payload)
        assert blocked.status_code == 503
        assert blocked.json()["detail"] == "combined_checkout_unavailable"

        env["config"].financial.combined_checkout_enabled = False
        response = await client.post(endpoint, json=payload)
        assert response.status_code == 200, response.text
        order_id = response.json()["order_id"]
        request = {
            "init_data": payload["init_data"],
            "order_id": order_id,
            "reason": "Please issue an invoice for this order",
            "operation_key": f"invoice-{uuid4()}",
        }
        support_endpoint = "/miniapp/api/customer/support"
        created = await client.post(support_endpoint, json=request)
        assert created.status_code == 200, created.text
        replay = await client.post(support_endpoint, json=request)
        assert replay.status_code == 200
        first, repeated = created.json(), replay.json()
        assert datetime.fromisoformat(
            first.pop("created_at")
        ) == datetime.fromisoformat(repeated.pop("created_at"))
        assert first == repeated
    (stored,) = scoped_rows(env, "customer_requests", UUID(order_id))
    assert (
        stored["payload"]["contact_reference"]
        == f"telegram:{env['user'].telegram_id}"
    )


def test_unused_combined_checkout_schema_can_be_reverted(monkeypatch):
    from importlib import import_module
    from os import environ

    from sqlalchemy import text

    from tests.helpers.financial_environment import isolated_financial_database

    migration = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0153_combined_checkout"
    )
    with (
        isolated_financial_database(
            environ["FINANCIAL_TEST_DATABASE_URL"]
        ) as engine,
        engine.begin() as db,
    ):
        monkeypatch.setattr(migration.op, "get_bind", lambda: db)
        guard_states = text("""
            SELECT tgname FROM pg_trigger
            WHERE tgrelid IN ('browser_checkout_attempts'::regclass,
                'consultation_checkout_attempts'::regclass)
              AND tgname IN ('browser_package_amount_guard',
                'consultation_package_channel_guard')
            ORDER BY tgname
        """)
        expected = [
            "browser_package_amount_guard",
            "consultation_package_channel_guard",
        ]
        assert db.scalars(guard_states).all() == expected
        migration.downgrade()
        assert not db.scalars(guard_states).all()
        assert "combined_checkout" not in db.scalar(
            text(
                "SELECT prosrc FROM pg_proc WHERE "
                "oid='correction_validate_authority(jsonb)'::regprocedure"
            )
        )
        migration.upgrade()
        assert db.scalars(guard_states).all() == expected
