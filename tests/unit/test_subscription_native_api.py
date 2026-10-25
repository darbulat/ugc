"""Subscription ingress never returns private service or resolver failures."""

from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.subscription_api import create_subscription_router

ACTOR = UUID(int=1)
PROOF = AuthenticatedMessengerPrincipal(ACTOR, "telegram", "native-admin")
SIGNED = dict(init_data="PRIVATE SIGNED PROOF", platform="telegram")


class Service:
    def __init__(self):
        self.calls = []
        self.error = None

    async def view(self, actor_id, *, principal):
        if self.error is not None:
            raise self.error
        self.calls.append((actor_id, principal))
        return dict(actor_id=str(actor_id), automatic_billing=False)

    async def execute(self, actor_id, action, key, payload, *, principal):
        if self.error is not None:
            raise self.error
        self.calls.append((actor_id, action, key, payload, principal))
        return dict(
            state="accepted",
            automatic_billing=False,
            **{
                name: payload[name]
                for name in ("price_minor", "amount_minor")
                if name in payload
            },
        )


def application(error=None, principal=PROOF):
    service = Service()

    async def resolve(request, init_data, *, platform):
        if error is not None:
            raise error
        return principal

    app = FastAPI()
    app.include_router(create_subscription_router(resolve))
    app.state.dispatcher = dict(subscription_service=service)
    return app, service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        PermissionError("PRIVATE bank evidence"),
        HTTPException(401, {"token": "PRIVATE secret"}),
    ],
)
async def test_private_failures_are_sanitized_without_echo(error):
    app, service = application(
        error if isinstance(error, HTTPException) else None
    )
    if not isinstance(error, HTTPException):
        service.error = error
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post("/subscriptions/view", json=SIGNED)
    assert result.status_code == 503
    assert result.json() == {"detail": "subscription_unavailable"}
    assert (
        "PRIVATE" not in result.text
        and result.headers["cache-control"] == "no-store"
    )


def tariff():
    return dict(
        **SIGNED,
        operation_key="publish",
        reason="Reviewed tariff",
        version="v1",
        title="Manager",
        price_minor="9007199254740993",
        duration_days=30,
        campaign_limit=5,
        recipient_limit=100,
        terms_reference="published:terms",
    )


def payment():
    return dict(
        **SIGNED,
        operation_key="payment",
        reason="Reviewed bank receipt",
        member_id=str(UUID(int=2)),
        tariff_version="v1",
        amount_minor="9007199254740993",
        currency="RUB",
        paid_at="2026-10-25T00:00:00+00:00",
        payment_reference="bank:1",
        evidence_reference="bank-statement:1",
        evidence_hash="a" * 64,
        pilot=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,body,action",
    [
        ("tariffs", tariff(), "publish"),
        ("payments", payment(), "accept_payment"),
        (
            "cancel",
            dict(**SIGNED, operation_key="cancel", reason="Stop"),
            "cancel",
        ),
        (
            "automation",
            dict(
                **SIGNED,
                operation_key="automation",
                reason="Pilots reviewed",
                evidence_reference="pilots:1",
                evidence_hash="b" * 64,
            ),
            "enable_automation",
        ),
    ],
)
async def test_signed_actions_use_native_actor_and_exact_minor_strings(
    path, body, action
):
    app, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post("/subscriptions/" + path, json=body)
    assert result.status_code == 200, result.text
    actor, recorded_action, key, payload, principal = service.calls[0]
    assert actor == ACTOR and principal is PROOF and recorded_action == action
    assert (
        key == body["operation_key"]
        and "actor_id" not in payload
        and "init_data" not in payload
    )
    for name in ("price_minor", "amount_minor"):
        if name in body:
            assert (
                payload[name] == 9007199254740993 and type(payload[name]) is int
            )
            assert result.json()[name] == body[name]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", [True, 12300, 1.5, "1.5", "01", "-1", "0", "9223372036854775808"]
)
async def test_money_wire_rejects_noncanonical_or_out_of_range_values(value):
    app, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/subscriptions/tariffs", json=tariff() | {"price_minor": value}
        )
    assert (
        result.status_code == 422
        and service.calls == []
        and "PRIVATE" not in result.text
    )


@pytest.mark.asyncio
async def test_untrusted_identity_and_missing_service_fail_closed():
    app, service = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post(
                "/subscriptions/view?actor_id=forged", json=SIGNED
            )
        ).status_code == 422
        assert (
            await client.post(
                "/subscriptions/tariffs",
                json=tariff() | {"actor_id": str(ACTOR)},
            )
        ).status_code == 422
        app.state.dispatcher = {}
        assert (
            await client.post("/subscriptions/view", json=SIGNED)
        ).status_code == 503
    assert service.calls == []
    app, _ = application(principal=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/subscriptions/view", json=SIGNED)
        ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,detail",
    [
        (
            PermissionError("subscription_current_admin_required"),
            403,
            "subscription_current_admin_required",
        ),
        (
            ValueError("financial_principal_changed"),
            403,
            "financial_principal_changed",
        ),
        (
            ValueError("PRIVATE invalid evidence"),
            409,
            "subscription_operation_rejected",
        ),
        (
            LookupError("PRIVATE source missing"),
            409,
            "subscription_operation_rejected",
        ),
        (
            RuntimeError("PRIVATE internal state"),
            503,
            "subscription_unavailable",
        ),
    ],
)
async def test_known_authority_errors_and_unknown_service_failures_are_safe(
    error, status, detail
):
    app, service = application()
    service.error = error
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post("/subscriptions/view", json=SIGNED)
    assert result.status_code == status and result.json() == {"detail": detail}
    assert "PRIVATE" not in result.text
