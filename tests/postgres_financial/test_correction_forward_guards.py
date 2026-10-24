"""Live blockers follow retained facts and the actual affected positions."""

from uuid import UUID, uuid4

import pytest

from tests.helpers.correction_approval_pg import approval_runtime
from tests.postgres_financial.test_order_intake import intake_env as intake_env
from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)

__all__ = ["intake_env"]


async def funding(rt, item_id):
    from sqlalchemy import event

    engine = rt.env["container"].session_factory.kw["bind"].sync_engine
    statements = []

    def before(connection, cursor, statement, parameters, context, many):
        statements.append(statement.lstrip().upper())

    event.listen(engine, "before_cursor_execute", before)
    try:
        async with rt.env["container"].transaction_manager.transaction() as db:
            result = await LiveCorrectionFundingGuard(rt.repo).load_item(
                item_id, session=db
            )
    finally:
        event.remove(engine, "before_cursor_execute", before)
    assert statements
    assert not any(
        sql.startswith(("INSERT ", "UPDATE ", "DELETE ", "ALTER ", "DROP "))
        or any(
            lock in sql
            for lock in (
                "FOR UPDATE",
                "FOR NO KEY UPDATE",
                "FOR SHARE",
                "FOR KEY SHARE",
                "PG_ADVISORY",
            )
        )
        for sql in statements
    )
    return result


async def forward(rt, item_id):
    async with rt.env["container"].transaction_manager.transaction() as db:
        await LiveCorrectionFundingGuard(rt.repo).require_forward_clear(
            item_id, session=db
        )


@pytest.mark.asyncio
async def test_rejected_request_without_bank_fact_does_not_keep_live_blocker(
    intake_env,
):
    rt = await approval_runtime(intake_env)
    command = await rt.request()
    requested = await rt.execute(command)
    rejected = await rt.execute(rt.review(requested, decision="reject"))
    assert rejected["review_status"] == "rejected"
    assert rt.rows("observations", case_id=UUID(requested["case_id"])) == []
    lines = await funding(rt, command.paid_item_ids[0])
    assert len(lines) == 1
    assert lines[0].gross_minor == lines[0].net_minor == 50000
    assert lines[0].state_consistent
    assert lines[0].unresolved_observation_ids == ()
    assert lines[0].unresolved_case_ids == ()
    await forward(rt, command.paid_item_ids[0])


@pytest.mark.asyncio
async def test_case_report_blocks_selected_positions_only(
    intake_env,
):
    rt = await approval_runtime(intake_env)
    command = await rt.request()
    requested = await rt.execute(command)
    approved = await rt.execute(rt.review(requested))
    observed = await rt.execute(rt.observation(approved))
    selected = await funding(rt, command.paid_item_ids[0])
    assert selected[0].unresolved_observation_ids == (
        UUID(observed["observation_id"]),
    )
    assert selected[0].unresolved_case_ids == (UUID(requested["case_id"]),)
    assert selected[0].net_minor == 50000
    sibling = rt.facts["order"].items[0].paid_item_id
    assert sibling not in command.paid_item_ids
    unaffected = await funding(rt, sibling)
    assert unaffected[0].unresolved_observation_ids == ()
    assert unaffected[0].unresolved_case_ids == ()
    assert unaffected[0].net_minor == 50000
    await forward(rt, sibling)
    with pytest.raises(ValueError, match="^correction_unresolved$"):
        await forward(rt, command.paid_item_ids[0])


@pytest.mark.asyncio
async def test_rejection_cannot_clear_a_retained_actual_refund_report(
    intake_env,
):
    rt = await approval_runtime(intake_env)
    command = await rt.request()
    requested = await rt.execute(command)
    approved = await rt.execute(rt.review(requested))
    observed = await rt.execute(rt.observation(approved))
    before = rt.rows("observations", case_id=UUID(requested["case_id"]))
    rejected = await rt.execute(rt.review(observed, decision="reject"))
    assert rejected["review_status"] == "rejected"
    lines = await funding(rt, command.paid_item_ids[0])
    assert lines[0].unresolved_observation_ids == (
        UUID(observed["observation_id"]),
    )
    assert lines[0].unresolved_case_ids == (UUID(requested["case_id"]),)
    assert lines[0].net_minor == lines[0].gross_minor == 50000
    assert rt.rows("observations", case_id=UUID(requested["case_id"])) == before


@pytest.mark.asyncio
async def test_known_order_report_cannot_block_another_actual_captured_order(
    intake_env,
):
    from tests.postgres_financial.test_order_intake import (
        intake_env as make_env,
    )

    rt = await approval_runtime(intake_env)
    approved = await rt.approved()
    await rt.execute(rt.observation(approved))
    async for other in make_env.__wrapped__(rt.env["pg"]):
        unrelated = await approval_runtime(other)
        other_id = unrelated.facts["order"].items[-1].paid_item_id
        assert unrelated.facts["order"].order_id != rt.facts["order"].order_id
        line = (await funding(unrelated, other_id))[0]
        assert line.net_minor == 50000
        assert line.unresolved_case_ids == line.unresolved_observation_ids == ()
        await forward(unrelated, other_id)


@pytest.mark.asyncio
async def test_case_scope_wins_over_conflicting_foreign_report_hints(
    intake_env,
):
    from tests.postgres_financial.test_order_intake import (
        intake_env as make_env,
    )

    rt = await approval_runtime(intake_env)
    approved = await rt.approved()
    async for other in make_env.__wrapped__(rt.env["pg"]):
        unrelated = await approval_runtime(other)
        report = rt.observation(
            approved,
            known_order_id=unrelated.facts["order"].order_id,
            known_capture_intent_id=unrelated.facts["invoice_id"],
            original_payment_reference=unrelated.facts["payment"].external_id,
        )
        observed = await rt.execute(report)
        other_id = unrelated.facts["order"].items[0].paid_item_id
        await forward(unrelated, other_id)
        own_id = rt.facts["order"].items[-1].paid_item_id
        own = (await funding(rt, own_id))[0]
        assert own.unresolved_observation_ids == (
            UUID(observed["observation_id"]),
        )
        assert own.net_minor == 50000


@pytest.mark.asyncio
@pytest.mark.parametrize("referred", [False, True])
async def test_completed_refund_clears_report_and_denies_forward(
    intake_env, referred
):
    from tests.helpers.correction_approval_pg import genuine_approved_match
    from tests.helpers.correction_runtime_pg import Runtime
    from tests.helpers.corrections import (
        append_application,
        assess_original,
        captured_order,
    )

    env = intake_env
    facts = await captured_order(env, referred=referred)
    await assess_original(env, facts)
    rt = Runtime(env, facts)
    async with env["container"].transaction_manager.transaction() as db:
        match = await genuine_approved_match(env, facts, rt.repo, db)
        async with rt.repo.application_savepoint(session=db):
            await append_application(env, facts, rt.repo, match, db)
    selected = match["scope"].selected_paid_item_ids[0]
    line = (await funding(rt, selected))[0]
    assert (line.gross_minor, line.cumulative_refund_minor, line.net_minor) == (
        50000,
        50000,
        0,
    )
    assert line.unresolved_case_ids == line.unresolved_observation_ids == ()
    with pytest.raises(ValueError, match="^correction_component_refunded$"):
        await forward(rt, selected)
    await forward(rt, facts["order"].items[0].paid_item_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
async def test_active_case_without_report_blocks_only_requested_positions(
    intake_env, approved
):
    rt = await approval_runtime(intake_env)
    command = await rt.request()
    requested = await rt.execute(command)
    if approved:
        await rt.execute(rt.review(requested))
    selected = await funding(rt, command.paid_item_ids[0])
    assert selected[0].unresolved_case_ids == (UUID(requested["case_id"]),)
    assert selected[0].unresolved_observation_ids == ()
    assert selected[0].net_minor == 50000
    sibling = await funding(rt, rt.facts["order"].items[0].paid_item_id)
    assert sibling[0].unresolved_case_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("hint", ["order", "invoice", "both", "unknown"])
async def test_early_report_requires_real_order_or_invoice_correlation(
    intake_env, hint
):
    from tests.helpers.correction_approval_pg import capture_pending

    rt = await approval_runtime(intake_env, early=True)
    observed = await rt.execute(
        rt.observation(
            known_order_id=rt.facts["order"].order_id
            if hint in ("order", "both")
            else None,
            known_capture_intent_id=rt.facts["invoice_id"]
            if hint in ("invoice", "both")
            else None,
        )
    )
    before = rt.rows("observations", case_id=UUID(observed["case_id"]))
    await capture_pending(rt)
    lines = await funding(rt, rt.facts["order"].items[0].paid_item_id)
    assert lines[0].unresolved_observation_ids == (
        () if hint == "unknown" else (UUID(observed["observation_id"]),)
    )
    assert lines[0].unresolved_case_ids == (
        () if hint == "unknown" else (UUID(observed["case_id"]),)
    )
    assert lines[0].state_consistent and lines[0].net_minor == 50000
    assert rt.rows("observations", case_id=UUID(observed["case_id"])) == before


@pytest.mark.asyncio
async def test_early_scope_narrows_after_real_request_without_rewriting_report(
    intake_env,
):
    from tests.helpers.correction_approval_pg import capture_pending

    rt = await approval_runtime(intake_env, early=True)
    observed = await rt.execute(rt.observation())
    before = rt.rows("observations", case_id=UUID(observed["case_id"]))
    await capture_pending(rt)
    sibling_id = rt.facts["order"].items[0].paid_item_id
    assert (await funding(rt, sibling_id))[0].unresolved_observation_ids
    command = await rt.request(existing_case_id=UUID(observed["case_id"]))
    await rt.execute(command)
    assert sibling_id not in command.paid_item_ids
    assert (await funding(rt, sibling_id))[0].unresolved_observation_ids == ()
    selected = await funding(rt, command.paid_item_ids[0])
    assert selected[0].unresolved_observation_ids == (
        UUID(observed["observation_id"]),
    )
    assert rt.rows("observations", case_id=UUID(observed["case_id"])) == before


@pytest.mark.asyncio
async def test_early_case_corrupt_projection_makes_funding_unavailable(
    intake_env,
):
    from sqlalchemy import update

    from tests.helpers.correction_approval_pg import capture_pending
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP

    rt = await approval_runtime(intake_env, early=True)
    observed = await rt.execute(rt.observation())
    await capture_pending(rt)
    # Mutable projection fault; no immutable bank/event fact is rewritten.
    with rt.env["pg"].begin() as db:
        db.execute(
            update(TABLE_MAP["states"])
            .where(TABLE_MAP["states"].c.case_id == UUID(observed["case_id"]))
            .values(result_state_hash="f" * 64)
        )
    lines = await funding(rt, rt.facts["order"].items[0].paid_item_id)
    assert not lines[0].state_consistent
    assert lines[0].net_minor is None
    assert lines[0].unresolved_case_ids == (UUID(observed["case_id"]),)


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", [["not-a-uuid"], [str(uuid4())]])
async def test_malformed_retained_request_cannot_hide_affected_order(
    intake_env, selected
):
    from tests.helpers.correction_approval_pg import alter_fact

    rt = await approval_runtime(intake_env)
    # Declared new INSERT fault after admission; no history mutation.
    with alter_fact(
        rt, "requests", lambda row: row | {"paid_item_ids": selected}
    ):
        requested = await rt.execute(await rt.request())
    lines = await funding(rt, rt.facts["order"].items[0].paid_item_id)
    assert not lines[0].state_consistent
    assert lines[0].net_minor is None
    assert lines[0].unresolved_case_ids == (UUID(requested["case_id"]),)
