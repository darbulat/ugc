"""Existing-only HMAC payout reads never create identity, country or wallets."""

import importlib
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from tests.e2e.miniapp_helpers import generate_init_data
from tests.unit.test_payout_view_service import ACTOR, setup


class Roles:
    def __init__(self, user):
        self.user = user
        self.reads = 0

    async def get_user(self, external_id, messenger_type):
        self.reads += 1
        return self.user

    def __getattr__(self, name):
        raise AssertionError(
            "read flow attempted forbidden identity write " + name
        )


def application(platform="telegram"):
    p, _, service, repo, principal = setup()
    repo.reader.facts["actor"] = replace(
        repo.reader.facts["actor"], platform=platform
    )
    try:
        importlib.import_module("ugc_bot.miniapp.payout_view_api")
    except ModuleNotFoundError:
        pytest.fail("dedicated payout read router is missing")
    roles = Roles(
        SimpleNamespace(
            user_id=ACTOR, telegram_id="123", max_id="123", country=None
        )
    )
    app = FastAPI()
    from ugc_bot.miniapp.api import router

    app.include_router(router, prefix="/miniapp")
    app.state.dispatcher = dict(
        payout_view_service=service, user_role_service=roles
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="synthetic-tg"),
        max_bot=SimpleNamespace(token="synthetic-max"),
    )
    token = "synthetic-tg" if platform == "telegram" else "synthetic-max"
    auth = dict(
        platform=platform,
        init_data=generate_init_data(token, 123, "Synthetic owner"),
    )
    return app, repo, roles, auth


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_signed_existing_missing_country_read_has_no_identity_side_effect(
    platform,
):
    app, repo, roles, auth = application(platform)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/miniapp/api/payouts/read/context", json=auth
        )
    assert response.status_code == 200, response.text
    assert response.json()["actor_id"] == str(ACTOR)
    assert response.json()["financial"]["balances"]["available_minor"] == "100"
    assert response.headers["cache-control"] == "no-store"
    assert (
        roles.user.country is None and roles.reads == 1 and repo.snapshots == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "mapping_race",
        "wrong_token",
        "selector",
        "query",
        "malformed",
    ],
)
async def test_unknown_changed_or_forged_identity_never_has_read_authority(
    platform, case
):
    app, repo, roles, auth = application(platform)
    url = "/miniapp/api/payouts/read/context"
    expected = 403
    if case == "unknown":
        roles.user = None
        expected = 404
    if case == "mapping_race":
        repo.reader.facts["actor"] = replace(
            repo.reader.facts["actor"], external_id="reassigned"
        )
    if case == "wrong_token":
        auth["init_data"] = generate_init_data("wrong", 123, "Synthetic")
        expected = 401
    if case == "selector":
        auth["actor_id"] = str(ACTOR)
        expected = 422
    if case == "query":
        url += "?admin=true"
        expected = 422
    if case == "malformed":
        auth["limit"] = {"secret": "SYNTHETIC_PRIVATE_INVALID"}
        expected = 422
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(url, json=auth)
    assert response.status_code == expected, response.text
    assert response.headers["cache-control"] == "no-store"
    assert (
        "SYNTHETIC_PRIVATE_INVALID" not in response.text
        and auth["init_data"] not in response.text
    )
    if case in ("unknown", "wrong_token", "selector", "query", "malformed"):
        assert repo.snapshots == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_real_main_router_read_paths_are_bounded_and_role_protected(
    platform,
):
    from tests.unit.test_payout_view_service import readable, request_facts

    app, repo, _, auth = application(platform)
    service = app.state.dispatcher["payout_view_service"]
    requisite = readable(repo)
    service.crypto = SimpleNamespace(
        open=lambda *args: {"bank_account": "SYNTHETIC_PRIVATE"}
    )
    fact = request_facts(repo)
    repo.reader.facts["requests"] = (fact,)
    repo.reader.facts["requirement_rows"] = (
        repo.reader.facts["requirements"].current
        | {"recorded_at": fact.row["requested_at"]},
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        for path in ("own", "masked", str(fact.row["request_id"]) + "/detail"):
            response = await client.post(
                "/miniapp/api/payouts/read/" + path, json=auth
            )
            assert response.status_code == 200, response.text
            assert (
                "SYNTHETIC_PRIVATE" not in response.text
                and "protected-origin" not in response.text
            )
        for path in (
            "admin/queue",
            "admin/requirements",
            "admin/" + str(fact.row["request_id"]) + "/history/intents",
        ):
            response = await client.post(
                "/miniapp/api/payouts/read/" + path, json=auth
            )
            assert response.status_code == 403
        preview = await client.post(
            "/miniapp/api/payouts/read/reserve-preview",
            json=auth | dict(requisites_id=str(requisite), amount_minor="1"),
        )
        assert (
            preview.status_code == 200 and preview.json()["amount_minor"] == "1"
        )
        repo.reader.facts["actor"] = replace(
            repo.reader.facts["actor"], admin=True
        )
        for path in (
            "admin/queue",
            "admin/requirements",
            "admin/" + str(fact.row["request_id"]) + "/history/intents",
        ):
            response = await client.post(
                "/miniapp/api/payouts/read/" + path, json=auth | {"limit": 1}
            )
            assert response.status_code == 200, response.text
        repo.reader.facts["actor"] = replace(
            repo.reader.facts["actor"], admin=False
        )
        unknown = await client.post(
            "/miniapp/api/payouts/read/00000000-0000-0000-0000-000000000001/detail",
            json=auth,
        )
        assert unknown.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError, KeyError])
async def test_unknown_source_failure_is_unavailable_not_false_absence(error):
    app, repo, _, auth = application()

    async def fail(recipient_id):
        raise error("SYNTHETIC_PRIVATE_SOURCE_FAILURE")

    repo.reader.financial = fail
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/miniapp/api/payouts/read/context", json=auth
        )
    assert response.status_code == 503
    assert "SYNTHETIC_PRIVATE_SOURCE_FAILURE" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_utc_overflow_cursor_is_invalid_read_request(platform):
    import base64
    import json

    app, _, _, auth = application(platform)
    token = base64.urlsafe_b64encode(
        json.dumps(
            dict(
                v=1,
                actor=str(ACTOR),
                route="own",
                scope=None,
                position=[
                    "9999-12-31T23:59:59-23:59",
                    "00000000-0000-0000-0000-000000000001",
                ],
            )
        ).encode()
    ).decode()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/miniapp/api/payouts/read/own", json=auth | {"cursor": token}
        )
    assert response.status_code == 422
    assert response.json() == {"detail": "payout_read_request_invalid"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dependency", ["payout_view_service", "user_role_service"]
)
async def test_missing_read_dependency_is_stable_unavailable(dependency):
    app, _, _, auth = application()
    app.state.dispatcher.pop(dependency)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/miniapp/api/payouts/read/context", json=auth
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "payout_read_unavailable"}
    assert response.headers["cache-control"] == "no-store"
