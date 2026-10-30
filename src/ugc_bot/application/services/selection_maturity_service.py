"""Close actual paid selection and release only delivered client obligations."""

from dataclasses import asdict
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.financial_ports import Clock, JournalMovement
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.selection_maturity_ports import (
    SelectionClosure,
    SelectionMaturityRepository,
    SelectionMaturitySource,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.financial import utc


class SelectionMaturityService:
    def __init__(
        self,
        repository: SelectionMaturityRepository,
        ledger: FinancialLedgerService,
        clock: Clock,
    ):
        self.repository, self.ledger, self.clock = repository, ledger, clock

    async def refresh(
        self,
        order_id: UUID,
        *,
        session: object,
        actor_id: UUID | None = None,
        reason: str = "",
        evidence: str = "",
        principal=None,
    ):
        repo, ledger = self.repository, self.ledger.repository
        before = await repo.load(order_id, session=session)
        grounds = await self._grounds(before, session=session)
        users = {before.client_id} | {g.recipient_id for g in grounds}
        if actor_id is not None:
            users.add(actor_id)
        await ledger.lock_recipients(
            tuple(sorted(users, key=str)), session=session
        )
        await ledger.lock_wallets(
            tuple(
                (user, "RUB")
                for user in sorted({g.recipient_id for g in grounds}, key=str)
            ),
            session=session,
        )
        await repo.lock_order(order_id, session=session)
        for item in sorted(before.positions, key=lambda p: str(p.paid_item_id)):
            await ledger.lock_item(item.paid_item_id, session=session)
        current = await repo.load(order_id, session=session)
        fresh_grounds = await self._grounds(current, session=session)
        now = utc(self.clock.now())
        self._require_stable(before, current, fresh_grounds, users, now)
        if actor_id is not None:
            await self._authorize(current, actor_id, principal, session=session)
        if current.policy.maturity_mode == "per_item_v1":
            return await self._schedule_individual(
                current, fresh_grounds, now, session=session
            )
        rules = current.policy.refund_rules
        if rules is None:
            raise ValueError("selection_refund_rules_required")
        closed = await self._close(
            current, actor_id, reason, evidence, now, session=session
        )
        if isinstance(closed, dict):
            return closed
        results = await self._schedule(
            current, closed, rules, fresh_grounds, now, session=session
        )
        return {
            "state": "closed",
            "closed_at": closed.closed_at.isoformat(),
            "items": results,
        }

    async def _schedule_individual(
        self, current, fresh_grounds, now, *, session
    ):
        if current.policy.selection_refund_window != timedelta(days=7):
            raise ValueError("selection_refund_window_required")
        results = []
        for item in current.positions:
            if item.delivered_at is None or item.refunded_at is not None:
                continue
            try:
                await self.repository.require_clear(
                    item.paid_item_id, session=session
                )
            except ValueError as error:
                if str(error) not in {
                    "work_disputed",
                    "correction_unresolved",
                    "correction_component_refunded",
                }:
                    raise
                continue
            deadline = item.delivered_at + timedelta(days=7)
            schedule = await self.repository.save_schedule(
                SelectionMaturitySource(
                    uuid5(
                        NAMESPACE_URL,
                        f"ugc:selection-maturity:{item.paid_item_id}",
                    ),
                    None,
                    item.paid_item_id,
                    current.order_id,
                    current.payment_id,
                    current.client_id,
                    current.policy.version,
                    deadline,
                    deadline,
                    deadline + timedelta(days=14),
                ),
                session=session,
            )
            for ground in fresh_grounds:
                if ground.paid_item_id == item.paid_item_id:
                    await self._release(ground, schedule, now, session=session)
            results.append(
                {
                    "paid_item_id": str(item.paid_item_id),
                    "refund_deadline_at": deadline.isoformat(),
                    "available_at": schedule.release_at.isoformat(),
                }
            )
        return {"state": "per_item", "items": results}

    @staticmethod
    def _require_stable(before, current, fresh_grounds, users, now):
        if (
            before.client_id,
            before.payment_id,
            before.policy,
            tuple(p.paid_item_id for p in before.positions),
        ) != (
            current.client_id,
            current.payment_id,
            current.policy,
            tuple(p.paid_item_id for p in current.positions),
        ) or any(g.recipient_id not in users for g in fresh_grounds):
            raise ValueError("financial_scope_changed_retry_required")
        if current.captured_at > now or any(
            p.resolved_at is not None and p.resolved_at > now
            for p in current.positions
        ):
            raise ValueError("selection_fact_in_future")

    async def _schedule(
        self, current, closed, rules, fresh_grounds, now, *, session
    ):
        repo, order_id = self.repository, current.order_id
        results = []
        for item in current.positions:
            if item.delivered_at is None or item.refunded_at is not None:
                continue
            await repo.require_clear(item.paid_item_id, session=session)
            deadline = rules.selection_refund_deadline(
                item_delivered_at=item.delivered_at,
                order_closed_at=closed.closed_at,
            )
            release = rules.selection_available_at(
                item_delivered_at=item.delivered_at,
                order_closed_at=closed.closed_at,
            )
            assert deadline is not None and release is not None
            schedule = await repo.save_schedule(
                SelectionMaturitySource(
                    uuid5(closed.closure_id, str(item.paid_item_id)),
                    closed.closure_id,
                    item.paid_item_id,
                    order_id,
                    current.payment_id,
                    current.client_id,
                    current.policy.version,
                    deadline,
                    release - timedelta(days=14),
                    release,
                ),
                session=session,
            )
            for ground in fresh_grounds:
                if ground.paid_item_id == item.paid_item_id:
                    await self._release(ground, schedule, now, session=session)
            results.append(
                {
                    "paid_item_id": str(item.paid_item_id),
                    "refund_deadline_at": deadline.isoformat(),
                    "available_at": release.isoformat(),
                }
            )
        return results

    async def _close(
        self, current, actor_id, reason, evidence, now, *, session
    ):
        repo, rules = self.repository, current.policy.refund_rules
        closed = await repo.get_closure(current.order_id, session=session)
        if closed is not None:
            return closed
        manual = rules.selection_closure_mode == "manual"
        if manual and actor_id is None:
            return {"state": "awaiting_manual_closure"}
        if manual and not all(
            isinstance(v, str) and v.strip() for v in (reason, evidence)
        ):
            raise ValueError("selection_closure_evidence_required")
        at = rules.selection_closed_at(
            position_resolved_at=tuple(
                p.resolved_at for p in current.positions
            ),
            manual_closed_at=now if manual else None,
        )
        if at is None:
            return {"state": "partially_fulfilled"}
        return await repo.save_closure(
            SelectionClosure(
                uuid5(NAMESPACE_URL, f"ugc:selection-close:{current.order_id}"),
                current.order_id,
                current.client_id,
                current.payment_id,
                current.policy.version,
                at,
                {
                    "refund_rules": rules.to_document(),
                    "positions": canonical(
                        [asdict(p) for p in current.positions]
                    ),
                },
                actor_id,
                reason,
                evidence,
                now,
            ),
            session=session,
        )

    async def _authorize(self, current, actor_id, principal, *, session):
        actor = await self.repository.load_actor(actor_id, session=session)
        if actor is None:
            raise PermissionError("selection_close_forbidden")
        require_current_principal(
            principal, actor_id, actor.user_id, actor.telegram_id, actor.max_id
        )
        if not (
            (actor.is_admin and actor.status == "active")
            or (
                actor.user_id == current.client_id
                and actor.is_client
                and actor.status in ("active", "pause", "bot_blocked")
            )
        ):
            raise PermissionError("selection_close_forbidden")

    async def _grounds(self, source, *, session):
        result = []
        for position in source.positions:
            result.extend(
                await self.ledger.repository.list_item_grounds(
                    position.paid_item_id, "client_referral", session=session
                )
            )
        return tuple(result)

    async def _release(self, ground, schedule, now, *, session):
        original = await self.ledger.repository.get_issue(
            ground.business_key, session=session
        )
        if original is None:
            raise ValueError("selection_obligation_missing")
        schedule.require_for(original.basis)
        report = await FinancialReconciliationService(
            self.ledger.repository
        ).require_ready(ground.recipient_id, "RUB", session=session)
        balances = dict(report.replay.by_obligation[ground.obligation_id])
        if schedule.closure_id is None and balances["blocked"]:
            return
        for source, target, at in (
            ("pending", "hold", schedule.hold_started_at),
            ("hold", "available", schedule.release_at),
        ):
            amount = balances[source]
            if not amount or now < at:
                continue
            movement = JournalMovement(
                obligation_id=ground.obligation_id,
                operation_key=f"selection-{target}:{schedule.source_id}:{ground.obligation_id}",
                event_id=str(schedule.closure_id or schedule.source_id),
                movement_type="transfer",
                amount_minor=amount,
                currency="RUB",
                effective_at=at,
                recorded_at=now,
                actor_id=None,
                actor_kind="system",
                system_actor="selection_maturity",
                reason="delivered_selection_" + target,
                bucket_from=source,
                bucket_to=target,
            )
            await self.ledger.transfer(
                ground.business_key, movement, now=now, session=session
            )
            balances[source] -= amount
            balances[target] += amount
