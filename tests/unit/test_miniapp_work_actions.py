"""UI capabilities follow current roles, deadlines and actual work state."""

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.test_miniapp_collaborations import (
    auth,
    command,
    start,
)
from tests.unit.test_miniapp_collaborations import (
    work_client as _work_client,
)

work_client = _work_client


async def view(env, actor):
    client, scope, _, _, users, _ = env
    return await client.post(
        f"/miniapp/api/collaborations/{scope.assignment_id}/status",
        json=auth(users, actor),
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("work_client")
async def test_current_party_and_manager_actions_follow_claimant(request):
    env = request.getfixturevalue("work_client")
    _, scope, _, _, _, _ = env
    await start(env)
    creator = (await view(env, scope.creator_id)).json()
    assert creator["actor_id"] == str(scope.creator_id)
    assert creator["is_current"] is True
    assert creator["allowed_actions"] == ["claim"]
    manager = (await view(env, scope.manager_id)).json()
    assert set(manager["allowed_actions"]) == {"request_confirmation"}
    claim = await command(
        env, scope.creator_id, "claim", 2, evidence="real proof"
    )
    assert claim.status_code == 200
    assert claim.json()["allowed_actions"] == []
    client = (await view(env, scope.client_id)).json()
    assert set(client["allowed_actions"]) == {"agree", "dispute", "extend_due"}
    assert (await view(env, scope.manager_id)).json()["allowed_actions"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("work_client")
async def test_exact_claim_and_dispute_boundaries_hide_ineligible_actions(
    request,
):
    env = request.getfixturevalue("work_client")
    _, scope, clock, _, _, _ = env
    await start(env)
    clock.at += timedelta(days=16)
    assert (await view(env, scope.creator_id)).json()["allowed_actions"] == []
    clock.at -= timedelta(days=16)
    await command(env, scope.creator_id, "claim", 2, evidence="real proof")
    clock.at += timedelta(hours=72)
    client = (await view(env, scope.client_id)).json()
    assert "dispute" not in client["allowed_actions"]
    assert "agree" in client["allowed_actions"]
    final = await command(env, scope.client_id, "agree", 3)
    assert final.json()["allowed_actions"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("work_client")
async def test_history_and_removed_roles_cannot_offer_actions(request):
    env = request.getfixturevalue("work_client")
    _, scope, clock, repo, _, _ = env
    await start(env)
    repo.scopes[scope.assignment_id] = replace(scope, valid_to=clock.at)
    historical = (await view(env, scope.client_id)).json()
    assert historical["is_current"] is False
    assert historical["allowed_actions"] == []
    repo.scopes[scope.assignment_id] = scope
    repo.actors[scope.creator_id] = replace(
        repo.actors[scope.creator_id], is_creator=False
    )
    assert (await view(env, scope.creator_id)).status_code == 403
