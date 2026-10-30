"""Signed gateways carry financial proof and sanitize protected errors."""

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from tests.application.services.test_rate_override_commands import START, setup
from tests.e2e.miniapp_helpers import generate_init_data
from tests.unit.test_financial_native_principal import (
    PayoutFacts,
    Roles,
    payout,
)


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


def application(platform, *, override=False):
    from ugc_bot.miniapp.financial_principal import resolve_financial_principal
    from ugc_bot.miniapp.override_api import create_override_router
    from ugc_bot.miniapp.payout_api import create_payout_router

    uid = uuid4()
    facts = PayoutFacts(uid)
    facts.facts["telegram_id"] = facts.facts["max_id"] = "changed"
    service, tx = payout(facts), Transactions()
    if override:
        facts, service, _, uid, _, _ = setup()
        facts.users[uid] = replace(
            facts.users[uid], telegram_id="changed", max_id="changed"
        )
        tx = facts
    roles = Roles(
        SimpleNamespace(
            user_id=uid, telegram_id="123", max_id="123", country=None
        )
    )
    app = FastAPI()
    app.include_router(
        (create_override_router if override else create_payout_router)(
            resolve_financial_principal
        )
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="synthetic-tg"),
        max_bot=SimpleNamespace(token="synthetic-max"),
        financial=SimpleNamespace(core_enabled=True, payouts_enabled=True),
    )
    app.state.dispatcher = dict(
        user_role_service=roles,
        payout_service=service,
        rate_override_service=service,
        transaction_manager=tx,
    )
    auth = dict(
        platform=platform,
        init_data=generate_init_data(
            "synthetic-tg" if platform == "telegram" else "synthetic-max",
            123,
            "Synthetic",
        ),
    )
    return app, facts, auth


# Parametrized cases are collected independently by each xdist worker.
REF = "00000000-0000-4000-8000-000000000001"
PAYOUT_PATHS = (
    (
        "/admin/requirements/publish",
        dict(
            operation_key="publish",
            expected_version=0,
            effective_from=START.isoformat(),
            legal_reference="Synthetic",
            terms_reference="Synthetic",
            evidence_reference="Synthetic",
            reason="Synthetic",
            required_fields=["bank_account"],
            enabled=True,
        ),
    ),
    (
        "/requisites",
        dict(
            operation_key="store",
            requirements_id=REF,
            accepted_terms_reference="Synthetic",
            details={"bank_account": "Synthetic"},
        ),
    ),
    (
        "/request",
        dict(operation_key="request", requisites_id=REF, amount_minor="100"),
    ),
    (
        "/admin/command",
        dict(
            operation_key="review",
            request_id=REF,
            expected_version=1,
            action="review",
            reason="Synthetic",
        ),
    ),
    (
        "/admin/result",
        dict(
            operation_key="result",
            request_id=REF,
            execution_id=REF,
            fence=REF,
            expected_version=1,
            status="unknown",
            reason="Synthetic",
            evidence_reference="Synthetic",
            evidence_hash="a" * 64,
        ),
    ),
    ("/requirements", {}),
    ("/list", {}),
    ("/admin/queue", {}),
    ("/admin/requirements", {}),
    (f"/admin/{REF}/history", {}),
    (
        f"/admin/{REF}/requisites",
        dict(operation_key="reveal", reason="Synthetic"),
    ),
    ("/operations/status", dict(operation_key="recover")),
    ("/requisites/list", {}),
    (f"/{REF}/status", {}),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("path,body", PAYOUT_PATHS)
async def test_each_signed_payout_path_supplies_native_proof(
    platform, path, body
):
    app, facts, auth = application(platform)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/payouts" + path, json=auth | body)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "financial_principal_changed"}
    assert response.headers["cache-control"] == "no-store"
    assert "receipt" not in facts.events


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("path", ["/command", "/list", f"/{REF}/status"])
async def test_each_override_admin_path_supplies_native_proof(platform, path):
    from tests.unit.test_miniapp_rate_overrides import create

    app, facts, auth = application(platform, override=True)
    admin, _, recipient = facts.users
    env = SimpleNamespace(
        admin=admin,
        recipient=recipient,
        identities={admin: SimpleNamespace(telegram_id="123")},
    )
    body = create(env) | auth if path == "/command" else auth
    if path == "/list":
        body = auth | dict(
            recipient_id=str(recipient),
            side="client",
            policy_version="approved:test",
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/admin/rate-overrides" + path, json=body)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "financial_principal_changed"}
    assert response.headers["cache-control"] == "no-store"
    assert not facts.commands and not facts.events


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [False, True])
async def test_validation_never_echoes_signed_input_or_private_fields(override):
    app, _, auth = application("telegram", override=override)
    path = "/admin/rate-overrides/command" if override else "/payouts/request"
    private = "SYNTHETIC_PRIVATE_VALIDATION"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            path,
            json=auth
            | dict(details={"bank_account": private}, rate_bps=private),
        )
    assert response.status_code == 422
    assert response.json() == {
        "detail": "override_request_invalid"
        if override
        else "payout_request_invalid"
    }
    assert response.headers["cache-control"] == "no-store"
    assert (
        private not in response.text and auth["init_data"] not in response.text
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,expected,status",
    [
        ("override_version_conflict", "override_version_conflict", 409),
        ("SYNTHETIC_PRIVATE_FAILURE", "override_unavailable", 503),
        ("override_private_failure", "override_unavailable", 503),
    ],
)
async def test_override_error_mapping_is_exact_constant_and_uncacheable(
    code, expected, status, caplog
):
    app, facts, auth = application("telegram", override=True)

    async def broken(*args, **kwargs):
        raise ValueError(code)

    app.state.dispatcher["rate_override_service"] = SimpleNamespace(
        get_for_admin=broken
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/admin/rate-overrides/{REF}/status", json=auth
        )
    assert response.status_code == status
    assert response.json() == {"detail": expected}
    assert response.headers["cache-control"] == "no-store"
    assert auth["init_data"] not in response.text + caplog.text
    if status == 503:
        assert code not in response.text + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [False, True])
async def test_unexpected_http_errors_are_also_sanitized(override, caplog):
    from fastapi import APIRouter, HTTPException

    from ugc_bot.miniapp.override_api import NoStoreOverrideRoute
    from ugc_bot.miniapp.payout_api import NoStorePayoutRoute

    private = "SYNTHETIC_PRIVATE_HTTP_EXCEPTION"
    app = FastAPI()
    router = APIRouter(
        route_class=NoStoreOverrideRoute if override else NoStorePayoutRoute
    )

    @router.post("/synthetic")
    async def broken():
        raise HTTPException(400, private)

    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/synthetic")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "override_unavailable" if override else "payout_unavailable"
    }
    assert response.headers["cache-control"] == "no-store"
    assert private not in response.text + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_current_signed_account_recovery_preserves_identity(
    platform,
):
    app, facts, auth = application(platform)
    facts.facts["telegram_id"] = facts.facts["max_id"] = "123"
    facts.old = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/payouts/operations/status",
            json=auth | dict(operation_key="unused"),
        )
    assert response.status_code == 200, response.text
    assert response.json()["recorded"] is False
    assert app.state.dispatcher["user_role_service"].user.country is None
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [False, True])
async def test_signed_http_cannot_use_internal_optional_principal_compatibility(
    override,
):
    from ugc_bot.miniapp.override_api import create_override_router
    from ugc_bot.miniapp.payout_api import create_payout_router

    async def legacy_resolver(*args, **kwargs):
        return uuid4()

    app = FastAPI()
    app.include_router(
        (create_override_router if override else create_payout_router)(
            legacy_resolver
        )
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/admin/rate-overrides/list" if override else "/payouts/list",
            json=dict(
                init_data="synthetic",
                **(
                    dict(
                        recipient_id=REF,
                        side="client",
                        policy_version="approved:test",
                    )
                    if override
                    else {}
                ),
            ),
        )
    assert response.status_code == 401
    assert response.json() == {"detail": "financial_session_invalid"}
    assert response.headers["cache-control"] == "no-store"
