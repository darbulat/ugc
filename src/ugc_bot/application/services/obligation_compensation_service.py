"""Cancel a trusted cumulative liability; paid history remains immutable.

The caller proves the refund authority and locks its complete recipient/item
scope before invoking this helper in the same transaction. This class cannot
establish a refund or fabricate an entitlement from public request fields.
"""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.financial_ports import Bucket, JournalMovement
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.financial import utc

LIQUID: tuple[Bucket, ...] = ("pending", "hold", "available", "blocked")


def cancellation_delta(owned, prior_reported, target_minor, issued_minor):
    prior = sum(
        entry.amount_minor
        for entry in owned
        if entry.movement_type in ("reversal", "debt")
    )
    if type(prior_reported) is not int or prior_reported != prior:
        raise ValueError("correction_prior_cancellation_conflict")
    if (
        type(target_minor) is not int
        or not prior <= target_minor <= issued_minor
    ):
        raise ValueError("correction_cumulative_target_invalid")
    return target_minor - prior


def cancellation_plan(buckets, owned, delta):
    debt_issued = sum(
        entry.amount_minor for entry in owned if entry.movement_type == "debt"
    )
    paid_capacity = max(0, buckets["paid"] - debt_issued)
    if delta > sum(buckets[name] for name in LIQUID) + paid_capacity:
        if buckets["reserved"]:
            raise ValueError("correction_reserved_review_required")
        raise ValueError("correction_liability_capacity_conflict")
    plan: list[tuple[Bucket | None, int]] = []
    for bucket in LIQUID:
        amount = min(delta, buckets[bucket])
        if amount:
            plan.append((bucket, amount))
            delta -= amount
    if delta:
        plan.append((None, delta))
    return plan


@dataclass
class ObligationCompensationService:
    ledger: FinancialLedgerService

    async def cancel(
        self,
        original,
        *,
        target_minor,
        already_cancelled_minor,
        case_id,
        refund_id,
        actor_id,
        now,
        session,
    ) -> tuple[UUID, ...]:
        now = utc(now)
        basis = original.basis
        if any(
            not isinstance(value, UUID) or not value.int
            for value in (case_id, refund_id, actor_id, basis.recipient_id)
        ):
            raise ValueError("correction_authority_reference_required")
        repo = self.ledger.repository
        await repo.lock_wallets(
            ((basis.recipient_id, basis.currency),), session=session
        )
        await repo.lock_item(basis.paid_item_id, session=session)
        stored = await repo.get_issue(basis.business_key, session=session)
        if stored != original:
            raise ValueError("correction_original_basis_mismatch")
        if now < original.movement.recorded_at:
            raise ValueError("correction_before_original_issue")
        report = await FinancialReconciliationService(repo).require_ready(
            basis.recipient_id, basis.currency, session=session
        )
        journal = await repo.list_for_recipient(
            basis.recipient_id, basis.currency, session=session
        )
        owned = [
            entry
            for entry in journal
            if entry.obligation_id == original.obligation_id
        ]
        delta = cancellation_delta(
            owned,
            already_cancelled_minor,
            target_minor,
            original.movement.amount_minor,
        )
        if not delta:
            return ()
        buckets = report.replay.by_obligation[original.obligation_id]
        source = await repo.get_entry_ref(
            original.movement.operation_key, session=session
        )
        if source is None:
            raise ValueError("correction_original_assessment_required")
        plan = cancellation_plan(buckets, owned, delta)
        result = []
        for bucket, amount in plan:
            movement = JournalMovement(
                obligation_id=original.obligation_id,
                operation_key=(
                    f"compensation:{refund_id}:{original.obligation_id}:"
                    f"{bucket or 'debt'}"
                ),
                event_id=str(refund_id),
                movement_type="reversal" if bucket else "debt",
                amount_minor=amount,
                currency=basis.currency,
                effective_at=now,
                recorded_at=now,
                actor_id=actor_id,
                actor_kind="admin",
                reason="Reviewed cumulative liability correction",
                bucket_from=bucket,
                bucket_to="cancelled" if bucket else None,
                source_entry_id=source,
                refund_id=refund_id,
                case_id=case_id,
            )
            written = await repo.append(movement, session=session)
            await repo.apply_projection(written, session=session)
            reference = await repo.get_entry_ref(
                written.operation_key, session=session
            )
            assert reference is not None
            result.append(reference)
        await FinancialReconciliationService(repo).require_ready(
            basis.recipient_id, basis.currency, session=session
        )
        return tuple(result)
