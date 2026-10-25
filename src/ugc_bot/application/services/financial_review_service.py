"""Review existing income without rewriting original issues or paid history."""

from uuid import uuid4

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.corrections import (
    correction_payload_hash,
    require_text,
    require_uuid,
)
from ugc_bot.domain.financial import utc

LIQUID = ("pending", "hold", "available")


def cancelled_minor(journal, obligation_id):
    return sum(
        m.amount_minor
        for m in journal
        if m.obligation_id == obligation_id
        and m.movement_type in ("reversal", "debt")
    )


class FinancialReviewService:
    def __init__(self, repository, ledger, compensation, clock):
        self.repository, self.ledger = repository, ledger
        self.compensation, self.clock = compensation, clock

    async def _admin(self, actor_id, principal, session):
        actor = await self.repository.actor(actor_id, session=session)
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        if actor is None or not actor.admin or actor.status != "active":
            raise PermissionError("financial_review_active_admin_required")

    async def _locked(self, actor_id, key, principal, session):
        scope = await self.repository.load_scope(key, session=session)
        if scope is None:
            raise ValueError("financial_review_ground_not_found")
        basis = scope.original.basis
        users = {
            actor_id,
            basis.recipient_id,
            scope.capture.client_id,
            basis.referred_user_id,
            *scope.user_ids,
        }
        await self.ledger.repository.lock_recipients(
            tuple(sorted(users, key=str)), session=session
        )
        await self.ledger.repository.lock_wallets(
            ((basis.recipient_id, basis.currency),), session=session
        )
        await self.repository.lock_scope(scope, session=session)
        await self.ledger.repository.lock_item(
            basis.paid_item_id, session=session
        )
        current = await self.repository.load_scope(key, session=session)
        if (
            current is None
            or current.original != scope.original
            or not set(current.user_ids) <= users
        ):
            raise ValueError("financial_scope_changed_retry_required")
        await self._admin(actor_id, principal, session)
        return current

    async def _replay(self, command, session):
        prior = await self.repository.command(
            command.actor_id, command.operation_key, session=session
        )
        if prior is not None:
            if prior["payload_hash"] != correction_payload_hash(command):
                raise ValueError("idempotency_payload_conflict")
            return prior["result"]
        return None

    async def _save(self, command, result, session):
        await self.repository.save_command(
            command.actor_id,
            command.operation_key,
            correction_payload_hash(command),
            result,
            utc(self.clock.now()),
            session=session,
        )
        return result

    async def _money(self, scope, session):
        basis = scope.original.basis
        report = await FinancialReconciliationService(
            self.ledger.repository
        ).require_ready(basis.recipient_id, basis.currency, session=session)
        journal = await self.ledger.repository.list_for_recipient(
            basis.recipient_id, basis.currency, session=session
        )
        return dict(
            report.replay.by_obligation[scope.original.obligation_id]
        ), journal

    async def open(self, command, *, session, principal=None):
        scope = await self._locked(
            command.actor_id, command.business_key, principal, session
        )
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        if scope.source_hash != command.expected_source_hash:
            raise ValueError("financial_review_source_changed")
        if (
            await self.repository.active_case(
                scope.original.obligation_id, session=session
            )
            is not None
        ):
            raise ValueError("financial_review_already_open")
        balances, journal = await self._money(scope, session)
        now = utc(self.clock.now())
        if now < max(
            m.recorded_at
            for m in journal
            if m.obligation_id == scope.original.obligation_id
        ):
            raise ValueError("financial_review_time_conflict")
        prior = cancelled_minor(journal, scope.original.obligation_id)
        if prior >= scope.original.movement.amount_minor:
            raise ValueError("financial_review_no_liability")
        basis = scope.original.basis
        fact = dict(
            case_id=uuid4(),
            obligation_id=scope.original.obligation_id,
            business_key=basis.business_key,
            paid_item_id=basis.paid_item_id,
            order_id=basis.order_id,
            recipient_id=basis.recipient_id,
            currency=basis.currency,
            opened_by=command.actor_id,
            operation_key=command.operation_key,
            opened_at=now,
            opened_source_hash=scope.source_hash,
            source_document=scope.source_document,
            blocked_buckets={b: balances[b] for b in LIQUID},
            prior_cancelled_minor=prior,
            reason=command.reason,
            evidence_reference=command.evidence_reference,
            evidence_hash=command.evidence_hash,
        )
        await self.repository.append_case(fact, session=session)
        for bucket in LIQUID:
            if balances[bucket]:
                await self._move(
                    scope.original,
                    fact["case_id"],
                    "block:" + bucket,
                    bucket,
                    "blocked",
                    balances[bucket],
                    command.actor_id,
                    now,
                    session,
                )
        return await self._save(
            command, await self._view(fact, session), session
        )

    async def resolve(self, command, *, session, principal=None):
        fact = await self.repository.case(command.case_id, session=session)
        if fact is None:
            raise ValueError("financial_review_case_not_found")
        scope = await self._locked(
            command.actor_id, fact["business_key"], principal, session
        )
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        (
            balances,
            prior,
            target,
            now,
            release_at,
        ) = await self._resolution_values(command, scope, session)
        resolution = dict(
            case_id=command.case_id,
            version=2,
            actor_id=command.actor_id,
            operation_key=command.operation_key,
            expected_source_hash=scope.source_hash,
            decision=command.decision,
            target_minor=target,
            prior_cancelled_minor=prior,
            cancelled_delta_minor=target - prior,
            debt_created_minor=0,
            release_at=release_at,
            restored_buckets={},
            reason=command.reason,
            evidence_reference=command.evidence_reference,
            evidence_hash=command.evidence_hash,
            resolved_at=now,
        )
        delta = target - prior
        liquid_before_blocked = sum(balances[b] for b in LIQUID)
        blocked_cancelled = min(
            balances["blocked"], max(0, delta - liquid_before_blocked)
        )
        resolution["debt_created_minor"] = max(
            0, delta - liquid_before_blocked - balances["blocked"]
        )
        restores = self._restores(fact, target, release_at, now)
        if sum(restores.values()) > balances["blocked"] - blocked_cancelled:
            raise ValueError("financial_review_blocked_source_changed")
        resolution["restored_buckets"] = restores
        await self.repository.append_resolution(resolution, session=session)
        if target > prior:
            await self.compensation.cancel(
                scope.original,
                target_minor=target,
                already_cancelled_minor=prior,
                case_id=command.case_id,
                refund_id=command.case_id,
                actor_id=command.actor_id,
                now=now,
                session=session,
            )
        for bucket, amount in restores.items():
            if amount:
                await self._move(
                    scope.original,
                    command.case_id,
                    "restore:" + bucket,
                    "blocked",
                    bucket,
                    amount,
                    command.actor_id,
                    now,
                    session,
                )
        return await self._save(
            command, await self._view(fact, session), session
        )

    async def _resolution_values(self, command, scope, session):
        if (
            command.expected_version != 1
            or await self.repository.resolution(
                command.case_id, session=session
            )
            is not None
        ):
            raise ValueError("financial_review_version_conflict")
        if command.expected_source_hash != scope.source_hash:
            raise ValueError("financial_review_source_changed")
        balances, journal = await self._money(scope, session)
        prior = cancelled_minor(journal, scope.original.obligation_id)
        now = utc(self.clock.now())
        if now < max(
            m.recorded_at
            for m in journal
            if m.obligation_id == scope.original.obligation_id
        ):
            raise ValueError("financial_review_time_conflict")
        if command.decision == "cumulative_cancel" and balances["reserved"]:
            raise ValueError("correction_reserved_review_required")
        target = (
            prior
            if command.decision == "no_adjustment"
            else command.target_minor
        )
        if not prior <= target <= scope.original.movement.amount_minor:
            raise ValueError("correction_cumulative_target_invalid")
        release_at = await self.ledger._release_time(
            scope.original, session=session
        )
        return balances, prior, target, now, release_at

    @staticmethod
    def _restores(fact, target, release_at, now):
        removed = target - fact["prior_cancelled_minor"]
        result = dict.fromkeys(LIQUID, 0)
        for bucket in LIQUID:
            original = fact["blocked_buckets"][bucket]
            taken = min(original, removed)
            removed -= taken
            amount = original - taken
            destination = (
                "hold"
                if bucket == "available"
                and (release_at is None or now < release_at)
                else bucket
            )
            result[destination] += amount
        return result

    async def _move(
        self,
        original,
        case_id,
        suffix,
        before,
        after,
        amount,
        actor,
        now,
        session,
    ):
        movement = JournalMovement(
            obligation_id=original.obligation_id,
            operation_key=f"financial-review:{case_id}:{suffix}",
            event_id=str(case_id),
            movement_type="transfer",
            amount_minor=amount,
            currency=original.basis.currency,
            effective_at=now,
            recorded_at=now,
            actor_id=actor,
            actor_kind="admin",
            reason="Explicit financial review " + suffix,
            bucket_from=before,
            bucket_to=after,
            case_id=case_id,
        )
        # The case authorizes exact restoration into the original buckets.
        written = await self.ledger.repository.append(movement, session=session)
        await self.ledger.repository.apply_projection(written, session=session)

    async def _view(self, fact, session):
        scope = await self.repository.load_scope(
            fact["business_key"], session=session
        )
        balances, _ = await self._money(scope, session)
        resolution = await self.repository.resolution(
            fact["case_id"], session=session
        )
        result = dict(
            case_id=str(fact["case_id"]),
            version=2 if resolution else 1,
            state="resolved" if resolution else "open",
            business_key=fact["business_key"],
            obligation_id=str(fact["obligation_id"]),
            kind=scope.original.basis.kind,
            recipient_id=str(fact["recipient_id"]),
            paid_item_id=str(fact["paid_item_id"]),
            amount_minor=scope.original.movement.amount_minor,
            currency=fact["currency"],
            buckets=balances,
            current_source_hash=scope.source_hash,
            opened_source_hash=fact["opened_source_hash"],
            reason=fact["reason"],
            evidence_reference=fact["evidence_reference"],
            opened_at=fact["opened_at"].isoformat(),
        )
        if resolution:
            result.update(
                {
                    k: resolution[k]
                    for k in (
                        "decision",
                        "target_minor",
                        "cancelled_delta_minor",
                        "debt_created_minor",
                    )
                }
            )
        return result

    async def view(self, actor_id, case_id, *, session, principal=None):
        require_uuid(actor_id)
        require_uuid(case_id)
        fact = await self.repository.case(case_id, session=session)
        if fact is None:
            raise ValueError("financial_review_case_not_found")
        await self._locked(actor_id, fact["business_key"], principal, session)
        return await self._view(fact, session)

    async def context(
        self,
        actor_id,
        *,
        session,
        principal=None,
        page=0,
        limit=25,
        business_key=None,
    ):
        require_uuid(actor_id)
        if (
            type(page) is not int
            or not 0 <= page <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("financial_review_invalid_page")
        if business_key is not None:
            require_text(business_key)
        await self.ledger.repository.lock_recipients(
            (actor_id,), session=session
        )
        await self._admin(actor_id, principal, session)
        return await self.repository.context(
            page=page, limit=limit, business_key=business_key, session=session
        )
