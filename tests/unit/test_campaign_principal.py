"""The dormant adapter delegates existing-only lookup with fixed errors."""

from time import time
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from tests.unit.test_miniapp_session_freshness import signed
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)

ACTOR = UUID(int=41)


class ExistingOnlyRoles:
    def __init__(self, user):
        self.user = user

    async def get_user(self, external_id, messenger):
        return self.user

    async def set_user(self, *args, **kwargs):
        pytest.fail("campaign principal cannot register or fill country")


def request_for(user, *, roles=True):
    app = SimpleNamespace(
        state=SimpleNamespace(
            config=SimpleNamespace(
                bot=SimpleNamespace(bot_token="synthetic-tg"),
                max_bot=SimpleNamespace(token="synthetic-max"),
            ),
            dispatcher={"user_role_service": ExistingOnlyRoles(user)}
            if roles
            else {},
        )
    )
    return Request({"type": "http", "app": app})


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_campaign_adapter_delegates_actual_existing_only_resolver(
    platform,
):
    from ugc_bot.miniapp.campaign_principal import resolve_campaign_principal

    user = SimpleNamespace(
        user_id=ACTOR, telegram_id="101", max_id="101", country=None
    )
    token = "synthetic-tg" if platform == "telegram" else "synthetic-max"
    result = await resolve_campaign_principal(
        request_for(user),
        signed(str(int(time())), bot_token=token),
        platform=platform,
    )
    assert result == AuthenticatedMessengerPrincipal(ACTOR, platform, "101")
    assert user.country is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("known", [False, True])
async def test_unknown_or_changed_native_binding_never_creates_an_account(
    platform, known
):
    from ugc_bot.miniapp.campaign_principal import resolve_campaign_principal

    user = (
        SimpleNamespace(user_id=ACTOR, telegram_id="other", max_id="other")
        if known
        else None
    )
    token = "synthetic-tg" if platform == "telegram" else "synthetic-max"
    with pytest.raises(HTTPException) as caught:
        await resolve_campaign_principal(
            request_for(user),
            signed(str(int(time())), bot_token=token),
            platform=platform,
        )
    assert (caught.value.status_code, caught.value.detail) == (
        404,
        "existing_campaign_account_required",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 403, 404, 418, 500])
@pytest.mark.parametrize(
    "upstream,want_status,want_code",
    [
        ("financial_session_invalid", 401, "campaign_session_invalid"),
        ("financial_unavailable", 503, "campaign_unavailable"),
        (
            "existing_financial_account_required",
            404,
            "existing_campaign_account_required",
        ),
        ("financial_principal_changed", 403, "campaign_principal_changed"),
    ],
)
async def test_known_failures_have_canonical_status_and_code(
    monkeypatch, status, upstream, want_status, want_code
):
    import ugc_bot.miniapp.campaign_principal as adapter

    async def refused(*args, **kwargs):
        raise HTTPException(
            status, upstream, headers={"PRIVATE": "not forwarded"}
        )

    monkeypatch.setattr(adapter, "resolve_financial_principal", refused)
    with pytest.raises(HTTPException) as caught:
        await adapter.resolve_campaign_principal(
            request_for(None), "PRIVATE_AUTH", platform="telegram"
        )
    assert (caught.value.status_code, caught.value.detail) == (
        want_status,
        want_code,
    )
    assert caught.value.headers is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        HTTPException(418, "PRIVATE_DETAIL"),
        HTTPException(401, {"private": "detail"}),
        ValueError("PRIVATE_DETAIL"),
        RuntimeError("PRIVATE_DETAIL"),
    ],
)
async def test_unexpected_failures_are_constant_without_auth_or_exception_text(
    monkeypatch, caplog, error
):
    import ugc_bot.miniapp.campaign_principal as adapter

    async def refused(*args, **kwargs):
        raise error

    monkeypatch.setattr(adapter, "resolve_financial_principal", refused)
    with pytest.raises(HTTPException) as caught:
        await adapter.resolve_campaign_principal(
            request_for(None), "PRIVATE_AUTH", platform="max"
        )
    assert (caught.value.status_code, caught.value.detail) == (
        503,
        "campaign_unavailable",
    )
    assert "PRIVATE" not in str(caught.value.detail) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "returned",
    [None, ACTOR, AuthenticatedMessengerPrincipal(ACTOR, "max", "101")],
)
async def test_adapter_refuses_missing_uuid_only_or_wrong_platform_proof(
    monkeypatch, returned
):
    import ugc_bot.miniapp.campaign_principal as adapter

    async def malformed(*args, **kwargs):
        return returned

    monkeypatch.setattr(adapter, "resolve_financial_principal", malformed)
    with pytest.raises(HTTPException) as caught:
        await adapter.resolve_campaign_principal(
            request_for(None), "synthetic", platform="telegram"
        )
    assert (caught.value.status_code, caught.value.detail) == (
        401,
        "campaign_session_invalid",
    )


@pytest.mark.asyncio
async def test_invalid_platform_unavailable_or_stale_session_fails_safely():
    from ugc_bot.miniapp.campaign_principal import resolve_campaign_principal

    for request, raw, platform, status, code in (
        (
            request_for(None),
            "synthetic",
            "email",
            401,
            "campaign_session_invalid",
        ),
        (
            request_for(None),
            signed("1", bot_token="synthetic-tg"),
            "telegram",
            401,
            "campaign_session_invalid",
        ),
        (
            request_for(None, roles=False),
            signed(str(int(time())), bot_token="synthetic-tg"),
            "telegram",
            503,
            "campaign_unavailable",
        ),
    ):
        with pytest.raises(HTTPException) as caught:
            await resolve_campaign_principal(request, raw, platform=platform)
        assert (caught.value.status_code, caught.value.detail) == (status, code)
