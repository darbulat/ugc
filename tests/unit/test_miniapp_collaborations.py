"""Signed lifecycle ingress uses current service ownership and transactions."""

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.application.services.test_collaboration_service import (
    setup_lifecycle,
)
from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import create_test_user
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.miniapp.api import router


@pytest_asyncio.fixture
async def work_client(user_repo):
    service, repo, scope, clock, _, stranger = setup_lifecycle()
    users = {}
    for index, actor in enumerate(
        (scope.client_id, scope.creator_id, scope.manager_id, stranger), start=1
    ):
        users[actor] = await create_test_user(
            user_repo, user_id=actor, external_id=str(index)
        )
    # Signed HTTP now checks the current native authority in the memory port.
    for actor, user in users.items():
        repo.actors[actor] = replace(
            repo.actors[actor], telegram_id=user.telegram_id, max_id=user.max_id
        )
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"),
        max_bot=None,
        financial=SimpleNamespace(core_enabled=True),
    )
    app.state.dispatcher = {
        "user_role_service": UserRoleService(user_repo),
        "collaboration_service": service,
        "transaction_manager": repo,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, scope, clock, repo, users, app


def auth(users, actor):
    return {
        "init_data": generate_init_data(
            "test-token", int(users[actor].telegram_id), "actor"
        )
    }


async def command(env, actor, action, version, **kwargs):
    client, scope, _, _, users, _ = env
    return await client.post(
        f"/miniapp/api/collaborations/{scope.assignment_id}/command",
        json={
            **auth(users, actor),
            "action": action,
            "operation_key": f"{action}:{version}",
            "expected_version": version,
            **kwargs,
        },
    )


async def start(env):
    _, scope, clock, _, _, _ = env
    assigned = await command(
        env,
        scope.client_id,
        "assign",
        0,
        due_at=(clock.at + timedelta(days=2)).isoformat(),
        terms_reference="agreed-brief:123",
    )
    assert assigned.status_code == 200
    begun = await command(env, scope.manager_id, "start", 1)
    assert begun.status_code == 200


@pytest.mark.asyncio
async def test_parties_can_assign_start_claim_and_reload_status(work_client):
    env = work_client
    client, scope, clock, _, users, _ = env
    await start(env)
    response = await command(
        env, scope.creator_id, "claim", 2, evidence="https://example.com/proof"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["record"]["collaboration"]["state"] == "success_claimed"
    assert data["record"]["version"] == 3
    assert data["available_at"] is None
    assert data["objection_deadline"] == (
        clock.at + timedelta(hours=72)
    ).isoformat().replace("+00:00", "Z")
    view = await client.post(
        f"/miniapp/api/collaborations/{scope.assignment_id}/status",
        json=auth(users, scope.client_id),
    )
    assert view.status_code == 200
    assert view.json()["record"] == data["record"]
    assert view.json()["actor_id"] == str(scope.client_id)
    assert set(view.json()["allowed_actions"]) == {
        "agree",
        "dispute",
        "extend_due",
    }


@pytest.mark.asyncio
async def test_foreign_actor_and_forged_system_authority_are_rejected(
    work_client,
):
    env = work_client
    client, scope, _, repo, users, _ = env
    stranger = next(
        x
        for x in users
        if x not in (scope.client_id, scope.creator_id, scope.manager_id)
    )
    view = await client.post(
        f"/miniapp/api/collaborations/{scope.assignment_id}/status",
        json=auth(users, stranger),
    )
    assert view.status_code == 403
    assert (await command(env, stranger, "start", 0)).status_code == 403
    for extra in (
        {"actor_id": str(scope.client_id)},
        {"system_actor": "collaboration_scheduler"},
    ):
        result = await command(env, scope.client_id, "start", 0, **extra)
        assert result.status_code == 422
    for action in ("notice", "advance"):
        result = await command(env, scope.client_id, action, 0)
        assert result.status_code == 422
    assert not repo.events


@pytest.mark.asyncio
async def test_claim_replay_preserves_first_notice_and_stale_version_conflicts(
    work_client,
):
    env = work_client
    _, scope, _, repo, _, _ = env
    await start(env)
    claim = dict(evidence="https://example.com/proof")
    first = await command(env, scope.creator_id, "claim", 2, **claim)
    replay = await command(env, scope.creator_id, "claim", 2, **claim)
    assert first.status_code == 200
    assert replay.json() == first.json()
    assert len(repo.notices) == 1
    stale = await command(env, scope.client_id, "agree", 2)
    assert stale.status_code == 409
    self_agree = await command(env, scope.creator_id, "agree", 3)
    assert self_agree.status_code == 409
    agreed = await command(env, scope.client_id, "agree", 3)
    assert agreed.status_code == 200
    assert agreed.json()["record"]["collaboration"]["state"] == "success_final"
    assert agreed.json()["available_at"] is not None


@pytest.mark.asyncio
async def test_manager_cannot_claim_and_dispute_requires_reason(work_client):
    env = work_client
    _, scope, _, repo, _, _ = env
    await start(env)
    result = await command(
        env, scope.manager_id, "claim", 2, evidence="own reward"
    )
    assert result.status_code == 403
    await command(env, scope.creator_id, "claim", 2, evidence="real proof")
    empty = await command(env, scope.client_id, "dispute", 3, reason="")
    assert empty.status_code == 422
    result = await command(
        env, scope.client_id, "dispute", 3, reason="Wrong content"
    )
    assert result.status_code == 200
    assert result.json()["record"]["collaboration"]["state"] == "disputed"
    assert not repo.schedules


@pytest.mark.asyncio
async def test_disabled_core_and_missing_service_fail_closed(work_client):
    env = work_client
    client, scope, _, _, users, app = env
    path = f"/miniapp/api/collaborations/{scope.assignment_id}/status"
    app.state.config.financial.core_enabled = False
    assert (
        await client.post(path, json=auth(users, scope.client_id))
    ).status_code == 503
    app.state.config.financial.core_enabled = True
    del app.state.dispatcher["collaboration_service"]
    assert (
        await client.post(path, json=auth(users, scope.client_id))
    ).status_code == 503
    assert (
        await client.post(path, json={"init_data": "forged"})
    ).status_code == 401


@pytest.mark.asyncio
async def test_expired_valid_signature_cannot_create_work_or_user(
    work_client, user_repo
):
    from tests.unit.test_miniapp_session_freshness import signed

    env = work_client
    client, scope, _, repo, _, _ = env
    before = dict(user_repo.users)
    response = await client.post(
        f"/miniapp/api/collaborations/{scope.assignment_id}/command",
        json={
            "init_data": signed(bot_token="test-token"),
            "action": "start",
            "operation_key": "old-session",
            "expected_version": 0,
        },
    )
    assert response.status_code == 401
    assert not repo.events
    assert user_repo.users == before
