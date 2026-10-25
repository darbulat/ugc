"""Stored stage rules require actual bank evidence and manager ground."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_work_entitlement_service import setup
from ugc_bot.application.accompaniment_refund_ports import (
    AccompanimentRefundScope,
    ApplyAccompanimentRefund,
)
from ugc_bot.application.services.accompaniment_refund_service import (
    AccompanimentRefundService,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.domain.refund_rules import RefundRules


class Repo:
    def __init__(self, scope, actor, amount):
        self.scope, self.actor, self.amount = scope, actor, amount
        self.commands, self.applications = {}, []
        self.observation_id = uuid4()

    async def load_scope(self, item_id, *, session):
        return self.scope

    async def lock_scope(self, scope, *, session):
        pass

    async def load_actor(self, actor_id, *, session):
        return SimpleNamespace(
            user_id=actor_id,
            telegram_id=None,
            max_id=None,
            admin=actor_id == self.actor,
            status="active",
        )

    async def get_command(self, actor_id, key, *, session):
        return self.commands.get(key)

    async def save_command(self, actor_id, key, digest, result, *, session):
        self.commands[key] = (digest, result)

    async def observation(self, identity, *, session):
        return {
            "observation_id": identity,
            "paid_item_id": self.scope.paid_item_id,
            "payment_id": self.scope.capture.payment_id,
            "original_payment_reference": "real-original",
            "amount_minor": self.amount,
            "currency": "RUB",
            "proof_claimed": True,
        }

    async def totals(self, item_id, *, session):
        return (
            sum(a["customer_delta_minor"] for a in self.applications),
            max(
                (a["manager_target_minor"] for a in self.applications),
                default=0,
            ),
        )

    async def application(self, identity, *, session):
        return next(
            (a for a in self.applications if a["observation_id"] == identity),
            None,
        )

    async def append_application(self, fact, *, session):
        self.applications.append(fact)


class Compensation:
    def __init__(self):
        self.calls = []

    async def cancel(self, original, **kwargs):
        self.calls.append((original, kwargs))
        return ()


@pytest.mark.asyncio
async def test_partial_accompaniment_retains_selection_and_manager_mode():
    work_repo, ledger, _, clock, _, _, _ = setup(final=True)
    snap = work_repo.snapshot
    rules = RefundRules(
        3600,
        "item_delivered",
        "all_positions_resolved",
        (("success_final", 5000),),
        "retain_earned",
    )
    capture = replace(
        snap.capture, policy=replace(snap.capture.policy, refund_rules=rules)
    )
    actor = uuid4()
    repo = Repo(
        AccompanimentRefundScope(capture, snap.record, "real-original"),
        actor,
        60000,
    )
    compensation = Compensation()
    service = AccompanimentRefundService(
        repo, FinancialLedgerService(ledger), None, compensation, clock
    )
    command = ApplyAccompanimentRefund(
        actor_id=actor,
        operation_key="apply",
        observation_id=repo.observation_id,
        paid_item_id=snap.record.paid_item_id,
        expected_work_version=snap.record.version,
        reason="Reviewed actual refund",
        evidence_reference="protected:review",
        evidence_hash="a" * 64,
    )
    async with ledger.transaction() as session:
        result = await service.apply(command, session=session)
        assert (
            result["customer_refund_minor"] == 60000
            and result["manager_adjustment_minor"] == 0
        )
        assert await service.apply(command, session=session) == result
    assert not compensation.calls and not ledger.movements
    assert repo.applications[0]["rules"] == rules.to_document()
    assert repo.applications[0]["stage"] == "success_final"
    assert len(repo.applications) == 1


@pytest.mark.asyncio
async def test_missing_stage_and_bank_mismatch_require_review():
    work_repo, ledger, _, clock, _, _, _ = setup()
    snap = work_repo.snapshot
    rules = RefundRules(
        3600, "item_delivered", "all_positions_resolved", (), "manual_review"
    )
    capture = replace(
        snap.capture, policy=replace(snap.capture.policy, refund_rules=rules)
    )
    actor = uuid4()
    repo = Repo(
        AccompanimentRefundScope(capture, snap.record, "real-original"),
        actor,
        60000,
    )
    service = AccompanimentRefundService(
        repo, FinancialLedgerService(ledger), None, Compensation(), clock
    )
    command = ApplyAccompanimentRefund(
        actor_id=actor,
        operation_key="review",
        observation_id=repo.observation_id,
        paid_item_id=snap.record.paid_item_id,
        expected_work_version=snap.record.version,
        reason="Review",
        evidence_reference="private:proof",
        evidence_hash="a" * 64,
    )
    async with ledger.transaction() as session:
        with pytest.raises(
            ValueError, match="accompaniment_manual_review_required"
        ):
            await service.apply(command, session=session)
        with pytest.raises(
            ValueError, match="accompaniment_bank_amount_mismatch"
        ):
            await service.apply(
                replace(
                    command,
                    reviewed_customer_target_minor=120000,
                    reviewed_manager_target_minor=0,
                ),
                session=session,
            )
    assert not repo.applications


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,target",
    (("retain_earned", 0), ("proportional", 30000), ("manual_review", 10000)),
)
async def test_success_original_is_assessed_once_before_compensation(
    mode, target
):
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )

    work_repo, ledger, _, clock, _, _, _ = setup(final=True)
    snap = work_repo.snapshot
    rules = RefundRules(
        3600,
        "item_delivered",
        "all_positions_resolved",
        (("success_final", 5000),),
        mode,
    )
    capture = replace(
        snap.capture, policy=replace(snap.capture.policy, refund_rules=rules)
    )
    actor = uuid4()
    repo = Repo(
        AccompanimentRefundScope(capture, snap.record, "real-original", True),
        actor,
        60000,
    )
    service = AccompanimentRefundService(
        repo,
        FinancialLedgerService(ledger),
        None,
        ObligationCompensationService(FinancialLedgerService(ledger)),
        clock,
    )
    command = ApplyAccompanimentRefund(
        actor_id=actor,
        operation_key="earned-manager",
        observation_id=repo.observation_id,
        paid_item_id=snap.record.paid_item_id,
        expected_work_version=snap.record.version,
        reason="Real successful management",
        evidence_reference="private-evidence",
        evidence_hash="b" * 64,
        reviewed_manager_target_minor=target
        if mode == "manual_review"
        else None,
    )
    async with ledger.transaction() as session:
        result = await service.apply(command, session=session)
        assert result["manager_adjustment_minor"] == target
        wallet = await ledger.read_projection(
            snap.scope.manager_id, "RUB", session=session
        )
        assert wallet["cancelled"] == target
        assert wallet["pending"] == 60000 - target
    assert len(ledger.records) == 1
    original = next(iter(ledger.records.values()))
    assert original.basis.base_minor == original.movement.amount_minor == 60000
    assert original.basis.snapshot_at == capture.captured_at


@pytest.mark.asyncio
@pytest.mark.parametrize("prior,increment", [(10000, 20000), (40000, 0)])
async def test_refund_manager_target_uses_all_original_cancellations(
    prior, increment
):
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )

    work_repo, ledger, _, clock, _, _, _ = setup(final=True)
    snap = work_repo.snapshot
    rules = RefundRules(
        3600,
        "item_delivered",
        "all_positions_resolved",
        (("success_final", 5000),),
        "proportional",
    )
    capture = replace(
        snap.capture, policy=replace(snap.capture.policy, refund_rules=rules)
    )
    actor = uuid4()
    repo = Repo(
        AccompanimentRefundScope(capture, snap.record, "real-original", True),
        actor,
        60000,
    )
    financial = FinancialLedgerService(ledger)
    compensation = ObligationCompensationService(financial)
    service = AccompanimentRefundService(
        repo, financial, None, compensation, clock
    )
    command = ApplyAccompanimentRefund(
        actor_id=actor,
        operation_key="refund-after-review",
        observation_id=repo.observation_id,
        paid_item_id=snap.record.paid_item_id,
        expected_work_version=snap.record.version,
        reason="Actual refund after an independent liability cancellation",
        evidence_reference="private:actual-refund-review",
        evidence_hash="e" * 64,
    )
    async with ledger.transaction() as session:
        original = await service._assess_original_management(
            repo.scope, clock.now(), session
        )
        await compensation.cancel(
            original,
            target_minor=prior,
            already_cancelled_minor=0,
            case_id=uuid4(),
            refund_id=uuid4(),
            actor_id=actor,
            now=clock.now(),
            session=session,
        )
        result = await service.apply(command, session=session)
        assert result["manager_adjustment_minor"] == increment
        assert result["customer_refund_minor"] == 60000
        assert await service.apply(command, session=session) == result
        wallet = await ledger.read_projection(
            snap.scope.manager_id, "RUB", session=session
        )
    assert wallet["cancelled"] == max(prior, 30000)
    assert repo.applications[0]["manager_target_minor"] == 30000
    assert repo.applications[0]["manager_delta_minor"] == increment


@pytest.mark.asyncio
async def test_absent_work_requires_review_without_manager_reward():
    work_repo, ledger, _, clock, _, _, _ = setup()
    snap = work_repo.snapshot
    rules = RefundRules(
        3600, "item_delivered", "all_positions_resolved", (), "manual_review"
    )
    capture = replace(
        snap.capture, policy=replace(snap.capture.policy, refund_rules=rules)
    )
    actor = uuid4()
    scope = AccompanimentRefundScope(
        capture, None, "real-original", paid_item_id=snap.record.paid_item_id
    )
    repo = Repo(scope, actor, 60000)
    service = AccompanimentRefundService(
        repo, FinancialLedgerService(ledger), None, Compensation(), clock
    )
    command = ApplyAccompanimentRefund(
        actor_id=actor,
        operation_key="absence-apply",
        observation_id=repo.observation_id,
        paid_item_id=snap.record.paid_item_id,
        expected_work_version=0,
        reason="No work started; actual partial refund reviewed",
        evidence_reference="protected:absence-and-bank",
        evidence_hash="a" * 64,
    )
    async with ledger.transaction() as session:
        with pytest.raises(
            ValueError, match="accompaniment_manual_review_required"
        ):
            await service.apply(command, session=session)
        approved = replace(
            command,
            reviewed_customer_target_minor=60000,
            reviewed_manager_target_minor=0,
        )
        result = await service.apply(approved, session=session)
    assert result["customer_refund_minor"] == 60000
    assert result["manager_adjustment_minor"] == 0
    assert (
        repo.applications[0]["assignment_id"]
        is repo.applications[0]["stage"]
        is None
    )
    assert repo.applications[0]["work_version"] == 0
    assert not ledger.records and not ledger.movements
