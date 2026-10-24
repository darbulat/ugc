"""Signed admin commands use current stored authority and immutable results."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.application.services.test_rate_override_commands import START, setup
from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import create_test_user
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.miniapp.api import router


@pytest_asyncio.fixture
async def override_api(user_repo):
    repo, service, clock, admin, other, recipient = setup()
    identities = {}
    for index, uid in enumerate((admin, other, recipient), start=30):
        identities[uid] = await create_test_user(
            user_repo, user_id=uid, external_id=str(index)
        )
        repo.users[uid] = replace(repo.users[uid], telegram_id=str(index))
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"),
        max_bot=None,
        financial=SimpleNamespace(core_enabled=True),
    )
    app.state.dispatcher = {
        "user_role_service": UserRoleService(user_repo),
        "rate_override_service": service,
        "transaction_manager": repo,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield SimpleNamespace(
            client=client,
            app=app,
            repo=repo,
            clock=clock,
            admin=admin,
            other=other,
            recipient=recipient,
            identities=identities,
        )


def auth(env, uid):
    return {
        "init_data": generate_init_data(
            "test-token", int(env.identities[uid].telegram_id), "admin"
        )
    }


def create(env, uid=None, **changes):
    return {
        **auth(env, uid or env.admin),
        "action": "create",
        "operation_key": "create:api",
        "recipient_id": str(env.recipient),
        "side": "client",
        "policy_version": "approved:test",
        "reason": "individual agreed rate",
        "rate_bps": 1500,
        "effective_from": (START + timedelta(days=1)).isoformat(),
        "effective_until": (START + timedelta(days=30)).isoformat(),
        **changes,
    }


PATH = "/miniapp/api/admin/rate-overrides"


@pytest.mark.asyncio
async def test_admin_create_replay_read_supersede_revoke(override_api):
    env = override_api
    response = await env.client.post(PATH + "/command", json=create(env))
    assert response.status_code == 200
    first = response.json()
    assert first["override"]["approval"]["approved_by"] == str(env.admin)
    assert first["override"]["approval"]["rate_bps"] == 1500
    assert (
        await env.client.post(PATH + "/command", json=create(env))
    ).json() == first
    oid = first["override"]["approval"]["override_id"]
    read = await env.client.post(
        PATH + f"/{oid}/status", json=auth(env, env.admin)
    )
    assert read.status_code == 200
    assert read.json() == first["override"]
    listed = await env.client.post(
        PATH + "/list",
        json={
            **auth(env, env.admin),
            "recipient_id": str(env.recipient),
            "side": "client",
            "policy_version": "approved:test",
        },
    )
    assert listed.status_code == 200
    assert listed.json() == [first["override"]]
    supersede = create(
        env,
        action="supersede",
        operation_key="supersede:api",
        override_id=oid,
        expected_version=1,
        rate_bps=1800,
        effective_from=(START + timedelta(days=10)).isoformat(),
    )
    replaced = await env.client.post(PATH + "/command", json=supersede)
    assert replaced.status_code == 200
    replacement = replaced.json()["replacement"]
    assert replacement["approval"]["rate_bps"] == 1800
    revoke = {
        **auth(env, env.other),
        "action": "revoke",
        "operation_key": "revoke:api",
        "recipient_id": str(env.recipient),
        "side": "client",
        "policy_version": "approved:test",
        "reason": "agreement ended",
        "expected_version": 1,
        "override_id": replacement["approval"]["override_id"],
        "effective_at": (START + timedelta(days=20)).isoformat(),
    }
    revoked = await env.client.post(PATH + "/command", json=revoke)
    assert revoked.status_code == 200
    assert revoked.json()["override"]["version"] == 2
    assert len(env.repo.commands) == 3
    assert len(env.repo.events) == 4


@pytest.mark.asyncio
async def test_nonadmin_current_demotion_and_forged_actor_denied(override_api):
    env = override_api
    result = await env.client.post(
        PATH + "/command", json=create(env, env.recipient)
    )
    assert result.status_code == 403
    forged = await env.client.post(
        PATH + "/command",
        json=create(env, env.recipient, actor_id=str(env.admin)),
    )
    assert forged.status_code == 422
    first = await env.client.post(PATH + "/command", json=create(env))
    oid = first.json()["override"]["approval"]["override_id"]
    env.repo.users[env.admin] = replace(
        env.repo.users[env.admin], is_admin=False
    )
    assert (
        await env.client.post(PATH + "/command", json=create(env))
    ).status_code == 403
    assert (
        await env.client.post(
            PATH + f"/{oid}/status", json=auth(env, env.admin)
        )
    ).status_code == 403
    assert (
        await env.client.post(
            PATH + "/list",
            json={
                **auth(env, env.admin),
                "recipient_id": str(env.recipient),
                "side": "client",
                "policy_version": "approved:test",
            },
        )
    ).status_code == 403
    assert len(env.repo.commands) == 1


@pytest.mark.asyncio
async def test_invalid_conflicting_and_unknown_commands_are_explicit(
    override_api,
):
    env = override_api
    for changes in (
        {"rate_bps": True},
        {"rate_bps": 10001},
        {"reason": ""},
        {"effective_from": "2026-10-24T00:00:00"},
        {"action": "approve"},
        {"approved_by": str(env.admin)},
        {"approved_at": START.isoformat()},
        {"is_admin": True},
    ):
        assert (
            await env.client.post(
                PATH + "/command", json=create(env, **changes)
            )
        ).status_code == 422
    assert (
        await env.client.post(PATH + "/command", json=create(env, reason="   "))
    ).status_code == 409
    assert not env.repo.commands
    assert (
        await env.client.post(PATH + "/command", json=create(env))
    ).status_code == 200
    assert (
        await env.client.post(
            PATH + "/command", json=create(env, rate_bps=1700)
        )
    ).status_code == 409
    assert (
        await env.client.post(
            PATH + f"/{uuid4()}/status", json=auth(env, env.admin)
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_disabled_missing_service_and_expired_session_refuse_mutation(
    override_api,
):
    from tests.unit.test_miniapp_session_freshness import signed

    env = override_api
    env.app.state.config.financial.core_enabled = False
    assert (
        await env.client.post(PATH + "/command", json=create(env))
    ).status_code == 503
    env.app.state.config.financial.core_enabled = True
    del env.app.state.dispatcher["rate_override_service"]
    assert (
        await env.client.post(PATH + "/command", json=create(env))
    ).status_code == 503
    assert (
        await env.client.post(
            PATH + "/command", json=create(env, init_data="forged")
        )
    ).status_code == 401
    assert (
        await env.client.post(
            PATH + "/command",
            json=create(env, init_data=signed(bot_token="test-token")),
        )
    ).status_code == 401
    assert not env.repo.commands
