"""Independent pure reproductions; no SQL or concurrency evidence."""

from uuid import UUID

import pytest

from tests.application.services.test_correction_service import review
from tests.helpers.correction_commands import U, environment, request
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entry,platform",
    [("execute", "telegram"), ("case", "max"), ("operation", "telegram")],
)
async def test_stale_native_denial_precedes_changed_private_source(
    entry, platform
):
    env = environment()
    own = await env.execute(request())
    command = review(own)
    await env.execute(command)
    field = "telegram_id" if platform == "telegram" else "max_id"
    principal = AuthenticatedMessengerPrincipal(
        U[1], platform, env.repo.actors[U[1]][field]
    )
    env.repo.actors[U[1]][field] = "remapped-native-id"
    # The frozen fake models the real repository's load_scope refusal inside
    # lock_scope. The real method is inspected as text, never imported here.
    env.repo.changed = True
    env.repo.trace.clear()

    with pytest.raises(ValueError, match="^financial_principal_changed$"):
        if entry == "execute":
            await env.execute(command, principal=principal)
        elif entry == "case":
            await env.service.get_for_actor(
                UUID(own["case_id"]),
                U[1],
                session=env.repo.session,
                principal=principal,
            )
        else:
            await env.service.operation_for_actor(
                U[1],
                command.operation_key,
                session=env.repo.session,
                principal=principal,
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["execute", "operation"])
async def test_revoked_admin_denial_precedes_changed_private_source(entry):
    env = environment()
    command = review(await env.execute(request()))
    await env.execute(command)
    env.repo.actors[U[1]]["admin"] = False
    env.repo.changed = True
    env.repo.trace.clear()

    with pytest.raises(ValueError, match="^correction_active_admin_required$"):
        if entry == "execute":
            await env.execute(command)
        else:
            await env.service.operation_for_actor(
                U[1], command.operation_key, session=env.repo.session
            )


@pytest.mark.asyncio
async def test_foreign_own_denial_precedes_changed_private_source():
    env = environment()
    env.repo.changed = True
    with pytest.raises(ValueError, match="^correction_own_client_required$"):
        await env.execute(request(actor_id=U[2], operation_key="foreign"))


@pytest.mark.asyncio
async def test_current_authorized_actor_still_requires_source_refresh():
    env = environment()
    command = review(await env.execute(request()))
    env.repo.changed = True
    with pytest.raises(
        ValueError, match="^correction_scope_changed_retry_required$"
    ):
        await env.execute(command)
