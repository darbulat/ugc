"""Actual non-manager paid income can be corrected and repaid explicitly."""

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import isolated_financial_database
from tests.helpers.payout_contracts import acceptance_fields
from tests.postgres_financial.test_payout_runtime import (
    capture_env,
    payout_env,
    prepare,
    result_command,
)
from ugc_bot.application.debt_recovery_ports import (
    ApplyDebtRecovery,
    RecordDebtRepayment,
)
from ugc_bot.application.financial_review_ports import (
    OpenFinancialReview,
    ResolveFinancialReview,
)
from ugc_bot.application.payout_ports import StorePayoutRequisites
from ugc_bot.application.services.financial_review_service import (
    FinancialReviewService,
)
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.container.debt_recovery_factory import build_debt_recovery
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.repositories.financial_reviews import (
    SqlAlchemyFinancialReviewRepository,
)

__all__ = ["capture_env", "payout_env"]


@pytest.fixture(scope="module")
def financial_pg_engine():
    url = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Explicit isolated financial PostgreSQL required")
    with isolated_financial_database(
        url, target_revision="0117_financial_reviews"
    ) as engine:
        yield engine


async def reviewed_service(env):
    ledger = env["service"].repository.ledger
    from ugc_bot.application.services.financial_ledger_service import (
        FinancialLedgerService,
    )

    service = FinancialLedgerService(ledger)
    return FinancialReviewService(
        SqlAlchemyFinancialReviewRepository(),
        service,
        ObligationCompensationService(service),
        env["service"].clock,
    )


async def partner_payout(env):
    partner = env["flow"]["partner"]
    requisites = await env["execute"](
        StorePayoutRequisites(
            actor_id=partner,
            operation_key="partner-details",
            requirements_id=env["requirements"]["requirements_id"],
            accepted_terms_reference="synthetic:payout-terms",
            details=env["details"],
            **acceptance_fields(env["requirements"]),
        )
    )
    # This fixture adapter selects the real partner wallet for the existing P01.
    payable = dict(
        env, flow=dict(env["flow"], manager=partner), requisites=requisites
    )
    prepared = await prepare(payable, amount=5000, key="actual-partner-paid")
    assert (await env["execute"](result_command(env, prepared)))[
        "state"
    ] == "paid"
    return partner


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ("creator_referral",))
async def test_paid_creator_review_debt_and_actual_repayment(payout_env, kind):
    env = payout_env
    partner = await partner_payout(env)
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    obligations = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        key = db.scalar(
            select(obligations.c.business_key).where(
                obligations.c.recipient_id == partner,
                obligations.c.kind == kind,
            )
        )
    assert key is not None
    async with tm.transaction() as db:
        scope = await app.repository.load_scope(key, session=db)
        opened = await app.open(
            OpenFinancialReview(
                actor_id=env["client"],
                operation_key="postpaid-review:" + uuid4().hex,
                business_key=key,
                expected_source_hash=scope.source_hash,
                reason="Late evidence disproves part of issued income",
                evidence_reference="synthetic:late-evidence",
                evidence_hash="a" * 64,
            ),
            session=db,
        )
    assert opened["buckets"]["paid"] == 5000 and opened["state"] == "open"
    async with tm.transaction() as db:
        resolved = await app.resolve(
            ResolveFinancialReview(
                actor_id=env["client"],
                operation_key="postpaid-resolution:" + uuid4().hex,
                case_id=UUID(opened["case_id"]),
                expected_version=1,
                expected_source_hash=opened["current_source_hash"],
                decision="cumulative_cancel",
                target_minor=2000,
                reason="Independent review cancels 2000 minor liability",
                evidence_reference="synthetic:late-decision",
                evidence_hash="b" * 64,
            ),
            session=db,
        )
    assert (
        resolved["buckets"]["paid"] == 5000
        and resolved["buckets"]["debt"] == 2000
    )
    async with tm.transaction() as db:
        context = await app.context(env["client"], business_key=key, session=db)
        assert context["grounds"][0]["buckets"]["debt"] == 2000
        assert context["grounds"][0]["buckets"]["cancelled"] == 2000

    recovery = build_debt_recovery(env["config"])
    recovery.clock = app.clock
    recovery.physical_proofs.clock = app.clock
    observation = RecordDebtRepayment(
        actor_id=env["client"],
        operation_key="late-case-repayment:" + uuid4().hex,
        recipient_id=partner,
        case_id=UUID(opened["case_id"]),
        amount_minor=2000,
        currency="RUB",
        bank_account_label="synthetic-origin-account",
        bank_reference="synthetic-real-incoming:" + uuid4().hex,
        occurred_at=app.clock.now(),
        reason="Actual incoming funds returned for this case",
        evidence_reference="synthetic:incoming-bank-proof",
        evidence_hash="c" * 64,
    )
    async with tm.transaction() as db:
        receipt = await recovery.observe(observation, session=db)
    async with tm.transaction() as db:
        recovered = await recovery.apply(
            ApplyDebtRecovery(
                actor_id=env["client"],
                operation_key="late-case-apply:" + uuid4().hex,
                observation_id=UUID(receipt["observation_id"]),
                business_key=key,
                case_id=UUID(opened["case_id"]),
                expected_debt_minor=2000,
                reason="Apply observed actual repayment to this debt",
                evidence_reference="synthetic:repayment-review",
                evidence_hash="d" * 64,
            ),
            session=db,
        )
    assert recovered["remaining_debt_minor"] == 0
    async with tm.transaction() as db:
        final = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
    assert final["buckets"]["paid"] == 5000 and final["buckets"]["debt"] == 0
    assert final["buckets"]["cancelled"] == 2000


async def open_ground(env, app, key):
    tm = env["flow"]["container"].transaction_manager
    async with tm.transaction() as db:
        scope = await app.repository.load_scope(key, session=db)
        return await app.open(
            OpenFinancialReview(
                actor_id=env["client"],
                operation_key="review-open:" + uuid4().hex,
                business_key=key,
                expected_source_hash=scope.source_hash,
                reason="Late economic review",
                evidence_reference="synthetic:case-proof",
                evidence_hash="a" * 64,
            ),
            session=db,
        )


def resolve_command(env, opened, decision="no_adjustment", target=None):
    return ResolveFinancialReview(
        actor_id=env["client"],
        operation_key="review-resolve:" + uuid4().hex,
        case_id=UUID(opened["case_id"]),
        expected_version=1,
        expected_source_hash=opened["current_source_hash"],
        decision=decision,
        target_minor=target,
        reason="Reviewed liability decision",
        evidence_reference="synthetic:decision",
        evidence_hash="b" * 64,
    )


def management_key(env):
    t = Base.metadata.tables["financial_obligations"]
    with Session(env["pg"]) as db:
        return db.scalar(
            select(t.c.business_key).where(
                t.c.recipient_id == env["flow"]["manager"],
                t.c.kind == "management",
            )
        )


@pytest.mark.asyncio
async def test_open_case_allows_only_reject_of_reservation_then_cancellation(
    payout_env,
):
    from tests.postgres_financial.test_payout_runtime import (
        request_command,
        review_command,
    )
    from ugc_bot.application.services.correction_funding_guard import (
        LiveCorrectionFundingGuard,
    )
    from ugc_bot.infrastructure.db.repositories.corrections import (
        SqlAlchemyCorrectionRepository,
    )

    env = payout_env
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    request = await env["execute"](request_command(env))
    assert request["state"] == "reserved"
    opened = await open_ground(env, app, management_key(env))
    assert opened["buckets"]["reserved"] == 60000
    with pytest.raises(ValueError, match="correction_reserved_review_required"):
        async with tm.transaction() as db:
            await app.resolve(
                resolve_command(env, opened, "cumulative_cancel", 20000),
                session=db,
            )
    rejected = await env["execute"](review_command(env, request, "reject"))
    assert rejected["state"] == "rejected"
    async with tm.transaction() as db:
        current = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
        assert (
            current["state"] == "open" and current["buckets"]["reserved"] == 0
        )
        guard = LiveCorrectionFundingGuard(SqlAlchemyCorrectionRepository())
        with pytest.raises(ValueError, match="correction_unresolved"):
            await guard.require_forward_clear(
                UUID(current["paid_item_id"]), session=db
            )
        result = await app.resolve(
            resolve_command(env, current, "cumulative_cancel", 20000),
            session=db,
        )
        assert result["buckets"]["cancelled"] == 20000
        assert result["buckets"]["available"] == 40000


@pytest.mark.asyncio
async def test_case_after_execution_retains_actual_bank_fact_unapplied(
    payout_env,
):
    env = payout_env
    prepared = await prepare(env)
    app = await reviewed_service(env)
    opened = await open_ground(env, app, management_key(env))
    result = await env["execute"](result_command(env, prepared))
    assert result["state"] == "unknown" and result["block_reason"]
    with Session(env["pg"]) as db:
        outcomes = Base.metadata.tables["financial_payout_outcomes"]
        fact = (
            db.execute(
                select(outcomes).where(
                    outcomes.c.execution_id == prepared["execution_id"]
                )
            )
            .mappings()
            .one()
        )
        assert fact["status"] == "paid" and not fact["applied"]
    tm = env["flow"]["container"].transaction_manager
    async with tm.transaction() as db:
        current = await app.view(
            env["client"], UUID(opened["case_id"]), session=db
        )
        assert (
            current["buckets"]["paid"] == 0
            and current["buckets"]["reserved"] == 60000
        )


@pytest.mark.asyncio
async def test_mature_restore_is_exact_and_sql_rejects_extra_restore(
    payout_env, monkeypatch
):
    from sqlalchemy.exc import IntegrityError

    from ugc_bot.application.financial_ports import JournalMovement

    env = payout_env
    app = await reviewed_service(env)
    tm = env["flow"]["container"].transaction_manager
    opened = await open_ground(env, app, management_key(env))
    assert (
        opened["buckets"]["blocked"] == 60000
        and opened["buckets"]["available"] == 0
    )
    append = app.repository.append_resolution

    async def false_restore(fact, *, session):
        await append(
            dict(
                fact, restored_buckets=dict(pending=0, hold=0, available=60001)
            ),
            session=session,
        )

    monkeypatch.setattr(app.repository, "append_resolution", false_restore)
    with pytest.raises(
        IntegrityError, match="financial_review_restore_maturity_mismatch"
    ):
        async with tm.transaction() as db:
            await app.resolve(resolve_command(env, opened), session=db)
    monkeypatch.setattr(app.repository, "append_resolution", append)
    async with tm.transaction() as db:
        result = await app.resolve(resolve_command(env, opened), session=db)
        assert (
            result["buckets"]["available"] == 60000
            and result["buckets"]["blocked"] == 0
        )
    with pytest.raises(
        IntegrityError, match="financial_review_restore_movement_mismatch"
    ):
        async with tm.transaction() as db:
            await app.ledger.repository.append(
                JournalMovement(
                    obligation_id=UUID(opened["obligation_id"]),
                    operation_key="financial-review:"
                    + opened["case_id"]
                    + ":restore:available:extra",
                    event_id=opened["case_id"],
                    movement_type="transfer",
                    amount_minor=1,
                    currency="RUB",
                    effective_at=app.clock.now(),
                    recorded_at=app.clock.now(),
                    actor_id=env["client"],
                    actor_kind="admin",
                    reason="Forged extra restoration",
                    bucket_from="blocked",
                    bucket_to="available",
                    case_id=UUID(opened["case_id"]),
                ),
                session=db,
            )
