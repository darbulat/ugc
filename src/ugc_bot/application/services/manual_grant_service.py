"""Current superadmin approval creates a separate positive expense and hold."""

from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from ugc_bot.application.financial_ports import IssueBasis, JournalMovement
from ugc_bot.application.manual_grant_ports import (
    ManualGrantAuthority,
    ManualGrantSource,
)
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.corrections import correction_payload_hash
from ugc_bot.domain.financial import utc


class ManualGrantService:
    def __init__(
        self, repository, ledger, funding_guard, clock, superadmins, *, enabled
    ):
        self.repository, self.ledger, self.funding_guard = (
            repository,
            ledger,
            funding_guard,
        )
        self.clock, self.superadmins, self.enabled = (
            clock,
            frozenset(superadmins),
            enabled,
        )

    async def _lock(
        self, item_id, recipient_id, actor_id, principal, *, session
    ):
        if not self.enabled:
            raise ValueError("financial_core_disabled")
        repo, ledger = self.repository, self.ledger.repository
        capture = await repo.load_capture(item_id, session=session)
        users = {capture.client_id, recipient_id}
        if actor_id is not None:
            users.add(actor_id)
        await ledger.lock_recipients(
            tuple(sorted(users, key=str)), session=session
        )
        await ledger.lock_wallets(((recipient_id, "RUB"),), session=session)
        await repo.lock_funding(capture, session=session)
        await ledger.lock_item(item_id, session=session)
        if await repo.load_capture(item_id, session=session) != capture:
            raise ValueError("financial_scope_changed_retry_required")
        if actor_id is not None:
            actor = await repo.actor(actor_id, session=session)
            require_current_principal(
                principal,
                actor_id,
                actor.user_id if actor else None,
                actor.telegram_id if actor else None,
                actor.max_id if actor else None,
            )
            if (
                actor is None
                or not actor.admin
                or actor.status != "active"
                or actor_id not in self.superadmins
            ):
                raise PermissionError("financial_superadmin_required")
        return capture

    async def _require_current_conditions(
        self, item_id, recipient_id, *, session
    ):
        target = await self.repository.actor(recipient_id, session=session)
        if target is None or target.status not in (
            "active",
            "pause",
            "bot_blocked",
        ):
            raise ValueError("manual_grant_recipient_unavailable")
        await self.funding_guard.require_forward_clear(
            item_id, session=session, components=("selection",)
        )
        await self.repository.require_work_clear(item_id, session=session)

    async def approve(self, command, *, session, principal=None):
        capture = await self._lock(
            command.paid_item_id,
            command.recipient_id,
            command.actor_id,
            principal,
            session=session,
        )
        previous = await self.repository.command(
            command.actor_id, command.operation_key, session=session
        )
        digest = correction_payload_hash(command)
        if previous is not None:
            if previous["payload_hash"] != digest:
                raise ValueError("idempotency_payload_conflict")
            return previous["result"]
        await self._require_current_conditions(
            command.paid_item_id, command.recipient_id, session=session
        )
        now = utc(self.clock.now())
        if now < capture.captured_at:
            raise ValueError("manual_grant_before_capture")
        await FinancialReconciliationService(
            self.ledger.repository
        ).require_ready(command.recipient_id, "RUB", session=session)
        source = ManualGrantSource(
            grant_id=uuid4(),
            actor_id=command.actor_id,
            recipient_id=command.recipient_id,
            paid_item_id=command.paid_item_id,
            order_id=capture.order_id,
            client_id=capture.client_id,
            payment_id=capture.payment_id,
            capture_id=capture.event_id,
            policy_version=capture.policy.version,
            amount_minor=command.amount_minor,
            currency=command.currency,
            approved_at=now,
            release_at=now + timedelta(days=14),
            reason=command.reason,
        )
        authority = ManualGrantAuthority(
            tuple(sorted(str(i) for i in self.superadmins))
        )
        await self.repository.append_grant(
            dict(
                asdict(source),
                operation_key=command.operation_key,
                capture_source_hash=capture.source_hash,
                authority=asdict(authority),
                authority_hash=correction_payload_hash(authority),
                evidence_reference=command.evidence_reference,
                evidence_hash=command.evidence_hash,
            ),
            session=session,
        )
        original = await self.ledger.issue(
            self._basis(source), recorded_at=now, session=session
        )
        await self._move(
            source,
            original,
            "pending",
            "hold",
            source.amount_minor,
            now,
            session=session,
        )
        result = dict(
            grant_id=str(source.grant_id),
            obligation_id=str(original.obligation_id),
            amount_minor=source.amount_minor,
            currency=source.currency,
            release_at=source.release_at.isoformat(),
            state="hold",
        )
        await self.repository.save_command(
            command.actor_id,
            command.operation_key,
            digest,
            result,
            now,
            session=session,
        )
        return result

    @staticmethod
    def _basis(source):
        return IssueBasis(
            business_key="manual-grant:" + str(source.grant_id),
            kind="manual_adjustment",
            recipient_id=source.recipient_id,
            paid_item_id=source.paid_item_id,
            order_id=source.order_id,
            assignment_id=None,
            referred_user_id=source.client_id,
            payment_id=source.payment_id,
            currency="RUB",
            base_minor=source.amount_minor,
            rate_bps=None,
            policy_version=source.policy_version,
            snapshot_at=source.approved_at,
            registered_at=None,
            verified_count=None,
            event_id=str(source.grant_id),
            reason=source.reason,
            actor_id=source.actor_id,
            actor_kind="admin",
            available_at=source.release_at,
        )

    async def _move(self, source, original, from_, to, amount, now, *, session):
        await self.ledger.transfer(
            original.basis.business_key,
            JournalMovement(
                obligation_id=original.obligation_id,
                operation_key=f"manual-grant-{to}:{source.grant_id}",
                event_id=str(source.grant_id),
                movement_type="transfer",
                amount_minor=amount,
                currency="RUB",
                effective_at=now,
                recorded_at=now,
                actor_id=None,
                actor_kind="system",
                system_actor="manual_grant",
                reason="approved_manual_grant_" + to,
                bucket_from=from_,
                bucket_to=to,
            ),
            now=now,
            session=session,
        )

    async def mature(self, grant_id, *, session, actor_id=None, principal=None):
        source = await self.repository.source(grant_id, session=session)
        if source is None:
            raise ValueError("manual_grant_not_found")
        capture = await self._lock(
            source.paid_item_id,
            source.recipient_id,
            actor_id,
            principal,
            session=session,
        )
        if (
            capture.order_id,
            capture.payment_id,
            capture.client_id,
            capture.event_id,
            capture.policy.version,
        ) != (
            source.order_id,
            source.payment_id,
            source.client_id,
            source.capture_id,
            source.policy_version,
        ):
            raise ValueError("manual_grant_source_mismatch")
        original = await self.ledger.repository.get_issue(
            "manual-grant:" + str(grant_id), session=session
        )
        if original is None:
            raise ValueError("manual_grant_obligation_missing")
        source.require_for(original.basis)
        await self._require_current_conditions(
            source.paid_item_id, source.recipient_id, session=session
        )
        now = utc(self.clock.now())
        report = await FinancialReconciliationService(
            self.ledger.repository
        ).require_ready(source.recipient_id, "RUB", session=session)
        balances = report.replay.by_obligation[original.obligation_id]
        if balances["hold"] and now >= source.release_at:
            await self._move(
                source,
                original,
                "hold",
                "available",
                balances["hold"],
                now,
                session=session,
            )
        return {
            "grant_id": str(grant_id),
            "mature": now >= source.release_at,
            "release_at": source.release_at.isoformat(),
        }


class ManualGrantSweepService:
    def __init__(self, grants, transactions):
        self.grants, self.transactions = grants, transactions
        self._cursor: tuple[datetime, UUID] | None = None

    async def run_once(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("manual_grant_sweep_limit_invalid")
        async with self.transactions.transaction() as session:
            ready = await self.grants.repository.list_ready(
                utc(self.grants.clock.now()),
                limit,
                after=self._cursor,
                session=session,
            )
        matured, deferred = 0, 0
        for _, identity in ready:
            try:
                async with self.transactions.transaction() as session:
                    result = await self.grants.mature(identity, session=session)
                matured += result["mature"]
            except ValueError:
                deferred += 1
        self._cursor = ready[-1] if len(ready) == limit else None
        return {
            "attempted": len(ready),
            "matured": matured,
            "deferred": deferred,
        }
