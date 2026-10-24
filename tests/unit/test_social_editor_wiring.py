"""Actual main routes over explicitly synthetic social authority/storage."""

from dataclasses import replace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from tests.unit.test_social_editor_api import application
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType
from ugc_bot.miniapp.api import router


async def mounted(platform):
    direct, editor, user, envelope = await application(platform)
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = direct.state.config
    app.state.dispatcher = direct.state.dispatcher
    return app, editor, user, envelope


def operation(action, envelope):
    if action == "save":
        return "/miniapp/api/social/accounts/save", {
            **envelope,
            "network": "youtube",
            "url": "https://youtube.com/@creator",
        }
    if action == "remove":
        return "/miniapp/api/social/accounts/remove", {
            **envelope,
            "account_id": str(UUID(int=99)),
        }
    return "/miniapp/api/social/accounts", envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_main_social_routes_save_list_remove_with_existing_proof(
    platform,
):
    app, editor, user, envelope = await mounted(platform)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        path, body = operation("save", envelope)
        saved = await client.post(path, json=body)
        assert saved.status_code == 200, saved.text
        account = saved.json()["account"]
        assert account["user_id"] == str(user.user_id)
        assert account["platform"] == "youtube"
        assert account["verified"] is False
        assert saved.json()["next_platform"] == "tiktok"
        listed = await client.post(
            "/miniapp/api/social/accounts", json=envelope
        )
        assert listed.status_code == 200, listed.text
        assert [a["platform"] for a in listed.json()["accounts"]] == [
            "instagram",
            "youtube",
        ]
        assert listed.json()["next_platform"] == "tiktok"
        removed = await client.post(
            "/miniapp/api/social/accounts/remove",
            json={**envelope, "account_id": account["account_id"]},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json() == {"removed": True}
    for response in [saved, listed, removed]:
        assert response.headers["cache-control"] == "no-store"
    assert editor.storage.accounts == {}
    assert editor.starts == editor.commits == 3
    assert editor.rollbacks == 0
    assert (await editor.users.get_by_id(user.user_id)).country is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
async def test_main_social_unknown_identity_never_registers(platform, action):
    app, editor, user, envelope = await mounted(platform)
    envelope["init_data"] = generate_init_data(
        "test-token" if platform == "telegram" else "max-token",
        808,
        "unknown",
    )
    path, body = operation(action, envelope)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "existing_financial_account_required"}
    assert response.headers["cache-control"] == "no-store"
    messenger = (
        MessengerType.TELEGRAM if platform == "telegram" else MessengerType.MAX
    )
    assert await editor.users.get_by_external("808", messenger) is None
    assert set(editor.users.users) == {user.user_id}
    assert editor.starts == 0
    assert editor.storage.accounts == {}
    assert (await editor.users.get_by_id(user.user_id)).country is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
async def test_main_social_rechecks_native_mapping_after_lookup(
    platform, action
):
    app, editor, _, envelope = await mounted(platform)

    class RemappingRoles(UserRoleService):
        async def get_user(self, external_id, messenger_type):
            original = await super().get_user(external_id, messenger_type)
            if original is not None:
                await editor.users.save(
                    replace(original, **{platform + "_id": None})
                )
            return original

    # This deliberately synthetic lookup/transaction interleaving proves main
    # resolver forwarding; actual PostgreSQL ordering has separate tests.
    app.state.dispatcher["user_role_service"] = RemappingRoles(editor.users)
    path, body = operation(action, envelope)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "financial_principal_changed"}
    assert response.headers["cache-control"] == "no-store"
    assert editor.starts == editor.rollbacks == 1
    assert editor.commits == 0
    assert "facts" not in editor.events
    assert editor.storage.accounts == {}
