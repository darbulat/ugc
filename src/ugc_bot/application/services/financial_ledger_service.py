"""Caller-transaction ledger commands, without I/O or inferred authorization."""

from datetime import datetime
from uuid import uuid4

from ugc_bot.application.financial_ports import (
    IssueBasis,
    IssuedObligation,
    JournalMovement,
    LedgerRepository,
    PotentialBasis,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
    replay_journal,
)
from ugc_bot.domain.financial import commission_minor, rate_bps, utc


class PayloadConflict(ValueError):
    """Caller must audit this incident outside a rolled-back transaction."""

    audit_required = True

    def __init__(self, key: str) -> None:
        self.operation_key = key
        super().__init__("idempotency_payload_conflict")


class FinancialLedgerService:
    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    async def issue(
        self, basis: IssueBasis, *, recorded_at: datetime, session: object
    ) -> IssuedObligation | PotentialBasis:
        recorded_at = utc(recorded_at)
        if (
            basis.recipient_id is None
            or basis.policy_version is None
            or basis.rate_bps is None
        ):
            reason = (
                "recipient_unresolved_or_absent"
                if basis.recipient_id is None
                else "snapshot_policy_unresolved"
            )
            try:
                return await self.repository.save_potential(
                    basis, reason, recorded_at=recorded_at, session=session
                )
            except ValueError as error:
                if str(error) == "idempotency_payload_conflict":
                    raise PayloadConflict(
                        "potential:" + basis.business_key
                    ) from error
                raise
        repo = self.repository
        await repo.lock_wallets(
            ((basis.recipient_id, basis.currency),), session=session
        )
        await repo.lock_item(basis.paid_item_id, session=session)
        existing = await repo.get_issue(basis.business_key, session=session)
        if existing is not None:
            if existing.basis != basis:
                raise PayloadConflict(basis.business_key)
            return existing
        expected = rate_bps(
            basis.registered_at,
            basis.snapshot_at,
            side="client" if basis.kind == "client_referral" else "creator",
            verified_count=basis.verified_count,
        )
        if basis.rate_bps != expected:
            raise ValueError("unapproved_referral_rate")
        amount = commission_minor(
            basis.base_minor, basis.rate_bps, basis.currency
        )
        if amount == 0:
            raise ValueError("zero_monetary_obligation_unsupported")
        obligation = uuid4()
        movement = JournalMovement(
            obligation_id=obligation,
            operation_key="issue:" + basis.business_key,
            event_id=basis.event_id,
            movement_type="issuance",
            amount_minor=amount,
            currency=basis.currency,
            effective_at=basis.snapshot_at,
            recorded_at=recorded_at,
            actor_id=basis.actor_id,
            reason=basis.reason,
            bucket_to="pending",
        )
        result = await repo.save_issue(
            IssuedObligation(obligation, uuid4(), basis, movement),
            session=session,
        )
        await repo.append(result.movement, session=session)
        await repo.apply_projection(result.movement, session=session)
        return result

    async def transfer(
        self,
        business_key: str,
        movement: JournalMovement,
        *,
        now: datetime,
        session: object,
    ) -> JournalMovement:
        """Non-bank transfers only; caller authenticates case/confirmation.

        Schedule comes from the persisted issue, never current configuration.
        """
        from dataclasses import replace

        now = utc(now)
        repo = self.repository
        original = await repo.get_issue(business_key, session=session)
        if original is None or original.basis.recipient_id is None:
            raise ValueError("obligation_not_found")
        basis = original.basis
        assert basis.recipient_id is not None
        await repo.lock_wallets(
            ((basis.recipient_id, basis.currency),), session=session
        )
        await repo.lock_item(basis.paid_item_id, session=session)
        if (
            movement.obligation_id != original.obligation_id
            or movement.currency != basis.currency
        ):
            raise ValueError("movement_scope_mismatch")
        journal = await repo.list_for_recipient(
            basis.recipient_id, basis.currency, session=session
        )
        for previous in journal:
            if previous.operation_key == movement.operation_key:
                if (
                    replace(previous, recorded_at=movement.recorded_at)
                    != movement
                ):
                    raise PayloadConflict(movement.operation_key)
                return previous
        # Saved retries above remain read-only even after later corruption.
        # New writes require independent wallet-wide truth under the same
        # writer barrier and caller transaction; never commit or repair here.
        await FinancialReconciliationService(repo).require_ready(
            basis.recipient_id, basis.currency, session=session
        )
        self._validate_transfer(original, movement, journal, now)
        result = await repo.append(movement, session=session)
        await repo.apply_projection(result, session=session)
        return result

    @staticmethod
    def _validate_transfer(
        original: IssuedObligation,
        movement: JournalMovement,
        journal: tuple[JournalMovement, ...],
        now: datetime,
    ) -> None:
        basis = original.basis
        replay = replay_journal(journal, currency=basis.currency)
        if not replay.balanced:
            raise ValueError("reconciliation_mismatch_audit_required")
        balances = replay.by_obligation[original.obligation_id]
        allowed = {
            ("pending", "hold"),
            ("hold", "available"),
            ("pending", "blocked"),
            ("hold", "blocked"),
            ("available", "blocked"),
            ("blocked", "hold"),
        }
        if (
            movement.movement_type != "transfer"
            or (movement.bucket_from, movement.bucket_to) not in allowed
        ):
            raise ValueError("unsupported_bucket_transition")
        if (
            "blocked" in (movement.bucket_from, movement.bucket_to)
            and movement.case_id is None
        ):
            raise ValueError("block_case_required")
        if movement.bucket_to == "available":
            if balances["blocked"]:
                raise ValueError("obligation_blocked")
            if basis.available_at is None or now < basis.available_at:
                raise ValueError("hold_not_mature")
        assert movement.bucket_from is not None
        if balances[movement.bucket_from] < movement.amount_minor:
            raise ValueError("insufficient_bucket_balance")
