"""Independent pure owner-binding reproductions; no SQL acceptance."""

from uuid import UUID

import pytest

from tests.helpers.correction_commands import U, environment, request


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["case", "operation"])
@pytest.mark.parametrize(
    "field,value", [("client_id", U[2]), ("order_id", U[9])]
)
async def test_nonnull_case_binding_cannot_be_hidden_by_request(
    entry, field, value
):
    env = environment()
    own = await env.execute(request())
    # Declared inconsistent retained facts: a non-null immutable case binding
    # disagrees with the genuine request/current order scope.
    env.repo.rows["cases"][0][field] = value
    env.repo.trace.clear()

    with pytest.raises(ValueError):
        if entry == "case":
            await env.service.get_for_actor(
                UUID(own["case_id"]), U[0], session=env.repo.session
            )
        else:
            await env.service.operation_for_actor(
                U[0], "request", session=env.repo.session
            )
    assert "wallets" not in env.repo.trace
    assert "facts" not in env.repo.trace
    assert "receipt" not in env.repo.trace


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"client_id": None},
        {"order_id": None},
        {"client_id": None, "order_id": None},
    ],
)
async def test_nullable_early_case_bindings_use_genuine_request(changes):
    env = environment()
    own = await env.execute(request())
    env.repo.rows["cases"][0].update(changes)
    result = await env.service.get_for_actor(
        UUID(own["case_id"]), U[0], session=env.repo.session
    )
    assert result["case_id"] == own["case_id"]
    assert not result["state_unavailable"]
