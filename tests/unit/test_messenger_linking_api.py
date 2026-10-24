"""Signed MAX linking never goes through automatic registration."""

import hashlib
import hmac
import importlib
import importlib.util
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qsl, urlencode

import httpx
import pytest
from fastapi import FastAPI

from tests.application.services.test_messenger_linking_service import setup
from tests.e2e.miniapp_helpers import generate_init_data


def application():
    name = "ugc_bot.miniapp.messenger_linking_api"
    assert importlib.util.find_spec(name) is not None, (
        "signed linking API missing"
    )
    module = importlib.import_module(name)
    service, repo, actor, _, _ = setup()
    app = FastAPI()
    app.include_router(
        module.create_messenger_linking_router(), prefix="/miniapp/api"
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=repo.users[actor.user_id]),
        set_user=AsyncMock(),
    )
    app.state.dispatcher = {
        "messenger_linking_service": service,
        "user_role_service": roles,
    }
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="tg-token"),
        max_bot=SimpleNamespace(token="max-token"),
    )
    return app, service, repo, actor, roles


def signed(**extra):
    return {
        "init_data": generate_init_data("max-token", 12345, "MAX Client"),
        "platform": "max",
        **extra,
    }


@pytest.mark.asyncio
async def test_real_max_hmac_create_and_status_expose_only_current_live_view():
    app, _, repo, actor, roles = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/miniapp/api/messenger-links/telegram/challenge",
            json=signed(operation_key="create"),
        )
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["state"] == "waiting" and body["launch_url"].startswith(
            "https://t.me/"
        )
        assert "launch_url" not in body["receipt"]
        current = await client.post(
            "/miniapp/api/messenger-links/telegram/status", json=signed()
        )
        assert current.json()["challenge_id"] == body["challenge_id"]
        assert repo.users[actor.user_id].telegram_id is None
    roles.set_user.assert_not_awaited()


@pytest.mark.parametrize(
    "case",
    [
        "wrong_token",
        "telegram",
        "stale",
        "future",
        "duplicate",
        "query",
        "extra",
        "missing_owner",
    ],
)
@pytest.mark.asyncio
async def test_bad_authority_or_unknown_owner_never_auto_creates(case):
    app, _, repo, _, roles = application()
    body = signed(operation_key="create")
    status = 401
    url = "/miniapp/api/messenger-links/telegram/challenge"
    if case == "wrong_token":
        body["init_data"] = generate_init_data("tg-token", 12345, "wrong")
    elif case == "telegram":
        body["platform"] = "telegram"
        status = 403
    elif case in {"stale", "future"}:
        offset = -3601 if case == "stale" else 61
        values = dict(parse_qsl(generate_init_data("max-token", 12345, "time")))
        values["auth_date"] = str(int(time.time()) + offset)
        values.pop("hash")
        secret = hmac.new(b"WebAppData", b"max-token", hashlib.sha256).digest()
        values["hash"] = hmac.new(
            secret,
            "\n".join(
                f"{key}={value}" for key, value in sorted(values.items())
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        body["init_data"] = urlencode(values)
    elif case == "duplicate":
        body["init_data"] += "&auth_date=1"
    elif case == "query":
        url += "?verified=true"
        status = 422
    elif case == "extra":
        body["telegram_id"] = "forged"
        status = 422
    else:
        roles.get_user.return_value = None
        status = 404
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(url, json=body)
    assert response.status_code == status, response.text
    assert not repo.challenges
    roles.set_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_max_view_exposes_claim_for_explicit_confirmation():
    from tests.application.services.test_messenger_linking_service import native

    app, service, _, actor, _ = application()
    waiting = await service.create(actor, "issue")
    receipt = await service.propose_native(native(waiting))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/miniapp/api/messenger-links/telegram/status", json=signed()
        )
    assert result.json().get("claim_id") == str(receipt.claim_id)
    assert result.json()["version"] == 2


@pytest.mark.asyncio
async def test_unexpected_value_error_never_echoes_private_proof():
    app, service, _, _, _ = application()
    service.status = AsyncMock(side_effect=ValueError("lk1_private-value"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/miniapp/api/messenger-links/telegram/status", json=signed()
        )
    assert result.status_code == 503
    assert "lk1_private" not in result.text


@pytest.mark.asyncio
async def test_live_views_and_rejected_inputs_are_not_cached_or_echoed():
    app, _, _, _, _ = application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for body, status in [
            (signed(operation_key="issue"), 200),
            (signed(operation_key="issue", token="lk1_private-bearer"), 422),
            (signed(operation_key="issue", platform="telegram"), 403),
        ]:
            response = await client.post(
                "/miniapp/api/messenger-links/telegram/challenge", json=body
            )
            assert response.status_code == status
            assert response.headers.get("cache-control") == "no-store"
            assert "lk1_private-bearer" not in response.text


@pytest.mark.asyncio
async def test_signed_confirm_replay_and_revoke_routes_preserve_safe_receipts():
    from tests.application.services.test_messenger_linking_service import native

    app, service, _, actor, _ = application()
    waiting = await service.create(actor, "issue")
    await service.propose_native(native(waiting))
    current = await service.status(actor)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        payload = signed(
            challenge_id=str(current.challenge_id),
            claim_id=str(current.claim_id),
            expected_version=current.version,
            operation_key="confirm",
        )
        confirmed = await client.post(
            "/miniapp/api/messenger-links/telegram/confirm", json=payload
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["state"] == "linked"
        repeated = await client.post(
            "/miniapp/api/messenger-links/telegram/confirm", json=payload
        )
        assert repeated.json() == confirmed.json()
    app, service, _, actor, _ = application()
    waiting = await service.create(actor, "other-issue")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        revoked = await client.post(
            "/miniapp/api/messenger-links/telegram/revoke",
            json=signed(
                challenge_id=str(waiting.challenge_id),
                expected_version=waiting.version,
                operation_key="revoke",
            ),
        )
    assert revoked.json()["state"] == "revoked"


@pytest.mark.parametrize(
    "missing", ["max_config", "roles", "binding", "system"]
)
@pytest.mark.asyncio
async def test_unavailable_current_principal_and_system_failure_never_echo(
    missing,
):
    from dataclasses import replace

    app, service, _, _, roles = application()
    expected = 503
    if missing == "max_config":
        app.state.config.max_bot = None
    elif missing == "roles":
        app.state.dispatcher["user_role_service"] = None
    elif missing == "binding":
        roles.get_user.return_value = replace(
            roles.get_user.return_value, max_id=None
        )
        expected = 404
    else:
        service.status = AsyncMock(side_effect=RuntimeError("lk1_private"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        result = await client.post(
            "/miniapp/api/messenger-links/telegram/status", json=signed()
        )
    assert result.status_code == expected
    assert "lk1_private" not in result.text
    assert result.headers["cache-control"] == "no-store"
