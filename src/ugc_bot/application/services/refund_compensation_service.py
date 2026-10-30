"""Apply a proven full selection refund to its original pending liability."""

from uuid import UUID, uuid4

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.corrections import pending_cancellation_delta
from ugc_bot.domain.financial import utc


class RefundAssessmentUnavailable(ValueError):
    """Keep the actual match and bank evidence pending explicit assessment."""


class SelectionRefundCompensationService:
    def __init__(self, repository, ledger, original_assessment=None):
        self.repository, self.ledger = repository, ledger
        self.original_assessment = original_assessment

    async def apply(
        self, scope, matched, *, actor_id, now, session, command_id=None
    ):
        now = utc(now)
        repo, ledger = self.repository, self.ledger.repository
        existing = await repo.refund_application(
            UUID(matched["match_id"]), session=session
        )
        if existing is not None:
            return {
                "applied": True,
                "application_id": str(existing["application_id"]),
            }
        expected = (
            scope.order_id,
            scope.payment_id,
            scope.capture_id,
            scope.source_hash,
            scope.bundle.total_minor,
            "RUB",
        )
        actual = (
            UUID(matched["order_id"]),
            UUID(matched["payment_id"]),
            UUID(matched["capture_id"]),
            matched["source_hash"],
            matched["amount_minor"],
            matched["currency"],
        )
        if expected != actual:
            raise ValueError("correction_application_scope_conflict")
        if self.original_assessment is not None:
            source = await repo.original_capture_event(scope, session=session)
            await self.original_assessment.handle(
                source, session=session, recorded_at=now
            )
            await repo.record_original_assessment(
                scope, matched, command_id, now, session=session
            )
        application_id, case_id = uuid4(), UUID(matched["case_id"])
        plans = [
            await self._plan(scope, item, session=session)
            for item in scope.bundle.components
        ]
        await repo.append_fact(
            "applications",
            dict(
                application_id=application_id,
                match_id=UUID(matched["match_id"]),
                intent_id=UUID(matched["intent_id"]),
                case_id=case_id,
                order_id=scope.order_id,
                payment_id=scope.payment_id,
                capture_id=scope.capture_id,
                source_hash=scope.source_hash,
                amount_minor=scope.bundle.total_minor,
                currency="RUB",
                recorded_at=now,
            ),
            session=session,
        )
        for item, original, prior, cancelled, delta, potential in plans:
            component_id = uuid4()
            await repo.append_fact(
                "components",
                dict(
                    component_application_id=component_id,
                    application_id=application_id,
                    allocation_key=item.allocation_key,
                    payment_id=scope.payment_id,
                    paid_item_id=item.paid_item_id,
                    component="selection",
                    currency="RUB",
                    gross_minor=item.gross_minor,
                    prior_refund_minor=prior,
                    new_refund_minor=prior + item.gross_minor,
                    refund_minor=item.gross_minor,
                ),
                session=session,
            )
            if original is None:
                await self._covered(
                    component_id, potential, scope, item, session
                )
                continue
            source_entry = await ledger.get_entry_ref(
                original.movement.operation_key, session=session
            )
            movement_id = None
            if delta:
                movement = JournalMovement(
                    obligation_id=original.obligation_id,
                    operation_key=f"refund:{application_id}:{original.obligation_id}",
                    event_id=str(application_id),
                    movement_type="reversal",
                    amount_minor=delta,
                    currency="RUB",
                    effective_at=now,
                    recorded_at=now,
                    actor_id=actor_id,
                    actor_kind="admin",
                    reason="Reviewed actual full selection refund",
                    bucket_from="pending",
                    bucket_to="cancelled",
                    source_entry_id=source_entry,
                    refund_id=application_id,
                    case_id=case_id,
                )
                await ledger.append(movement, session=session)
                await ledger.apply_projection(movement, session=session)
                movement_id = await ledger.get_entry_ref(
                    movement.operation_key, session=session
                )
            await repo.append_fact(
                "liabilities",
                dict(
                    assessment_id=uuid4(),
                    component_application_id=component_id,
                    status="pending_cancelled",
                    business_key=original.basis.business_key,
                    obligation_id=original.obligation_id,
                    snapshot_id=original.snapshot_id,
                    issuance_entry_id=source_entry,
                    potential_id=None,
                    frozen_rate_bps=original.basis.rate_bps,
                    override_id=original.basis.override_id,
                    target_minor=delta + cancelled,
                    already_cancelled_minor=cancelled,
                    delta_minor=delta,
                    movement_id=movement_id,
                ),
                session=session,
            )
            await FinancialReconciliationService(ledger).require_ready(
                original.basis.recipient_id, "RUB", session=session
            )
        return {"applied": True, "application_id": str(application_id)}

    async def _covered(self, component_id, potential, scope, item, session):
        await self.repository.append_fact(
            "liabilities",
            dict(
                assessment_id=uuid4(),
                component_application_id=component_id,
                status=potential[1],
                business_key=f"client-selection:{scope.payment_id}:{item.paid_item_id}",
                obligation_id=None,
                snapshot_id=None,
                issuance_entry_id=None,
                potential_id=potential[0],
                frozen_rate_bps=None,
                override_id=None,
                target_minor=0,
                already_cancelled_minor=0,
                delta_minor=0,
                movement_id=None,
            ),
            session=session,
        )

    async def _plan(self, scope, item, *, session):
        repo, ledger = self.repository, self.ledger.repository
        key = f"client-selection:{scope.payment_id}:{item.paid_item_id}"
        original = await ledger.get_issue(key, session=session)
        if original is None:
            potential = await repo.covered_potential(
                scope, item, session=session
            )
            if potential is None:
                raise RefundAssessmentUnavailable(
                    "correction_original_assessment_required"
                )
            return (item, None, 0, 0, 0, potential)
        basis = original.basis
        if (
            basis.kind,
            basis.payment_id,
            basis.paid_item_id,
            basis.order_id,
            basis.base_minor,
            basis.event_id,
            basis.referred_user_id,
        ) != (
            "client_referral",
            scope.payment_id,
            item.paid_item_id,
            scope.order_id,
            item.gross_minor,
            str(scope.capture_id),
            scope.client_id,
        ):
            raise ValueError("correction_original_basis_mismatch")
        prior = await repo.component_refund_total(
            item.allocation_key, session=session
        )
        cancelled = await repo.liability_refund_total(
            original.obligation_id, session=session
        )
        report = await FinancialReconciliationService(ledger).require_ready(
            basis.recipient_id, "RUB", session=session
        )
        balances = report.replay.by_obligation[original.obligation_id]
        if prior != 0 or any(
            balances[b]
            for b in (
                "hold",
                "available",
                "reserved",
                "paid",
                "blocked",
                "debt",
            )
        ):
            raise RefundAssessmentUnavailable(
                "correction_nonpending_review_required"
            )
        delta = pending_cancellation_delta(
            item.gross_minor,
            item.gross_minor,
            basis.rate_bps,
            "RUB",
            already_source_linked_cancelled=cancelled,
            pending_minor=balances["pending"],
        )
        return (item, original, prior, cancelled, delta, None)
