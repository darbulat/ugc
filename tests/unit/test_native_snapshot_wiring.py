"""Main-router resolver wiring with declared synthetic account/view sources."""

import pytest
from fastapi import FastAPI

from tests.unit.test_native_snapshot_api import (
    ACTOR,
    FAMILIES,
    ORDER,
    Roles,
    application,
    assert_error,
    post,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.api import router


class ExistingRoles(Roles):
    async def get_user(self, external_id, messenger_type):
        return await super().get_user(external_id, messenger_type)


def mounted(family, platform):
    direct, _, service, transactions, path, auth = application(family, platform)
    roles = ExistingRoles()
    direct.state.dispatcher["user_role_service"] = roles
    app = FastAPI()
    app.include_router(router, prefix="/miniapp")
    app.state.config = direct.state.config
    app.state.dispatcher = direct.state.dispatcher
    return app, roles, service, transactions, "/miniapp/api" + path, auth


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_main_snapshot_routes_forward_existing_typed_identity(
    family, platform
):
    app, roles, service, transactions, path, auth = mounted(family, platform)
    response = await post(app, path, auth)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert service.identities == (
        (ACTOR,) if family == "partner" else (ORDER, ACTOR)
    )
    assert service.options["principal"] == AuthenticatedMessengerPrincipal(
        ACTOR, platform, "123"
    )
    assert roles.user.country is None
    assert transactions.entries == (1 if family == "partner" else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_main_snapshot_routes_never_register_unknown_identity(
    family, platform
):
    app, roles, service, transactions, path, auth = mounted(family, platform)
    roles.user = None
    response = await post(app, path, auth)
    assert_error(response, 404, "existing_financial_account_required")
    assert service.private_reads == transactions.entries == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_main_snapshot_routes_keep_view_native_denial_private(
    family, platform
):
    app, roles, service, _, path, auth = mounted(family, platform)
    # A synthetic view boundary exercises forwarding, not actual MVCC.
    service.native = None
    response = await post(app, path, auth)
    assert_error(response, 403, "financial_principal_changed")
    assert service.private_reads == 0
    assert roles.user.country is None
