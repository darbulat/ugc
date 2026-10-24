"""A retained linked match must agree with its approval's actual order."""

import pytest

from tests.helpers.correction_approvals import (
    U,
    captured_approval,
    environment,
    faithful_legacy_authority,
    match,
    observation,
    review,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "corrupt", ["match", "approval", "legacy_match", "both"]
)
async def test_historical_match_link_order_must_agree_before_new_match(corrupt):
    env = environment()
    approved = await captured_approval(env)
    if corrupt == "legacy_match":
        faithful_legacy_authority(env, approved)
    observed = await env.execute(observation(approved))
    matched = await env.execute(match(observed, approved, observed))
    fresh = await env.execute(
        review(matched, operation_key="fresh-review-before-order-corruption")
    )
    kind = "approvals" if corrupt == "approval" else "matches"
    env.repo.rows[kind][0]["order_id"] = U[10]
    if corrupt == "both":
        env.repo.rows["approvals"][0]["order_id"] = U[10]

    with pytest.raises(ValueError):
        await env.execute(
            match(
                fresh,
                fresh,
                observed,
                operation_key="new-match-after-linked-order-corruption",
            )
        )
    assert len(env.repo.rows["matches"]) == 1
