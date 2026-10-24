"""Pure immutable observation replay through the actual delivery writer.

The first transport fact is appended by the real accepted-result flow. These
checks assert existing behavior; they do not claim a newly discovered bug or
PostgreSQL/schema acceptance for intentionally conflicting candidate fields.
"""

from dataclasses import asdict
from datetime import timedelta
from uuid import uuid5

import pytest

from tests.application.services import (
    test_paid_selection_finish_scope_retention as retained,
)

env = retained.env
__all__ = ["env"]


async def replay(env, attempt, fact):
    async with env.transactions.transaction() as session:
        return await env.worker._observe(
            env.repo.current_job,
            attempt,
            fact["kind"],
            fact["status"],
            fact["provider_reference"],
            fact["reason"],
            fact["applied"],
            session,
        )


@pytest.mark.asyncio
async def test_exact_retained_observation_replay_preserves_original_fact(env):
    attempt = await retained.accepted_then_scope_changed(env)
    original = env.repo.outcomes[uuid5(attempt.attempt_id, "transport")]
    history = dict(env.repo.outcomes)
    original_job = env.repo.current_job
    env.clock.at += timedelta(minutes=1)
    repeated = await replay(env, attempt, asdict(original))
    assert repeated == original
    assert repeated.outcome_id == original.outcome_id
    assert repeated.recorded_at < env.clock.now()
    assert asdict(repeated) == asdict(original)
    assert env.repo.outcomes == history
    assert env.repo.current_job == original_job
    assert env.repo.accepted == []
    assert env.bot.calls == [attempt]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("provider_reference", "synthetic-different-receipt"),
        ("reason", "synthetic_different_review_reason"),
        ("applied", True),
    ],
)
async def test_changed_observation_field_conflicts_without_rewriting_history(
    env, field, value
):
    attempt = await retained.accepted_then_scope_changed(env)
    original = env.repo.outcomes[uuid5(attempt.attempt_id, "transport")]
    history = dict(env.repo.outcomes)
    original_job = env.repo.current_job
    env.clock.at += timedelta(minutes=1)
    changed = asdict(original) | {field: value}
    with pytest.raises(ValueError, match="^selection_outcome_conflict$"):
        await replay(env, attempt, changed)
    assert env.repo.outcomes == history
    assert env.repo.outcomes[original.outcome_id] == original
    assert env.repo.current_job == original_job
    assert env.repo.accepted == []
    assert env.bot.calls == [attempt]
