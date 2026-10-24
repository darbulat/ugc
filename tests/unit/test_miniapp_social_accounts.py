"""Signed Mini App requests operate on the real canonical-owner service."""

from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.social_editor import MemorySocialEditor
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.social_api import create_social_router


@pytest_asyncio.fixture
async def social_client(user_repo, blogger_repo):
    users = []
    for external, username in (("101", "alice"), ("202", "bob")):
        user = await create_test_user(
            user_repo, external_id=external, username=username, country="ru"
        )
        profile = await create_test_blogger_profile(
            blogger_repo,
            user.user_id,
            instagram_url=f"https://instagram.com/{username}",
            confirmed=True,
        )
        await blogger_repo.save(
            replace(profile, instagram_user_id="ig-" + external)
        )
        users.append(user)
    # Module compatibility only: root main-router injection is a later grant.
    accounts = MemorySocialEditor(user_repo, blogger_repo)
    service = accounts.service()
    app = FastAPI()
    app.include_router(
        create_social_router(resolve_financial_principal), prefix="/miniapp/api"
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"), max_bot=None
    )
    app.state.dispatcher = {
        "user_role_service": UserRoleService(user_repo),
        "social_account_service": service,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, service, users, blogger_repo


def auth(user):
    return {
        "init_data": generate_init_data(
            "test-token", int(user.telegram_id), user.username
        )
    }


@pytest.mark.asyncio
async def test_signed_account_list_cannot_disclose_another_creators_links(
    social_client,
):
    client, service, users, _ = social_client
    await service.save_account(
        users[1].user_id, "tiktok", "https://tiktok.com/@privatebob"
    )
    response = await client.post(
        "/miniapp/api/social/accounts", json=auth(users[0])
    )
    assert response.status_code == 200
    payload = response.json()
    assert [a["platform"] for a in payload["accounts"]] == ["instagram"]
    assert payload["next_platform"] == "tiktok"
    assert "privatebob" not in response.text


@pytest.mark.asyncio
async def test_repeated_save_preserves_owner_id_and_unknown_metrics(
    social_client,
):
    client, _, users, _ = social_client
    request = {
        **auth(users[0]),
        "network": "tiktok",
        "url": "https://www.tiktok.com/@alice",
    }
    first = await client.post("/miniapp/api/social/accounts/save", json=request)
    assert first.status_code == 200
    account = first.json()["account"]
    assert account["user_id"] == str(users[0].user_id)
    assert account["verified"] is False
    assert account["followers_count"] is None
    assert account["metrics_source"] is None
    assert first.json()["next_platform"] == "youtube"
    repeated = await client.post(
        "/miniapp/api/social/accounts/save", json=request
    )
    assert repeated.status_code == 200
    assert repeated.json()["account"]["account_id"] == account["account_id"]
    listed = await client.post(
        "/miniapp/api/social/accounts", json=auth(users[0])
    )
    assert len(listed.json()["accounts"]) == 2


@pytest.mark.asyncio
async def test_skip_advances_without_creating_account(
    social_client,
):
    client, _, users, _ = social_client
    response = await client.post(
        "/miniapp/api/social/accounts",
        json={**auth(users[0]), "skipped": ["tiktok", "youtube"]},
    )
    assert response.status_code == 200
    assert response.json()["next_platform"] == "telegram"
    assert len(response.json()["accounts"]) == 1


@pytest.mark.asyncio
async def test_unverified_instagram_blocks_social_save(
    social_client,
):
    client, _, users, profiles = social_client
    profile = await profiles.get_by_user_id(users[0].user_id)
    await profiles.save(replace(profile, confirmed=False))
    response = await client.post(
        "/miniapp/api/social/accounts/save",
        json={
            **auth(users[0]),
            "network": "telegram",
            "url": "https://t.me/alice",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_foreign_social_account_cannot_be_removed(social_client):
    client, service, users, _ = social_client
    account = await service.save_account(
        users[1].user_id, "telegram", "https://t.me/bobby"
    )
    response = await client.post(
        "/miniapp/api/social/accounts/remove",
        json={**auth(users[0]), "account_id": str(account.account_id)},
    )
    assert response.status_code == 400
    accounts = await service.list_accounts(users[1].user_id)
    assert any(a.account_id == account.account_id for a in accounts)
    response = await client.post(
        "/miniapp/api/social/accounts/remove",
        json={**auth(users[1]), "account_id": str(account.account_id)},
    )
    assert response.status_code == 200
    assert response.json()["removed"] is True


@pytest.mark.asyncio
async def test_invalid_signature_and_forged_owner_or_verification_are_rejected(
    social_client,
):
    client, service, users, _ = social_client
    invalid = await client.post(
        "/miniapp/api/social/accounts", json={"init_data": "forged"}
    )
    assert invalid.status_code == 401
    for field, value in (
        ("user_id", str(users[1].user_id)),
        ("verified", True),
        ("followers_count", 100000),
    ):
        response = await client.post(
            "/miniapp/api/social/accounts/save",
            json={
                **auth(users[0]),
                "network": "youtube",
                "url": "https://youtube.com/@alice",
                field: value,
            },
        )
        assert response.status_code == 422
    assert len(await service.list_accounts(users[0].user_id)) == 1


@pytest.mark.asyncio
async def test_max_signature_resolves_max_principal_separately(
    user_repo,
    blogger_repo,
):
    user = await create_test_user(
        user_repo,
        external_id="101",
        messenger_type=MessengerType.MAX,
        country="ru",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )
    service = MemorySocialEditor(user_repo, blogger_repo).service()
    app = FastAPI()
    app.include_router(
        create_social_router(resolve_financial_principal), prefix="/api"
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="telegram-token"),
        max_bot=SimpleNamespace(token="max-token"),
    )
    app.state.dispatcher = {
        "user_role_service": UserRoleService(user_repo),
        "social_account_service": service,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/social/accounts",
            json={
                "init_data": generate_init_data("max-token", 101, "max-user"),
                "platform": "max",
            },
        )
        assert response.status_code == 200
        assert response.json()["accounts"][0]["user_id"] == str(user.user_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [UserStatus.BLOCKED, UserStatus.DELETED])
async def test_blocked_or_deleted_principal_cannot_edit_socials(
    social_client,
    user_repo,
    status,
):
    client, service, users, _ = social_client
    await user_repo.save(replace(users[0], status=status))
    response = await client.post(
        "/miniapp/api/social/accounts/save",
        json={
            **auth(users[0]),
            "network": "youtube",
            "url": "https://youtube.com/@alice",
        },
    )
    assert response.status_code == 403
    assert len(await service.list_accounts(users[0].user_id)) == 1


@pytest.mark.asyncio
async def test_missing_configured_social_service_is_unavailable(social_client):
    client, _, users, _ = social_client
    # Exercise the actual request dependency, preserving real HMAC validation.
    del client._transport.app.state.dispatcher["social_account_service"]
    response = await client.post(
        "/miniapp/api/social/accounts", json=auth(users[0])
    )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_old_signed_session_cannot_access_socials(social_client):
    from tests.unit.test_miniapp_session_freshness import signed

    client, _, _, _ = social_client
    response = await client.post(
        "/miniapp/api/social/accounts",
        json={"init_data": signed(bot_token="test-token")},
    )
    assert response.status_code == 401
