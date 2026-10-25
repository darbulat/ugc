"""Caller-transaction ledger commands, without I/O or inferred authorization."""

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from ugc_bot.application.financial_ports import (
    ActiveEconomicGround,
    IssueBasis,
    IssuedObligation,
    JournalMovement,
    LedgerRepository,
    ObligationMaturity,
    PotentialBasis,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
    replay_journal,
)
from ugc_bot.domain.financial import (
    MANAGEMENT_REWARD_MINOR,
    commission_minor,
    rate_bps,
    utc,
)


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
            or (
                basis.rate_bps is None
                and basis.kind not in ("management", "manual_adjustment")
            )
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
        previous_grounds = await self._lock_issue_scope(basis, session=session)
        existing = await repo.get_issue(basis.business_key, session=session)
        if existing is not None:
            if existing.basis != basis:
                raise PayloadConflict(basis.business_key)
            return existing
        for previous_ground in previous_grounds:
            await self._require_cancelled(previous_ground, session=session)
        amount = await self._assessed_amount(basis, session=session)
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
            actor_kind=basis.actor_kind,
            system_actor=basis.system_actor,
            reason=basis.reason,
            bucket_to="pending",
        )
        result = await repo.save_issue(
            IssuedObligation(obligation, uuid4(), basis, movement),
            session=session,
        )
        await repo.append(result.movement, session=session)
        await repo.apply_projection(result.movement, session=session)
        if basis.kind in ("creator_referral", "management"):
            await repo.set_active_ground(result, session=session)
        return result

    async def _lock_issue_scope(
        self, basis: IssueBasis, *, session: object
    ) -> tuple[ActiveEconomicGround, ...]:
        """Discover recipients, then take User→wallet→item writer barriers.

        The item serializes all assignment grounds. Discovery is repeated under
        that lock; a newly discovered wallet requires a whole-transaction retry,
        never acquiring an additional User or wallet after the item barrier.
        Immutable obligations/journal are authoritative; the active pointer is
        only a projection and cannot establish permission to issue.
        """
        repo = self.repository
        assert basis.recipient_id is not None
        previous = (
            await repo.list_item_grounds(
                basis.paid_item_id, basis.kind, session=session
            )
            if basis.kind in ("creator_referral", "management")
            else ()
        )
        keys = {(basis.recipient_id, basis.currency)}
        for ground in previous:
            keys.add((ground.recipient_id, ground.currency))
        await repo.lock_wallets(
            tuple(sorted(keys, key=lambda x: (str(x[0]), x[1]))),
            session=session,
        )
        await repo.lock_item(basis.paid_item_id, session=session)
        if basis.kind not in ("creator_referral", "management"):
            return ()
        current = await repo.list_item_grounds(
            basis.paid_item_id, basis.kind, session=session
        )
        if any(
            (ground.recipient_id, ground.currency) not in keys
            for ground in current
        ):
            raise ValueError("financial_scope_changed_retry_required")
        return current

    async def _require_cancelled(
        self, previous: ActiveEconomicGround, *, session: object
    ) -> None:
        report = await FinancialReconciliationService(
            self.repository
        ).require_ready(
            previous.recipient_id, previous.currency, session=session
        )
        buckets = report.replay.by_obligation.get(previous.obligation_id)
        if (
            buckets is None
            or not buckets["cancelled"]
            or any(
                value for key, value in buckets.items() if key != "cancelled"
            )
        ):
            raise ValueError("active_economic_ground_exists")

    async def _assessed_amount(
        self, basis: IssueBasis, *, session: object
    ) -> int:
        if basis.kind == "manual_adjustment":
            source = await self.repository.load_manual_grant(
                UUID(basis.event_id), session=session
            )
            if source is None:
                raise ValueError("manual_grant_approval_required")
            source.require_for(basis)
            return source.amount_minor
        if basis.kind == "management":
            if basis.base_minor != MANAGEMENT_REWARD_MINOR:
                raise ValueError("unapproved_management_reward")
            return basis.base_minor
        assert basis.registered_at is not None and basis.rate_bps is not None
        if basis.rate_source == "override":
            assert basis.override_id is not None
            override = await self.repository.get_rate_override(
                basis.override_id, as_of=basis.snapshot_at, session=session
            )
            if override is None or not override.applies(basis):
                raise ValueError("approved_override_required")
            return commission_minor(
                basis.base_minor, override.rate_bps, basis.currency
            )
        expected = rate_bps(
            basis.registered_at,
            basis.snapshot_at,
            side="client" if basis.kind == "client_referral" else "creator",
            verified_count=basis.verified_count,
        )
        if basis.rate_bps != expected:
            raise ValueError("unapproved_referral_rate")
        return commission_minor(
            basis.base_minor, basis.rate_bps, basis.currency
        )

    async def record_maturity(
        self,
        business_key: str,
        source_id: UUID,
        *,
        producer: str,
        recorded_at: datetime,
        session: object,
    ) -> ObligationMaturity:
        """Bind an existing obligation to server-persisted work maturity.

        Dates come from the persisted source. Client selection maturity
        has a different source and is deliberately not implemented by this port.
        """
        recorded_at = utc(recorded_at)
        if (
            not isinstance(source_id, UUID)
            or source_id.int == 0
            or not isinstance(producer, str)
            or not producer.strip()
        ):
            raise ValueError("maturity_provenance_required")
        original = await self.repository.get_issue(
            business_key, session=session
        )
        if original is None:
            raise ValueError("obligation_not_found")
        basis = original.basis
        assert basis.recipient_id is not None
        await self.repository.lock_wallets(
            ((basis.recipient_id, basis.currency),), session=session
        )
        await self.repository.lock_item(basis.paid_item_id, session=session)
        existing = await self.repository.get_maturity(
            original.obligation_id, session=session
        )
        if existing is not None:
            if existing.source_id != source_id or existing.producer != producer:
                raise PayloadConflict("maturity:" + business_key)
            return existing
        source = await self.repository.load_maturity_source(
            source_id, session=session
        )
        if source is None:
            raise ValueError("maturity_source_not_eligible")
        source.require_for(basis)
        if recorded_at < source.success_final_at:
            raise ValueError("maturity_before_success")
        fact = ObligationMaturity(
            uuid5(NAMESPACE_URL, f"ugc:maturity:{original.obligation_id}"),
            original.obligation_id,
            source_id,
            source.assignment_id,
            source.paid_item_id,
            source.success_final_at,
            source.release_at,
            producer,
            recorded_at,
        )
        return await self.repository.save_maturity(fact, session=session)

    async def _release_time(
        self, original: IssuedObligation, *, session: object
    ) -> datetime | None:
        if original.basis.kind == "manual_adjustment":
            source = await self.repository.load_manual_grant(
                UUID(original.basis.event_id), session=session
            )
            if source is None:
                raise ValueError("manual_grant_approval_required")
            source.require_for(original.basis)
            return source.release_at
        if original.basis.kind == "client_referral":
            loader = getattr(self.repository, "load_selection_maturity", None)
            source = (
                await loader(original.obligation_id, session=session)
                if loader is not None
                else None
            )
            if source is not None:
                source.require_for(original.basis)
                return source.release_at
        fact = await self.repository.get_maturity(
            original.obligation_id, session=session
        )
        if fact is None:
            # Compatibility for existing internally assessed snapshots. New
            # work producers issue with available_at=None and bind the actual
            # immutable success schedule through record_maturity.
            return original.basis.available_at
        source = await self.repository.load_maturity_source(
            fact.source_id, session=session
        )
        if source is None:
            raise ValueError("maturity_source_not_eligible")
        source.require_for(original.basis)
        if (
            source.release_at != fact.release_at
            or source.success_final_at != fact.success_final_at
        ):
            raise ValueError("maturity_source_changed")
        return fact.release_at

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
        release_at = (
            await self._release_time(original, session=session)
            if movement.bucket_to == "available"
            else basis.available_at
        )
        self._validate_transfer(original, movement, journal, now, release_at)
        result = await repo.append(movement, session=session)
        await repo.apply_projection(result, session=session)
        return result

    @staticmethod
    def _validate_transfer(
        original: IssuedObligation,
        movement: JournalMovement,
        journal: tuple[JournalMovement, ...],
        now: datetime,
        release_at: datetime | None,
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
            if release_at is None or now < release_at:
                raise ValueError("hold_not_mature")
        assert movement.bucket_from is not None
        if balances[movement.bucket_from] < movement.amount_minor:
            raise ValueError("insufficient_bucket_balance")
