"""Assess confirmed selection funding against historical attribution."""

from dataclasses import asdict

from ugc_bot.application.entitlement_ports import (
    ClientCapture,
    ClientEntitlementRepository,
    EffectiveRateOverrides,
)
from ugc_bot.application.financial_ports import (
    Bucket,
    Clock,
    IssueBasis,
    IssuedObligation,
    JournalMovement,
)
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.application.services.work_financial_guard import WorkFinancialGuard
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.financial import rate_bps, utc
from ugc_bot.domain.identity_history import HistoricalDirectAttribution


class ClientEntitlementService:
    def __init__(
        self,
        repository: ClientEntitlementRepository,
        ledger: FinancialLedgerService,
        history: CreatorIdentityHistoryService,
        overrides: EffectiveRateOverrides,
        clock: Clock,
        work_guard: WorkFinancialGuard | None = None,
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.history = history
        self.overrides = overrides
        self.clock = clock
        self.work_guard = work_guard

    async def handle(self, event: OutboxEvent, *, session: object) -> None:
        repo = self.repository
        completed = await repo.get_receipt(event.event_id, session=session)
        if completed is not None:
            digest = await repo.source_hash(event, session=session)
            if completed["source_hash"] != digest:
                raise ValueError("idempotency_payload_conflict")
            return
        capture = await repo.load_capture(event, session=session)
        before = await self.history.resolve_direct_binding(
            capture.client_id, capture.captured_at, session=session
        )
        recipients = {capture.client_id}
        if before.referrer_user_id is not None:
            recipients.add(before.referrer_user_id)
        for item in capture.items:
            grounds = await self.ledger.repository.list_item_grounds(
                item.paid_item_id, "client_referral", session=session
            )
            recipients.update(ground.recipient_id for ground in grounds)
        # Every prospective User/wallet comes before order, history and items.
        await self.ledger.repository.lock_recipients(
            tuple(sorted(recipients, key=str)), session=session
        )
        await self.ledger.repository.lock_wallets(
            tuple(
                (user, "RUB")
                for user in sorted(recipients - {capture.client_id}, key=str)
            ),
            session=session,
        )
        await repo.lock_funding(capture, session=session)
        await self.history.acquire_snapshot_barrier(session=session)
        for item in sorted(
            capture.items, key=lambda item: str(item.paid_item_id)
        ):
            await self.ledger.repository.lock_item(
                item.paid_item_id, session=session
            )
        current = await repo.load_capture(event, session=session)
        if current != capture:
            raise ValueError("financial_scope_changed_retry_required")
        attribution = await self.history.resolve_direct_binding(
            capture.client_id, capture.captured_at, session=session
        )
        if (
            attribution.referrer_user_id is not None
            and attribution.referrer_user_id not in recipients
        ):
            raise ValueError("financial_scope_changed_retry_required")
        self._require_attribution(capture, attribution)
        previous = await repo.get_receipt(capture.event_id, session=session)
        if previous is not None:
            if previous["source_hash"] != capture.source_hash:
                raise ValueError("idempotency_payload_conflict")
            return
        results = await self._issue(capture, attribution, session=session)
        assessment = {
            "kind": "client_selection",
            "basis_keys": results,
            "attribution": asdict(attribution),
            "creator_assessment": "awaiting_assignment",
        }
        await repo.save_receipt(
            capture,
            assessment,
            recorded_at=utc(self.clock.now()),
            session=session,
        )

    @staticmethod
    def _require_attribution(
        capture: ClientCapture,
        attribution: HistoricalDirectAttribution,
    ) -> None:
        if capture.captured_referrer_id != attribution.referrer_user_id or (
            attribution.referrer_user_id is not None
            and capture.registered_at != attribution.registered_at
        ):
            raise ValueError("capture_attribution_mismatch")

    async def _issue(
        self,
        capture: ClientCapture,
        attribution: HistoricalDirectAttribution,
        *,
        session: object,
    ) -> list[str]:
        recipient = attribution.referrer_user_id
        assert capture.policy.version
        if recipient is not None and capture.registered_at is None:
            raise ValueError("historical_registration_required")
        override = (
            await self.overrides.select_effective_override(
                recipient,
                "client",
                capture.policy.version,
                capture.captured_at,
                session=session,
            )
            if recipient is not None
            else None
        )
        rate = None
        if recipient is not None:
            assert capture.registered_at is not None
            rate = (
                override.rate_bps
                if override
                else rate_bps(
                    capture.registered_at,
                    capture.captured_at,
                    side="client",
                    verified_count=None,
                )
            )
        results = []
        for item in capture.items:
            key = f"client-selection:{capture.payment_id}:{item.paid_item_id}"
            grounds = await self.ledger.repository.list_item_grounds(
                item.paid_item_id, "client_referral", session=session
            )
            if any(ground.business_key != key for ground in grounds):
                raise ValueError("client_economic_ground_exists")
            issued = await self.ledger.issue(
                IssueBasis(
                    business_key=key,
                    kind="client_referral",
                    recipient_id=recipient,
                    paid_item_id=item.paid_item_id,
                    order_id=capture.order_id,
                    assignment_id=None,
                    referred_user_id=capture.client_id,
                    payment_id=capture.payment_id,
                    currency="RUB",
                    base_minor=item.selection_minor,
                    rate_bps=rate,
                    policy_version=capture.policy.version,
                    snapshot_at=capture.captured_at,
                    registered_at=capture.registered_at,
                    verified_count=None,
                    event_id=str(capture.event_id),
                    reason="confirmed_selection_capture",
                    actor_id=capture.client_id,
                    rate_source="override" if override else "standard",
                    override_id=override.override_id if override else None,
                ),
                recorded_at=utc(self.clock.now()),
                session=session,
            )
            if isinstance(issued, IssuedObligation):
                await self._block_disputed(issued, session=session)
            results.append(key)
        return results

    async def _block_disputed(
        self,
        issued: IssuedObligation,
        *,
        session: object,
    ) -> None:
        if self.work_guard is None:
            return
        basis = issued.basis
        case = await self.work_guard.case_for_item(
            basis.paid_item_id, session=session
        )
        if case is None:
            return
        now = utc(self.clock.now())
        if utc(case.occurred_at) > now:
            raise ValueError("work_case_time_conflict")
        assert basis.recipient_id is not None
        report = await FinancialReconciliationService(
            self.ledger.repository
        ).require_ready(basis.recipient_id, basis.currency, session=session)
        balances = report.replay.by_obligation[issued.obligation_id]
        if balances["reserved"] or balances["paid"]:
            raise ValueError("work_disputed_payout_review_required")
        sources: tuple[Bucket, ...] = ("pending", "hold", "available")
        for source in sources:
            if not balances[source]:
                continue
            movement = JournalMovement(
                obligation_id=issued.obligation_id,
                operation_key=f"client-block:{case.case_id}:{issued.obligation_id}:{source}",
                event_id=str(case.source_event_id),
                movement_type="transfer",
                amount_minor=balances[source],
                currency=basis.currency,
                effective_at=case.occurred_at,
                recorded_at=now,
                actor_kind="system",
                actor_id=None,
                system_actor="client_entitlement",
                reason="work_disputed",
                bucket_from=source,
                bucket_to="blocked",
                case_id=case.case_id,
            )
            await self.ledger.transfer(
                basis.business_key, movement, now=now, session=session
            )
