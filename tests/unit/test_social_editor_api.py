"""Actual social router/service over explicit synthetic memory authority."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from tests.e2e.miniapp_helpers import generate_init_data
from tests.helpers.social_editor import editor_fixture
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.social_api import create_social_router


class StringSubclass(str):
    def __hash__(self):
        raise RuntimeError("PRIVATE string subclass hash")

    def __str__(self):
        raise RuntimeError("PRIVATE string subclass conversion")


async def application(
    platform="telegram", resolver=resolve_financial_principal
):
    editor, user, principal = await editor_fixture(platform=platform)
    app = FastAPI()
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="test-token"),
        max_bot=SimpleNamespace(token="max-token"),
    )
    app.state.dispatcher = {
        "user_role_service": UserRoleService(editor.users),
        "social_account_service": editor.service(),
    }
    app.include_router(create_social_router(resolver), prefix="/api")
    envelope = {
        "platform": platform,
        "init_data": generate_init_data(
            "test-token" if platform == "telegram" else "max-token",
            int(principal.external_id),
            "creator",
        ),
    }
    return app, editor, user, envelope


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_aggregate_editor_roundtrip_no_country_write(platform):
    app, editor, user, envelope = await application(platform)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        saved = await client.post(
            "/api/social/accounts/save",
            json={
                **envelope,
                "network": "youtube",
                "url": "https://youtube.com/@creator",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["next_platform"] == "tiktok"
        assert saved.headers["cache-control"] == "no-store"
        listed = await client.post("/api/social/accounts", json=envelope)
        assert [a["platform"] for a in listed.json()["accounts"]] == [
            "instagram",
            "youtube",
        ]
        removed = await client.post(
            "/api/social/accounts/remove",
            json={
                **envelope,
                "account_id": saved.json()["account"]["account_id"],
            },
        )
        assert removed.status_code == 200 and removed.json() == {
            "removed": True
        }
    assert (await editor.users.get_by_id(user.user_id)).country is None
    assert editor.starts == editor.commits == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("proof", [None, uuid4()])
async def test_uuid_only_resolver_cannot_enter_trusted_methods(proof):
    async def resolve(*args, **kwargs):
        return proof

    app, editor, _, envelope = await application(resolver=resolve)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 401
    assert response.json() == {"detail": "financial_session_invalid"}
    assert response.headers["cache-control"] == "no-store"
    assert editor.starts == 0


class UnsafeValue(ValueError):
    conversions = 0

    def __str__(self):
        type(self).conversions += 1
        raise RuntimeError("PRIVATE unsafe conversion")


class UnsafePermission(PermissionError):
    def __str__(self):
        raise RuntimeError("PRIVATE permission conversion")


class UnsafeArgument:
    def __str__(self):
        raise RuntimeError("PRIVATE argument conversion")

    __repr__ = __str__


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        UnsafeValue("PRIVATE"),
        UnsafePermission("PRIVATE"),
        ValueError(UnsafeArgument()),
        PermissionError(UnsafeArgument()),
        ValueError(),
        ValueError("financial_principal_changed", "PRIVATE"),
        RuntimeError("PRIVATE"),
    ],
)
async def test_unsafe_errors_never_convert_or_escape_no_store(error, caplog):
    app, editor, _, envelope = await application()
    editor.failure = error
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 503
    assert response.json() == {"detail": "social_unavailable"}
    assert response.headers["cache-control"] == "no-store"
    assert UnsafeValue.conversions == 0 and "PRIVATE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 418, 500])
async def test_known_http_code_uses_canonical_status(status):
    async def resolver(*args, **kwargs):
        raise HTTPException(
            status, "financial_principal_changed", headers={"PRIVATE": "SECRET"}
        )

    app, _, _, envelope = await application(resolver=resolver)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 403
    assert response.json() == {"detail": "financial_principal_changed"}
    assert "PRIVATE" not in response.headers


@pytest.mark.asyncio
async def test_validation_unknown_account_and_missing_service_are_constant():
    app, editor, _, envelope = await application()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for extra in (
            {"user_id": str(uuid4())},
            {"followers_count": 99},
            {"verified": True},
        ):
            response = await client.post(
                "/api/social/accounts/save",
                json={
                    **envelope,
                    "network": "youtube",
                    "url": "PRIVATE URL",
                    **extra,
                },
            )
            assert response.status_code == 422 and response.json() == {
                "detail": "social_request_invalid"
            }
            assert response.headers["cache-control"] == "no-store"
        response = await client.post(
            "/api/social/accounts?user_id=PRIVATE", json=envelope
        )
        assert response.status_code == 422
        unknown = {
            **envelope,
            "init_data": generate_init_data("test-token", 999, "PRIVATE"),
        }
        response = await client.post("/api/social/accounts", json=unknown)
        assert response.status_code == 404
        del app.state.dispatcher["social_account_service"]
        response = await client.post("/api/social/accounts", json=envelope)
        assert response.status_code == 503
    assert len(editor.users.users) == 1 and editor.starts == 0


@pytest.mark.asyncio
async def test_remap_between_gateway_and_transaction_denies():
    app, editor, user, envelope = await application()

    async def resolver(request, init_data, *, platform):
        proof = await resolve_financial_principal(
            request, init_data, platform=platform
        )
        await editor.users.save(replace(user, telegram_id=None))
        return proof

    other = FastAPI()
    other.state.config = app.state.config
    other.state.dispatcher = app.state.dispatcher
    other.include_router(create_social_router(resolver), prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=other), base_url="http://test"
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 403 and response.json() == {
        "detail": "financial_principal_changed"
    }
    assert "facts" not in editor.events


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detail",
    [
        StringSubclass("financial_principal_changed"),
        UnsafeArgument(),
        {"PRIVATE": "value"},
        None,
    ],
)
async def test_non_plain_http_detail_is_never_converted(detail):
    async def resolver(*args, **kwargs):
        raise HTTPException(401, detail)

    app, _, _, envelope = await application(resolver=resolver)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 503 and response.json() == {
        "detail": "social_unavailable"
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_string_subclass_domain_argument_is_not_a_code():
    app, editor, _, envelope = await application()
    editor.failure = ValueError(StringSubclass("financial_principal_changed"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 503 and response.json() == {
        "detail": "social_unavailable"
    }


@pytest.mark.asyncio
async def test_later_http_serialization_failure_is_safe_after_commit(
    monkeypatch,
):
    import fastapi.routing

    app, editor, _, envelope = await application()

    async def broken_encoding(*args, **kwargs):
        raise UnsafeValue("PRIVATE serialization")

    monkeypatch.setattr(fastapi.routing, "serialize_response", broken_encoding)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/social/accounts/save",
            json={
                **envelope,
                "network": "youtube",
                "url": "https://youtube.com/@creator",
            },
        )
    assert response.status_code == 503 and response.json() == {
        "detail": "social_unavailable"
    }
    assert response.headers["cache-control"] == "no-store"
    assert editor.commits == 1 and editor.rollbacks == 0
    assert len(editor.storage.accounts) == 1


@pytest.mark.asyncio
async def test_transaction_exit_failure_stays_inside_safe_boundary():
    from contextlib import asynccontextmanager

    app, editor, _, envelope = await application()

    class FailingExit:
        @asynccontextmanager
        async def transaction(self):
            async with editor.transaction() as session:
                yield session
                raise UnsafePermission("PRIVATE exit")

    app.state.dispatcher[
        "social_account_service"
    ].transaction_manager = FailingExit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/social/accounts/save",
            json={
                **envelope,
                "network": "youtube",
                "url": "https://youtube.com/@creator",
            },
        )
    assert (
        response.status_code == 503
        and response.headers["cache-control"] == "no-store"
    )
    assert editor.storage.accounts == {} and editor.rollbacks == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "missing_dispatcher",
        "missing_roles",
        "missing_config",
        "missing_capability",
        "missing_transactions",
    ],
)
async def test_context_failures_are_constant_no_store(failure):
    app, _, _, envelope = await application()
    if failure == "missing_dispatcher":
        del app.state.dispatcher
    elif failure == "missing_roles":
        del app.state.dispatcher["user_role_service"]
    elif failure == "missing_config":
        del app.state.config
    elif failure == "missing_capability":
        app.state.dispatcher["social_account_service"].editor_repository = None
    else:
        app.state.dispatcher[
            "social_account_service"
        ].transaction_manager = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/social/accounts", json=envelope)
    assert response.status_code == 503
    assert response.json()["detail"] in {
        "social_unavailable",
        "financial_unavailable",
    }
    assert response.headers["cache-control"] == "no-store"
