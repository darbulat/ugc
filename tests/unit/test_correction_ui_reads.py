"""UI reads exercise real correction authority over declared source facts."""

from dataclasses import replace

import pytest

from tests.helpers.correction_commands import U, environment
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


@pytest.mark.asyncio
async def test_preview_never_borrows_another_clients_order_authority():
    env = environment()
    scope = replace(env.repo.scope, actor_id=U[2])
    principal = AuthenticatedMessengerPrincipal(U[2], "telegram", "103")
    with pytest.raises(ValueError, match="^correction_own_client_required$"):
        await env.service._authority(
            scope,
            principal,
            action="preview",
            session=env.repo.session,
        )
    assert "wallets" not in env.repo.trace


@pytest.mark.asyncio
async def test_paused_admin_cannot_preview_foreign_client_sources():
    env = environment()
    env.repo.actors[U[1]]["status"] = "pause"
    principal = AuthenticatedMessengerPrincipal(U[1], "max", "202")
    with pytest.raises(ValueError, match="^correction_active_admin_required$"):
        await env.service._authority(
            replace(env.repo.scope, actor_id=U[1]),
            principal,
            action="preview",
            session=env.repo.session,
        )
    assert "wallets" not in env.repo.trace


@pytest.mark.asyncio
async def test_unknown_internal_read_action_has_no_authority():
    env = environment()
    with pytest.raises(ValueError, match="correction_read_action_invalid"):
        await env.service.authorize_read(
            env.repo.scope,
            action="invented",
            session=env.repo.session,
            principal=AuthenticatedMessengerPrincipal(U[0], "telegram", "101"),
        )
    assert not env.repo.trace


@pytest.mark.parametrize("limit", [0, 101, True, "20"])
def test_invalid_internal_page_limit_never_becomes_unbounded(limit):
    from ugc_bot.application.services.correction_view_service import (
        page_position,
    )

    with pytest.raises(ValueError, match="correction_read_request_invalid"):
        page_position(limit, None)


@pytest.mark.parametrize("bundle", [[], "invalid"])
def test_malformed_bundle_is_unavailable_instead_of_zero(bundle):
    from ugc_bot.application.services.correction_view_service import (
        request_total,
    )

    with pytest.raises(ValueError, match="correction_source_unavailable"):
        request_total({"bundle": bundle})


@pytest.mark.parametrize("missing", ["transactions", "session_factory"])
def test_factory_requires_actual_caller_database(missing, config):
    from ugc_bot.container.correction_factory import build_correction_services

    with pytest.raises(ValueError, match="correction_database_required"):
        build_correction_services(
            config,
            None if missing == "transactions" else object(),
            None if missing == "session_factory" else object(),
        )


def test_factory_does_not_invent_a_physical_bank_source(config):
    from ugc_bot.application.physical_proof_ports import (
        PhysicalProofUnavailable,
    )
    from ugc_bot.container.correction_factory import build_correction_services

    config.financial.manual_bank_source_id = ""
    config.financial.manual_bank_account_id = ""
    commands, views = build_correction_services(config, object(), object())
    assert views.commands is commands
    with pytest.raises(PhysicalProofUnavailable):
        commands.physical_proofs.resolve_manual_identity(
            "caller-supplied", "actual-reference", direction="outgoing"
        )
