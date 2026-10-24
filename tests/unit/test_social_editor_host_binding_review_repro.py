"""Wrong-host typed gateway results must not authorize social HTTP actions."""

from uuid import uuid4

import httpx
import pytest

from tests.unit.test_social_editor_api import application
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.financial_principal import resolve_financial_principal


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("action", ["list", "save", "remove"])
async def test_social_http_refuses_typed_proof_from_other_host(
    platform, action
):
    async def wrong_host(request, init_data, *, platform):
        # Validate the actual synthetic signed request first. Only the returned
        # typed gateway result is deliberately changed to a different host.
        signed = await resolve_financial_principal(
            request, init_data, platform=platform
        )
        current = await editor.users.get_by_id(signed.user_id)
        other = "max" if platform == "telegram" else "telegram"
        external = current.max_id if other == "max" else current.telegram_id
        return AuthenticatedMessengerPrincipal(signed.user_id, other, external)

    app, editor, user, envelope = await application(
        platform, resolver=wrong_host
    )
    account_id = uuid4()
    if action == "remove":
        correct = AuthenticatedMessengerPrincipal(
            user.user_id, platform, "101" if platform == "telegram" else "202"
        )
        saved = await editor.service().save_editor_account(
            user.user_id,
            "youtube",
            "https://youtube.com/@creator",
            principal=correct,
        )
        account_id = saved.account.account_id
    before = dict(editor.storage.accounts)
    editor.starts = editor.commits = editor.rollbacks = 0
    editor.events.clear()
    path, body = "/api/social/accounts", dict(envelope)
    if action == "save":
        path += "/save"
        body.update(network="youtube", url="https://youtube.com/@creator")
    elif action == "remove":
        path += "/remove"
        body["account_id"] = str(account_id)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body)
    assert (
        response.status_code,
        editor.starts,
        editor.storage.accounts == before,
    ) == (401, 0, True)
    assert response.json() == {"detail": "financial_session_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert "facts" not in editor.events
