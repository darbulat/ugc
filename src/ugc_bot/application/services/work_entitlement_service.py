"""Produce assignment earnings from captured funding and current work facts."""

from dataclasses import asdict
from typing import Any
from uuid import UUID

from ugc_bot.application.entitlement_ports import EffectiveRateOverrides
from ugc_bot.application.financial_ports import (
    ActiveEconomicGround,
    Bucket,
    Clock,
    IssueBasis,
    IssuedObligation,
    JournalMovement,
)
from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
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
from ugc_bot.application.work_entitlement_ports import (
    WORK_EVENT_TYPES,
    WorkDisputeCase,
    WorkEntitlementRepository,
    WorkEntitlementSnapshot,
)
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.financial import rate_bps, utc
from ugc_bot.domain.identity_history import HistoricalDirectAttribution

KINDS = ("client_referral", "creator_referral", "management")
PRODUCER = "work_entitlement"


class WorkEntitlementService:
    def __init__(
        self,
        repository: WorkEntitlementRepository,
        ledger: FinancialLedgerService,
        history: CreatorIdentityHistoryService,
        overrides: EffectiveRateOverrides,
        clock: Clock,
        guard: WorkFinancialGuard | None = None,
        funding_guard: LiveCorrectionFundingGuard | None = None,
    ) -> None:
        self.repository, self.ledger, self.history = repository, ledger, history
        self.overrides, self.clock = overrides, clock
        self.guard = guard or WorkFinancialGuard(repository)
        self.funding_guard = funding_guard

    async def handle(self, event: OutboxEvent, *, session: object) -> None:
        if event.event_type not in WORK_EVENT_TYPES:
            raise ValueError("work_source_unsupported")
        if await self._replayed(event, session=session):
            return
        current, fresh, grounds = await self._locked_snapshot(
            event, session=session
        )
        if await self._replayed(event, session=session):
            return
        assessment = await self._assess(
            current, fresh, grounds, session=session
        )
        await self.repository.save_receipt(
            event,
            current,
            assessment,
            recorded_at=utc(self.clock.now()),
            session=session,
        )

    async def _replayed(self, event: OutboxEvent, *, session: object) -> bool:
        previous = await self.repository.get_receipt(
            event.event_id, session=session
        )
        if previous is None:
            return False
        if previous["source_hash"] != await self.repository.source_hash(
            event, session=session
        ):
            raise ValueError("idempotency_payload_conflict")
        return True

    async def _locked_snapshot(
        self, event: OutboxEvent, *, session: object
    ) -> tuple[
        WorkEntitlementSnapshot,
        HistoricalDirectAttribution,
        tuple[ActiveEconomicGround, ...],
    ]:
        repo, ledger = self.repository, self.ledger.repository
        before = await repo.load(event, session=session)
        attribution = await self.history.resolve_direct_binding(
            before.scope.creator_id, before.capture.captured_at, session=session
        )
        grounds = await self._grounds(
            before.scope.paid_item_id, session=session
        )
        users = {before.scope.client_id, before.scope.creator_id}
        wallets = {g.recipient_id for g in grounds}
        for user in (
            before.scope.manager_id,
            attribution.referrer_user_id,
            before.capture.captured_referrer_id,
        ):
            if user is not None:
                users.add(user)
        wallets.update(
            u
            for u in (
                before.scope.manager_id,
                attribution.referrer_user_id,
                before.capture.captured_referrer_id,
            )
            if u is not None
        )
        users.update(wallets)
        await ledger.lock_recipients(
            tuple(sorted(users, key=str)), session=session
        )
        await ledger.lock_wallets(
            tuple((u, "RUB") for u in sorted(wallets, key=str)), session=session
        )
        await repo.lock_funding(before, session=session)
        await self.history.acquire_snapshot_barrier(session=session)
        await ledger.lock_item(before.scope.paid_item_id, session=session)
        current = await repo.load(event, session=session)
        self._require_scope(before, current, users)
        fresh = await self.history.resolve_direct_binding(
            current.scope.creator_id,
            current.capture.captured_at,
            session=session,
        )
        if (
            fresh.referrer_user_id is not None
            and fresh.referrer_user_id not in wallets
        ):
            raise ValueError("financial_scope_changed_retry_required")
        current_grounds = await self._grounds(
            current.scope.paid_item_id, session=session
        )
        if any(g.recipient_id not in wallets for g in current_grounds):
            raise ValueError("financial_scope_changed_retry_required")
        return current, fresh, current_grounds

    async def _assess(
        self,
        current: WorkEntitlementSnapshot,
        fresh: HistoricalDirectAttribution,
        current_grounds: tuple[ActiveEconomicGround, ...],
        *,
        session: object,
    ) -> dict[str, Any]:
        assessment: dict[str, Any] = {
            "state": current.record.collaboration.state.value,
            "version": current.record.version,
            "attribution": asdict(fresh),
            "basis_keys": [],
            "manager": "not_successful",
        }
        now = utc(self.clock.now())
        case = await self.guard.case_for_item(
            current.scope.paid_item_id, session=session
        )
        if (
            current.record.updated_at > now
            or current.capture.captured_at > now
            or (case is not None and case.occurred_at > now)
        ):
            raise ValueError("work_fact_in_future")
        issued: list[IssuedObligation] = []
        if current.scope.valid_to is not None:
            assessment["result"] = "historical_assignment_closed"
        elif current.record.collaboration.state in (
            "unconfirmed_expired",
            "rejected",
        ):
            if case is None:
                await self._expire(current, current_grounds, session=session)
            assessment["result"] = current.record.collaboration.state.value
        else:
            issued = await self._issue(
                current, fresh, assessment, session=session
            )
        # An ended assignment can retain an unresolved dispute. Its live case
        # still freezes every related item ground, including later assignments.
        if case is not None:
            assessment["case_id"] = str(case.case_id)
            await self._block(current, case, assessment, session=session)
        elif (
            current.scope.valid_to is None
            and current.record.collaboration.state
            in ("success_final", "available")
        ):
            for obligation in issued:
                await self._settle(current, obligation, session=session)
        if case is None and current.resolution_case_id is not None:
            await self._resume_client_grounds(
                current, current_grounds, session=session
            )
        return assessment

    async def _resume_client_grounds(self, current, grounds, *, session):
        for ground in grounds:
            if ground.kind != "client_referral":
                continue
            original = await self.ledger.repository.get_issue(
                ground.business_key, session=session
            )
            if original is None:
                raise ValueError("work_ground_source_missing")
            await self._resume(current, original, session=session)

    async def _grounds(
        self, item_id: UUID, *, session: object
    ) -> tuple[ActiveEconomicGround, ...]:
        result: list[ActiveEconomicGround] = []
        for kind in KINDS:
            result.extend(
                await self.ledger.repository.list_item_grounds(
                    item_id, kind, session=session
                )
            )
        return tuple(result)

    @staticmethod
    def _require_scope(
        before: WorkEntitlementSnapshot,
        current: WorkEntitlementSnapshot,
        users: set[UUID],
    ) -> None:
        s, record, capture = current.scope, current.record, current.capture
        work = record.collaboration
        actors = {s.client_id, s.creator_id}
        if s.manager_id is not None:
            actors.add(s.manager_id)
        if (
            not actors <= users
            or s.assignment_id != before.scope.assignment_id
            or s.paid_item_id != before.scope.paid_item_id
            or current.capture != before.capture
        ):
            raise ValueError("financial_scope_changed_retry_required")
        if (
            current.source_hash != before.source_hash
            or (
                work.assignment_id,
                work.client_id,
                work.creator_id,
                work.manager_id,
                record.paid_item_id,
                record.order_id,
                record.policy_version,
            )
            != (
                s.assignment_id,
                s.client_id,
                s.creator_id,
                s.manager_id,
                s.paid_item_id,
                s.order_id,
                s.policy_version,
            )
            or capture.order_id != s.order_id
            or capture.client_id != s.client_id
            or capture.policy.version != s.policy_version
            or capture.captured_at != s.captured_at
            or not s.selection_funded
            or not record.terms_reference.strip()
            or (
                work.state in ("success_final", "available")
                and work.success_final_at is None
            )
        ):
            raise ValueError("work_scope_mismatch")
        item = next(
            (i for i in capture.items if i.paid_item_id == s.paid_item_id), None
        )
        if (
            item is None
            or item.selection_minor != 50000
            or item.accompaniment_minor not in (0, 120000)
        ):
            raise ValueError("work_funding_mismatch")

    async def _issue(
        self,
        snapshot: WorkEntitlementSnapshot,
        attribution: HistoricalDirectAttribution,
        assessment: dict[str, Any],
        *,
        session: object,
    ) -> list[IssuedObligation]:
        scope, capture = snapshot.scope, snapshot.capture
        if self.funding_guard is not None:
            await self.funding_guard.require_forward_clear(
                scope.paid_item_id, session=session, components=("selection",)
            )
        recipient = attribution.referrer_user_id
        grade, override, rate = None, None, None
        if recipient is not None:
            grade = await self.history.count_verified_direct_creators(
                recipient, capture.captured_at, session=session
            )
            if (
                grade.partner_user_id != recipient
                or grade.as_of != capture.captured_at
            ):
                raise ValueError("work_grade_scope_mismatch")
            if attribution.registered_at is None:
                raise ValueError("historical_registration_required")
            override = await self.overrides.select_effective_override(
                recipient,
                "creator",
                capture.policy.version,
                capture.captured_at,
                session=session,
            )
            rate = (
                override.rate_bps
                if override
                else rate_bps(
                    attribution.registered_at,
                    capture.captured_at,
                    side="creator",
                    verified_count=grade.verified_count,
                )
            )
            assessment["grade"] = asdict(grade)
        basis = IssueBasis(
            business_key=f"creator-selection:{capture.payment_id}:{scope.paid_item_id}:{scope.assignment_id}",
            kind="creator_referral",
            recipient_id=recipient,
            paid_item_id=scope.paid_item_id,
            order_id=scope.order_id,
            assignment_id=scope.assignment_id,
            referred_user_id=scope.creator_id,
            payment_id=capture.payment_id,
            currency="RUB",
            base_minor=50000,
            rate_bps=rate,
            policy_version=capture.policy.version,
            snapshot_at=capture.captured_at,
            registered_at=attribution.registered_at,
            verified_count=grade.verified_count if grade else None,
            event_id=str(capture.event_id),
            reason="captured_assignment_selection",
            actor_id=None,
            actor_kind="system",
            system_actor=PRODUCER,
            rate_source="override" if override else "standard",
            override_id=override.override_id if override else None,
        )
        creator = await self.ledger.issue(
            basis, recorded_at=utc(self.clock.now()), session=session
        )
        assessment["basis_keys"].append(basis.business_key)
        results = [creator] if isinstance(creator, IssuedObligation) else []
        item = next(
            i for i in capture.items if i.paid_item_id == scope.paid_item_id
        )
        if snapshot.record.collaboration.state not in (
            "success_final",
            "available",
        ):
            return results
        reason = await self._management_deferral(
            snapshot, item, assessment, session=session
        )
        if reason is not None:
            assessment["manager"] = reason
        else:
            management = IssueBasis(
                business_key=f"management:{capture.payment_id}:{scope.paid_item_id}:{scope.assignment_id}",
                kind="management",
                recipient_id=scope.manager_id,
                paid_item_id=scope.paid_item_id,
                order_id=scope.order_id,
                assignment_id=scope.assignment_id,
                referred_user_id=scope.creator_id,
                payment_id=capture.payment_id,
                currency="RUB",
                base_minor=60000,
                rate_bps=None,
                policy_version=capture.policy.version,
                snapshot_at=capture.captured_at,
                registered_at=None,
                verified_count=None,
                event_id=str(capture.event_id),
                reason="successful_funded_management",
                actor_id=None,
                actor_kind="system",
                system_actor=PRODUCER,
            )
            issued = await self.ledger.issue(
                management, recorded_at=utc(self.clock.now()), session=session
            )
            if not isinstance(issued, IssuedObligation):
                raise ValueError("management_issuance_unresolved")
            results.append(issued)
            assessment["basis_keys"].append(management.business_key)
            assessment["manager"] = "successful_funded_management"
            assessment["manager_id"] = str(scope.manager_id)
            assessment["management_basis_key"] = management.business_key
            assessment["management_schedule_id"] = str(snapshot.schedule_id)
            success_at = snapshot.record.collaboration.success_final_at
            assert success_at is not None
            assessment["manager_success_at"] = success_at.isoformat()
        return results

    async def _management_deferral(
        self, snapshot, item, assessment, *, session
    ):
        if item.accompaniment_minor != 120000:
            return "accompaniment_not_purchased"
        if snapshot.scope.manager_id is None:
            return "actual_manager_not_assigned"
        reason = None
        if not snapshot.manager_linked:
            reason = "manager_membership_at_success_unproven"
        else:
            reason = await self._management_refund_deferral(
                snapshot, session=session
            )
        if reason is not None:
            assessment.setdefault("potential_reasons", []).append(reason)
        return reason

    async def _management_refund_deferral(self, snapshot, *, session):
        if self.funding_guard is None:
            return None
        funding = await self.funding_guard.load_item(
            snapshot.scope.paid_item_id, session=session
        )
        if not any(
            line.component == "accompaniment" and line.cumulative_refund_minor
            for line in funding
        ):
            return None
        key = (
            f"management:{snapshot.capture.payment_id}:"
            f"{snapshot.scope.paid_item_id}:{snapshot.scope.assignment_id}"
        )
        if (
            await self.ledger.repository.get_issue(key, session=session)
            is not None
        ):
            return None
        disposition = await self.funding_guard.management_refund_disposition(
            snapshot.scope.paid_item_id, session=session
        )
        if disposition == "continue":
            return None
        return (
            "accompaniment_management_cancelled"
            if disposition == "cancel"
            else "accompaniment_management_review_required"
        )

    async def _balances(
        self, obligation: IssuedObligation, *, session: object
    ) -> dict[str, int]:
        basis = obligation.basis
        assert basis.recipient_id is not None
        report = await FinancialReconciliationService(
            self.ledger.repository
        ).require_ready(basis.recipient_id, basis.currency, session=session)
        return report.replay.by_obligation[obligation.obligation_id]

    def _movement(
        self,
        snapshot: WorkEntitlementSnapshot,
        obligation: IssuedObligation,
        amount: int,
        source: Bucket,
        target: Bucket,
        key: str,
        *,
        case: UUID | None = None,
    ) -> JournalMovement:
        now = utc(self.clock.now())
        return JournalMovement(
            obligation_id=obligation.obligation_id,
            operation_key=key,
            event_id=str(
                snapshot.current_event_id or snapshot.capture.event_id
            ),
            movement_type="transfer",
            amount_minor=amount,
            currency="RUB",
            effective_at=now,
            recorded_at=now,
            actor_kind="system",
            actor_id=None,
            system_actor=PRODUCER,
            reason="trusted_work_" + target,
            bucket_from=source,
            bucket_to=target,
            case_id=case,
        )

    async def _settle(
        self,
        snapshot: WorkEntitlementSnapshot,
        obligation: IssuedObligation,
        *,
        session: object,
    ) -> None:
        if self.funding_guard is not None:
            await self.funding_guard.require_forward_clear(
                snapshot.scope.paid_item_id,
                session=session,
                components=("selection",),
            )
        if snapshot.schedule_id is None:
            raise ValueError("work_maturity_schedule_missing")
        basis = obligation.basis
        fact = await self.ledger.record_maturity(
            basis.business_key,
            snapshot.schedule_id,
            producer=PRODUCER,
            recorded_at=utc(self.clock.now()),
            session=session,
        )
        await self._resume(snapshot, obligation, session=session)
        transitions: tuple[tuple[Bucket, Bucket], ...] = (
            ("pending", "hold"),
            ("hold", "available"),
        )
        for source, target in transitions:
            balances = await self._balances(obligation, session=session)
            if (
                target == "available"
                and utc(self.clock.now()) < fact.release_at
            ):
                continue
            if balances[source]:
                movement = self._movement(
                    snapshot,
                    obligation,
                    balances[source],
                    source,
                    target,
                    f"work-{target}:{obligation.obligation_id}:{snapshot.schedule_id}",
                )
                await self.ledger.transfer(
                    basis.business_key,
                    movement,
                    now=utc(self.clock.now()),
                    session=session,
                )

    async def _resume(self, snapshot, obligation, *, session):
        balances = await self._balances(obligation, session=session)
        if not balances["blocked"]:
            return
        if snapshot.resolution_case_id is None:
            raise ValueError("work_resolution_evidence_required")
        movement = self._movement(
            snapshot,
            obligation,
            balances["blocked"],
            "blocked",
            "hold",
            f"work-resume:{snapshot.resolution_case_id}:{obligation.obligation_id}",
            case=snapshot.resolution_case_id,
        )
        await self.ledger.transfer(
            obligation.basis.business_key,
            movement,
            now=utc(self.clock.now()),
            session=session,
        )

    async def _block(
        self,
        snapshot: WorkEntitlementSnapshot,
        case: WorkDisputeCase,
        assessment: dict[str, Any],
        *,
        session: object,
    ) -> None:
        for ground in await self._grounds(
            snapshot.scope.paid_item_id, session=session
        ):
            obligation = await self.ledger.repository.get_issue(
                ground.business_key, session=session
            )
            if obligation is None:
                raise ValueError("work_ground_source_missing")
            balances = await self._balances(obligation, session=session)
            if balances["reserved"] or balances["paid"]:
                assessment.setdefault("manual_review_required", []).append(
                    str(obligation.obligation_id)
                )
            sources: tuple[Bucket, ...] = ("pending", "hold", "available")
            for source in sources:
                if balances[source]:
                    movement = self._movement(
                        snapshot,
                        obligation,
                        balances[source],
                        source,
                        "blocked",
                        f"work-block:{case.case_id}:{obligation.obligation_id}:{source}",
                        case=case.case_id,
                    )
                    await self.ledger.transfer(
                        ground.business_key,
                        movement,
                        now=utc(self.clock.now()),
                        session=session,
                    )

    async def _expire(
        self,
        snapshot: WorkEntitlementSnapshot,
        grounds: tuple[ActiveEconomicGround, ...],
        *,
        session: object,
    ) -> None:
        repo = self.ledger.repository
        for ground in grounds:
            if ground.kind == "client_referral":
                continue
            obligation = await repo.get_issue(
                ground.business_key, session=session
            )
            if obligation is None:
                raise ValueError("work_ground_source_missing")
            if obligation.basis.assignment_id != snapshot.scope.assignment_id:
                continue
            balances = await self._balances(obligation, session=session)
            sources: tuple[Bucket, ...] = (
                "pending",
                "hold",
                "available",
                "blocked",
            )
            for source in sources:
                if not balances[source]:
                    continue
                entry = await repo.get_entry_ref(
                    obligation.movement.operation_key, session=session
                )
                movement = JournalMovement(
                    obligation_id=obligation.obligation_id,
                    operation_key=f"work-expire:{obligation.obligation_id}:{source}",
                    event_id=str(
                        snapshot.current_event_id or snapshot.capture.event_id
                    ),
                    movement_type="reversal",
                    amount_minor=balances[source],
                    currency="RUB",
                    effective_at=(
                        snapshot.record.updated_at
                        if snapshot.record.collaboration.state == "rejected"
                        else snapshot.record.collaboration.first_claim_deadline
                    ),
                    recorded_at=utc(self.clock.now()),
                    actor_kind="system",
                    actor_id=None,
                    system_actor=PRODUCER,
                    reason="unconfirmed_work_expired",
                    bucket_from=source,
                    bucket_to="cancelled",
                    source_entry_id=entry,
                    case_id=snapshot.resolution_case_id,
                )
                await repo.append(movement, session=session)
                await repo.apply_projection(movement, session=session)
