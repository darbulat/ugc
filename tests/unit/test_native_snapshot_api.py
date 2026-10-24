"""Three typed snapshot routers with synthetic identities and view sources."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from tests.e2e.miniapp_helpers import generate_init_data
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.miniapp.campaign_summary_api import create_campaign_summary_router
from ugc_bot.miniapp.financial_principal import resolve_financial_principal
from ugc_bot.miniapp.partner_api import create_partner_router
from ugc_bot.miniapp.selection_api import create_selection_router

ACTOR, ORDER = UUID(int=1), UUID(int=2)
FAMILIES = ("partner", "selection", "summary")
PRIVATE = "SYNTHETIC_PRIVATE_SNAPSHOT_VALUE"


class Roles:
    def __init__(self):
        self.user = SimpleNamespace(
            user_id=ACTOR, telegram_id="123", max_id="123", country=None
        )

    async def get_user(self, external, messenger):
        assert external == "123"
        return self.user

    async def set_user(self, *args, **kwargs):
        raise AssertionError("snapshot_created_user")

    async def set_country(self, *args, **kwargs):
        raise AssertionError("snapshot_filled_country")


class Transactions:
    def __init__(self):
        self.session, self.entries = object(), 0

    @asynccontextmanager
    async def transaction(self):
        self.entries += 1
        yield self.session


class View:
    """Synthetic view source; adapter checks are covered separately."""

    def __init__(self, family):
        self.family, self.native, self.private_reads = family, "123", 0
        self.identities, self.options, self.failure = None, None, None
        self.result = {"history": "synthetic snapshot"}

    async def view(self, *identities, principal=None, **options):
        if self.failure:
            raise self.failure
        actor = identities[0] if self.family == "partner" else identities[1]
        if principal is None:
            raise ValueError("synthetic_missing_http_proof")
        require_current_principal(
            principal, actor, ACTOR, self.native, self.native
        )
        self.identities, self.options = (
            identities,
            options | {"principal": principal},
        )
        self.private_reads += 1
        return self.result


def application(family, platform="telegram", *, resolver=None):
    roles, service, transactions = Roles(), View(family), Transactions()
    app = FastAPI()
    app.include_router(
        {
            "partner": create_partner_router,
            "selection": create_selection_router,
            "summary": create_campaign_summary_router,
        }[family](resolver or resolve_financial_principal)
    )
    app.state.config = SimpleNamespace(
        bot=SimpleNamespace(bot_token="synthetic-tg"),
        max_bot=SimpleNamespace(token="synthetic-max"),
        financial=SimpleNamespace(core_enabled=False),
    )
    app.state.dispatcher = {
        "user_role_service": roles,
        "partner_view_service": service,
        "selection_view_service": service,
        "campaign_summary_service": service,
        "transaction_manager": transactions,
    }
    path = {
        "partner": "/partner/view",
        "selection": f"/financial/orders/{ORDER}/selection",
        "summary": f"/orders/{ORDER}/campaign-summary",
    }[family]
    auth = dict(
        platform=platform,
        init_data=generate_init_data(
            "synthetic-tg" if platform == "telegram" else "synthetic-max",
            123,
            "Synthetic",
        ),
    )
    return app, roles, service, transactions, path, auth


async def post(app, path, payload, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(path, json=payload, **kwargs)


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json() == {"detail": code}
    assert response.headers["cache-control"] == "no-store"
    assert PRIVATE not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_signed_typed_identity_reaches_view_without_country_fill(
    family, platform
):
    app, roles, service, transactions, path, auth = application(
        family, platform
    )
    response = await post(app, path, auth)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == dict(
        service.result,
        **({"writes_paused": True} if family == "selection" else {}),
    )
    assert service.identities == (
        (ACTOR,) if family == "partner" else (ORDER, ACTOR)
    )
    assert service.options["principal"] == AuthenticatedMessengerPrincipal(
        ACTOR, platform, "123"
    )
    assert roles.user.country is None
    if family == "partner":
        assert service.options["session"] is transactions.session
        assert service.options["writes_paused"] is True
        assert transactions.entries == 1
    else:
        assert transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("proof", [None, ACTOR])
async def test_snapshot_http_rejects_missing_or_uuid_only_proof(family, proof):
    async def legacy(*args, **kwargs):
        return proof

    app, _, service, transactions, path, auth = application(
        family, resolver=legacy
    )
    response = await post(app, path, auth)
    assert_error(response, 401, "financial_session_invalid")
    assert service.private_reads == transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_unknown_signed_identity_creates_nothing(
    family, platform
):
    app, roles, service, transactions, path, auth = application(
        family, platform
    )
    roles.user = None
    response = await post(app, path, auth)
    assert_error(response, 404, "existing_financial_account_required")
    assert service.private_reads == transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_gateway_proof_remap_is_forwarded_to_source_check(
    family, platform
):
    async def remapped(request, init_data, *, platform):
        proof = await resolve_financial_principal(
            request, init_data, platform=platform
        )
        service.native = None
        return proof

    app, _, service, _, path, auth = application(
        family, platform, resolver=remapped
    )
    response = await post(app, path, auth)
    assert_error(response, 403, "financial_principal_changed")
    assert service.private_reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "field", ["actor_id", "recipient_id", "principal", "system_actor"]
)
async def test_snapshot_body_cannot_choose_authority(family, field):
    app, _, service, transactions, path, auth = application(family)
    response = await post(app, path, auth | {field: PRIVATE})
    assert_error(response, 422, f"{family}_request_invalid")
    assert service.private_reads == transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("case", ["query", "platform", "json", "missing_init"])
async def test_snapshot_invalid_envelopes_are_constant_and_no_store(
    family, case
):
    app, _, service, transactions, path, auth = application(family)
    if case == "json":
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                path,
                content=PRIVATE,
                headers={"Content-Type": "application/json"},
            )
    else:
        payload = (
            auth | {"platform": PRIVATE}
            if case == "platform"
            else {"platform": "telegram"}
            if case == "missing_init"
            else auth
        )
        response = await post(
            app,
            path + (f"?private={PRIVATE}" if case == "query" else ""),
            payload,
        )
    assert_error(response, 422, f"{family}_request_invalid")
    assert service.private_reads == transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["selection", "summary"])
async def test_snapshot_invalid_order_id_is_constant(family):
    app, _, _, _, path, auth = application(family)
    response = await post(app, path.replace(str(ORDER), PRIVATE), auth)
    assert_error(response, 422, f"{family}_request_invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("page", [-1, True, 100001, PRIVATE])
async def test_snapshot_partner_pages_keep_strict_bounded_validation(page):
    app, _, service, _, path, auth = application("partner")
    response = await post(app, path, auth | {"network_page": page})
    assert_error(response, 422, "partner_request_invalid")
    assert service.private_reads == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "exception",
    [ValueError, PermissionError, LookupError, RuntimeError, HTTPException],
)
async def test_snapshot_private_context_exceptions_are_constant(
    family, exception, caplog
):
    async def broken(*args, **kwargs):
        raise (
            exception(418, PRIVATE)
            if exception is HTTPException
            else exception(PRIVATE)
        )

    app, _, _, _, path, auth = application(family, resolver=broken)
    assert_error(await post(app, path, auth), 503, f"{family}_unavailable")
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("case", ["dispatcher", "missing_service", "response"])
async def test_snapshot_context_and_response_failures_share_error_boundary(
    family, case
):
    app, _, service, _, path, auth = application(family)
    if case == "dispatcher":
        del app.state.dispatcher
    elif case == "missing_service":
        app.state.dispatcher[
            {
                "partner": "partner_view_service",
                "selection": "selection_view_service",
                "summary": "campaign_summary_service",
            }[family]
        ] = None
    else:
        service.result = {"private": object()}
    assert_error(await post(app, path, auth), 503, f"{family}_unavailable")


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("status", [200, 403, 418, 500])
async def test_snapshot_known_http_code_has_exact_safe_status(family, status):
    app, _, service, _, path, auth = application(family)
    service.failure = HTTPException(status, "financial_principal_changed")
    assert_error(
        await post(app, path, auth), 403, "financial_principal_changed"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "family,exception,code,status",
    [
        ("partner", PermissionError, "partner_account_unavailable", 403),
        ("partner", LookupError, "partner_not_found", 404),
        ("selection", PermissionError, "selection_client_inactive", 403),
        ("selection", PermissionError, "selection_client_role_required", 403),
        ("selection", LookupError, "selection_order_not_found", 404),
        ("selection", ValueError, "selection_history_unavailable", 503),
        ("summary", PermissionError, "summary_actor_inactive", 403),
        ("summary", LookupError, "summary_not_found", 404),
        ("summary", ValueError, "summary_history_unavailable", 503),
    ],
)
async def test_snapshot_expected_status_and_source_denials_remain_exact(
    family, exception, code, status
):
    app, _, service, _, path, auth = application(family)
    service.failure = exception(code)
    assert_error(await post(app, path, auth), status, code)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "exception",
    [ValueError, PermissionError, LookupError, RuntimeError, HTTPException],
)
async def test_snapshot_unknown_service_failures_remain_private(
    family, exception, caplog
):
    app, _, service, _, path, auth = application(family)
    service.failure = (
        exception(418, PRIVATE)
        if exception is HTTPException
        else exception(PRIVATE)
    )
    assert_error(await post(app, path, auth), 503, f"{family}_unavailable")
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("status", [200, 418, 500])
async def test_snapshot_request_invalid_status_is_always_422(family, status):
    app, _, service, _, path, auth = application(family)
    service.failure = HTTPException(status, f"{family}_request_invalid")
    assert_error(await post(app, path, auth), 422, f"{family}_request_invalid")


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("status", [200, 418, 500])
async def test_snapshot_known_absent_scope_status_is_always_404(family, status):
    app, _, service, _, path, auth = application(family)
    code = {
        "partner": "partner_not_found",
        "selection": "selection_order_not_found",
        "summary": "summary_not_found",
    }[family]
    service.failure = HTTPException(status, code)
    assert_error(await post(app, path, auth), 404, code)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_snapshot_bad_signed_auth_denies_before_view(family, platform):
    app, _, service, transactions, path, auth = application(family, platform)
    response = await post(
        app, path, auth | {"init_data": "bad-signed-" + PRIVATE}
    )
    assert_error(response, 401, "financial_session_invalid")
    assert service.private_reads == transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["missing_transactions", "transaction", "config"]
)
async def test_snapshot_partner_infrastructure_failures_are_bounded(case):
    app, _, _, transactions, path, auth = application("partner")
    if case == "missing_transactions":
        app.state.dispatcher["transaction_manager"] = None
    elif case == "transaction":

        def broken():
            raise RuntimeError(PRIVATE)

        transactions.transaction = broken
    else:
        app.state.config.financial = None
    assert_error(await post(app, path, auth), 503, "partner_unavailable")
