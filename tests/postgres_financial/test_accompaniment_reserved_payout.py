"""An actual accompaniment refund can safely release an existing reservation."""

from uuid import UUID, uuid4

import pytest

from tests.postgres_financial.test_financial_reviews import financial_pg_engine
from tests.postgres_financial.test_payout_runtime import (
    capture_env,
    payout_env,
    prepare,
    request_command,
    result_command,
    review_command,
    wallet,
)
from ugc_bot.application.accompaniment_refund_ports import (
    ApplyAccompanimentRefund,
    ObserveAccompanimentRefund,
)
from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)
from ugc_bot.container.correction_factory import (
    build_accompaniment_refund_service,
)
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)

__all__ = ["financial_pg_engine", "capture_env", "payout_env"]

REVIEW_RULES = RefundRules(
    3600, "item_delivered", "all_positions_resolved", (), "manual_review"
)


async def actual_refund(env, *, customer_minor=60000):
    tm = env["flow"]["container"].transaction_manager
    service = build_accompaniment_refund_service(
        env["config"], tm, env["flow"]["container"].session_factory
    )
    service.clock = env["service"].clock
    service.physical_proofs.clock = service.clock
    async with tm.transaction() as db:
        scope = await service.repository.load_scope(
            env["flow"]["item"], session=db
        )
        assert scope.work_stage == "available" and scope.manager_earned
        observation = await service.observe(
            ObserveAccompanimentRefund(
                actor_id=env["client"],
                operation_key="actual-accompaniment-report:" + uuid4().hex,
                paid_item_id=env["flow"]["item"],
                original_payment_reference=scope.original_payment_reference,
                amount_minor=customer_minor,
                currency="RUB",
                bank_account_label="synthetic-origin-account",
                bank_reference="synthetic-actual-refund:" + uuid4().hex,
                occurred_at=service.clock.now(),
                reason="Observed actual partial customer refund",
                evidence_reference="synthetic:actual-outgoing-bank-proof",
                evidence_hash="a" * 64,
            ),
            session=db,
        )
    assert observation["proof_claimed"] and not observation["applied"]
    command = ApplyAccompanimentRefund(
        actor_id=env["client"],
        operation_key="actual-accompaniment-apply:" + uuid4().hex,
        observation_id=UUID(observation["observation_id"]),
        paid_item_id=env["flow"]["item"],
        expected_work_version=scope.work_version,
        reviewed_customer_target_minor=customer_minor,
        reviewed_manager_target_minor=30000,
        reason="Explicit review cancels half of earned management liability",
        evidence_reference="synthetic:partial-service-review",
        evidence_hash="b" * 64,
    )
    return service, command


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [REVIEW_RULES], indirect=True)
async def test_reserved_manager_refund_releases_only_by_explicit_rejection(
    payout_env,
):
    env = payout_env
    tm = env["flow"]["container"].transaction_manager
    manager = env["flow"]["manager"]
    request = await env["execute"](request_command(env))
    assert wallet(env, manager)["reserved_minor"] == 60000
    refunds, command = await actual_refund(env)
    with pytest.raises(ValueError, match="correction_reserved_review_required"):
        async with tm.transaction() as db:
            await refunds.apply(command, session=db)
    blocked = await env["execute"](review_command(env, request, "review"))
    assert blocked["state"] == "blocked"
    assert wallet(env, manager)["reserved_minor"] == 60000
    with pytest.raises(ValueError, match="active_admin_required"):
        await env["execute"](
            review_command(env, blocked, "reject", actor_id=manager)
        )
    rejected = await env["execute"](review_command(env, blocked, "reject"))
    assert rejected["state"] == "rejected"
    assert wallet(env, manager)["reserved_minor"] == 0
    assert wallet(env, manager)["available_minor"] == 60000
    with pytest.raises(ValueError, match="correction_unresolved"):
        await env["execute"](
            request_command(env, operation_key="refund-still-unapplied")
        )
    guard = LiveCorrectionFundingGuard(SqlAlchemyCorrectionRepository())
    async with tm.transaction() as db:
        with pytest.raises(ValueError, match="correction_unresolved"):
            await guard.require_forward_clear(command.paid_item_id, session=db)
        scope = await refunds.repository.load_scope(
            command.paid_item_id, session=db
        )
        assert scope.work_version == command.expected_work_version
        applied = await refunds.apply(command, session=db)
        assert await refunds.apply(command, session=db) == applied
    assert applied["manager_adjustment_minor"] == 30000
    assert applied["customer_refund_minor"] == 60000
    balance = wallet(env, manager)
    assert balance["available_minor"] == balance["cancelled_minor"] == 30000
    assert balance["reserved_minor"] == balance["paid_minor"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("capture_env", [REVIEW_RULES], indirect=True)
@pytest.mark.parametrize("state", ["executing", "unknown", "paid"])
async def test_observed_refund_cannot_release_a_started_or_paid_transfer(
    payout_env, state
):
    env = payout_env
    manager = env["flow"]["manager"]
    prepared = await prepare(env)
    request = prepared
    if state == "paid":
        request = await env["execute"](result_command(env, prepared))
    elif state == "unknown":
        request = await env["execute"](
            result_command(
                env,
                prepared,
                status="unknown",
                amount_minor=None,
                currency=None,
                settled_at=None,
                recipient_details={},
            )
        )
    assert request["state"] == state
    await actual_refund(env)
    before = dict(wallet(env, manager))
    with pytest.raises(ValueError, match="payout_state_not_reviewable"):
        await env["execute"](review_command(env, request, "reject"))
    assert dict(wallet(env, manager)) == before
