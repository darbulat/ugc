"""Signed feedback reads canonical profiles without account or code writes."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import create_test_user
from tests.helpers.social_editor import editor_fixture
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryAdvertiserProfileRepository,
)
from ugc_bot.miniapp.api import router

PATH = "/api/blogger/instagram-verification/status"
pytestmark = pytest.mark.asyncio


async def application(platform):
    editor, user, principal = await editor_fixture(
        platform=platform, confirmed=False
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(wraps=UserRoleService(editor.users).get_user),
        set_user=AsyncMock(side_effect=AssertionError("Unexpected user write")),
        set_country=AsyncMock(
            side_effect=AssertionError("Unexpected country write")
        ),
    )
    profiles = ProfileService(
        editor.users, editor.profiles, InMemoryAdvertiserProfileRepository()
    )
    app = FastAPI()
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"),
        max_bot=SimpleNamespace(token="max-token"),
    )
    app.state.dispatcher = {
        "user_role_service": roles,
        "profile_service": profiles,
    }
    app.include_router(router)
    envelope = {
        "platform": platform,
        "init_data": generate_init_data(
            "test-token" if platform == "telegram" else "max-token",
            int(principal.external_id),
            "synthetic_creator",
        ),
    }
    return app, editor, user, envelope, roles, profiles


@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_reads_latest_confirmation_and_keeps_storage_unchanged(platform):
    app, editor, user, body, roles, _ = await application(platform)
    users_before = deepcopy(editor.users.users)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        first = await client.post(PATH, json=body)
        assert first.status_code == 200 and first.json()["confirmed"] is False
        saved = await editor.profiles.get_by_user_id(user.user_id)
        await editor.profiles.save(replace(saved, confirmed=True))
        profiles_before = deepcopy(editor.profiles.profiles)
        second = await client.post(PATH, json=body)
    assert second.status_code == 200
    assert second.json() == {
        "user_id": str(user.user_id),
        "instagram_url": saved.instagram_url,
        "confirmed": True,
        "agreement_confirmed": True,
    }
    assert second.headers["cache-control"] == "no-store"
    assert editor.users.users == users_before
    assert editor.profiles.profiles == profiles_before
    roles.set_user.assert_not_called()
    roles.set_country.assert_not_called()


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("case", ["invalid", "expired", "unknown", "deleted"])
async def test_denied_accounts_are_not_created_or_updated(platform, case):
    app, editor, user, body, roles, _ = await application(platform)
    if case == "deleted":
        await editor.users.save(replace(user, status=UserStatus.DELETED))
    elif case == "invalid":
        body["init_data"] = "invalid"
    else:
        body["init_data"] = generate_init_data(
            "test-token" if platform == "telegram" else "max-token",
            999
            if case == "unknown"
            else int(
                getattr(
                    user, "telegram_id" if platform == "telegram" else "max_id"
                )
            ),
            "synthetic",
            auth_date=1 if case == "expired" else None,
        )
    before = deepcopy(editor.users.users)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(PATH, json=body)
    assert (
        response.status_code
        == {"invalid": 401, "expired": 401, "unknown": 404, "deleted": 403}[
            case
        ]
    )
    assert response.headers["cache-control"] == "no-store"
    assert editor.users.users == before
    roles.set_user.assert_not_called()
    roles.set_country.assert_not_called()


@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_native_remap_during_profile_read_cannot_expose_old_owner(
    platform,
):
    app, editor, user, body, _, profiles = await application(platform)

    async def remap(user_id):
        profile = await profiles.get_blogger_profile(user_id)
        field = "telegram_id" if platform == "telegram" else "max_id"
        external_id = getattr(user, field)
        await editor.users.save(replace(user, **{field: None}))
        await create_test_user(
            editor.users,
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM
            if platform == "telegram"
            else MessengerType.MAX,
        )
        return profile

    app.state.dispatcher["profile_service"] = SimpleNamespace(
        get_blogger_profile=remap
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(PATH, json=body)
    assert response.status_code == 403
    assert "instagram_url" not in response.json()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "case", ["extra", "query", "profile", "failure", "agreement"]
)
async def test_strict_private_response_and_incomplete_registration(case):
    app, editor, user, body, _, profiles = await application("telegram")
    path = PATH
    if case == "extra":
        body["user_id"] = "another-owner"
    elif case == "query":
        path += "?user_id=another-owner"
    elif case == "failure":
        app.state.dispatcher["profile_service"] = SimpleNamespace(
            get_blogger_profile=AsyncMock(
                side_effect=RuntimeError("PRIVATE provider detail")
            )
        )
    elif case == "profile":
        app.state.dispatcher["profile_service"] = SimpleNamespace(
            get_blogger_profile=AsyncMock(return_value=None)
        )
    else:
        profile = await profiles.get_blogger_profile(user.user_id)
        await editor.profiles.save(
            replace(profile, confirmed=True, agreement_confirmed_at=None)
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body)
    assert (
        response.status_code
        == {
            "extra": 422,
            "query": 422,
            "failure": 503,
            "profile": 400,
            "agreement": 200,
        }[case]
    )
    assert response.headers["cache-control"] == "no-store"
    assert "PRIVATE" not in response.text
    if case == "agreement":
        assert response.json()["confirmed"] is True
        assert response.json()["agreement_confirmed"] is False
