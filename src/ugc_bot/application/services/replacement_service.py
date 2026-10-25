"""Reviewed replacements keep one paid position and cancel old liabilities."""

from uuid import uuid4

from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.replacement_ports import replacement_hash
from ugc_bot.domain.financial import utc


class ReplacementService:
    def __init__(
        self, repository, ledger, compensation, clock, *, enabled=False
    ):
        self.repository, self.ledger = repository, ledger
        self.compensation, self.clock, self.enabled = (
            compensation,
            clock,
            enabled,
        )

    async def _grounds(self, item_id, session):
        result = []
        for kind in ("creator_referral", "management"):
            result.extend(
                await self.ledger.repository.list_item_grounds(
                    item_id, kind, session=session
                )
            )
        return tuple(result)

    async def _locked(
        self,
        actor_id,
        item_id,
        interest_id,
        principal,
        session,
        *,
        admin=False,
        command=None,
    ):
        repo, ledger = self.repository, self.ledger.repository
        before = await repo.load_scope(item_id, session=session)
        candidate = (
            await repo.candidate(interest_id, session=session)
            if interest_id
            else None
        )
        grounds = await self._grounds(item_id, session)
        users = {
            actor_id,
            before.client_id,
            *before.creator_ids,
            *before.manager_ids,
        }
        if before.manager_id is not None:
            users.add(before.manager_id)
        users.update(g.recipient_id for g in grounds)
        if candidate is not None:
            users.add(candidate.creator_id)
        await ledger.lock_recipients(
            tuple(sorted(users, key=str)), session=session
        )
        await ledger.lock_wallets(
            tuple(
                sorted(
                    {(g.recipient_id, g.currency) for g in grounds},
                    key=lambda k: (str(k[0]), k[1]),
                )
            ),
            session=session,
        )
        await repo.lock_scope(before, session=session)
        await ledger.lock_item(item_id, session=session)
        current = await repo.load_scope(item_id, session=session)
        fresh = await self._grounds(item_id, session)
        changed = before != current or any(
            g.recipient_id not in users for g in fresh
        )
        actor = await repo.load_actor(actor_id, session=session)
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        active_admin = (
            actor is not None and actor.is_admin and actor.status == "active"
        )
        if admin and not active_admin:
            raise PermissionError("active_admin_required")
        if not admin and not (
            active_admin
            or (
                actor is not None
                and actor.is_client
                and actor.user_id == current.client_id
                and actor.status in ("active", "pause", "bot_blocked")
            )
        ):
            raise PermissionError("replacement_forbidden")
        if changed:
            # A concurrent identical command may have committed during locking.
            # Current authentication still precedes its immutable receipt.
            # Changed scopes never authorize fresh writes.
            previous = await self._replay(command, session) if command else None
            if previous is None:
                raise ValueError("financial_scope_changed_retry_required")
            return current, fresh, previous
        return current, fresh, None

    async def _replay(self, command, session):
        previous = await self.repository.get_command(
            command.actor_id, command.operation_key, session=session
        )
        if previous is not None:
            if previous[0] != replacement_hash(command):
                raise ValueError("idempotency_payload_conflict")
            return previous[1]
        return None

    async def _save(self, command, result, session):
        await self.repository.save_command(
            command.actor_id,
            command.operation_key,
            replacement_hash(command),
            result,
            session=session,
        )
        return result

    @staticmethod
    def _replaceable(scope, expected, now):
        if scope.assignment_version != expected:
            raise ValueError("replacement_assignment_version_conflict")
        if scope.completed_work:
            raise ValueError("replacement_after_completed_work_forbidden")
        if not scope.order_active or scope.selection_state not in (
            "paid",
            "delivered",
        ):
            raise ValueError("replacement_position_unavailable")
        if now < max(scope.captured_at, scope.assignment_from):
            raise ValueError("replacement_fact_in_future")

    async def _candidate(self, interest_id, scope, now, session):
        candidate = await self.repository.candidate(
            interest_id, session=session
        )
        if (
            candidate is None
            or not candidate.verified
            or candidate.used
            or candidate.creator_id in scope.creator_ids
            or candidate.creator_id == scope.client_id
            or (
                candidate.order_id,
                candidate.payment_id,
                candidate.capture_event_id,
                candidate.policy_version,
            )
            != (
                scope.order_id,
                scope.payment_id,
                scope.capture_event_id,
                scope.policy_version,
            )
            or not scope.captured_at <= candidate.confirmed_at <= now
        ):
            raise ValueError("replacement_confirmed_reserve_required")
        return candidate

    def _enabled(self):
        if not self.enabled:
            raise ValueError("financial_core_paused")

    async def queue(self, actor_id, *, page=0, principal=None, session):
        if type(page) is not int or not 0 <= page <= 100000:
            raise ValueError("replacement_queue_invalid")
        await self.ledger.repository.lock_recipients(
            (actor_id,), session=session
        )
        actor = await self.repository.load_actor(actor_id, session=session)
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        if actor is None or not actor.is_admin or actor.status != "active":
            raise PermissionError("active_admin_required")
        return dict(
            actor_id=str(actor_id),
            **await self.repository.queue(page, session=session),
        )

    async def view(self, actor_id, item_id, *, principal=None, session):
        scope, _, _ = await self._locked(
            actor_id, item_id, None, principal, session
        )
        actor = await self.repository.load_actor(actor_id, session=session)
        facts = await self.repository.view(
            scope, admin=actor.is_admin, session=session
        )
        return dict(
            actor_id=str(actor_id),
            paid_item_id=str(item_id),
            order_id=str(scope.order_id),
            assignment_id=str(scope.assignment_id),
            assignment_version=scope.assignment_version,
            original_paid_pool=scope.original_paid_pool,
            reserve_limit=scope.original_paid_pool // 5,
            replacement_count=scope.replacement_count,
            completed_work=scope.completed_work,
            writes_paused=not self.enabled,
            capabilities=dict(
                request=self.enabled and not scope.completed_work,
                review=self.enabled
                and actor.is_admin
                and actor.status == "active",
            ),
            **facts,
        )

    async def contact(self, command, *, principal=None, session):
        allocation = await self.repository.allocation(
            command.replacement_id, session=session
        )
        if allocation is None:
            raise ValueError("replacement_allocation_not_found")
        scope, _, previous = await self._locked(
            command.actor_id,
            allocation["paid_item_id"],
            allocation["candidate_interest_id"],
            principal,
            session,
            command=command,
        )
        previous = previous or await self._replay(command, session)
        if previous is not None:
            return previous
        if allocation["assignment_id"] != scope.assignment_id:
            raise ValueError("replacement_assignment_obsolete")
        await self.repository.require_clear(scope.paid_item_id, session=session)
        candidate = await self.repository.candidate(
            allocation["candidate_interest_id"], session=session
        )
        if (
            candidate is None
            or not candidate.verified
            or candidate.creator_id != scope.creator_id
        ):
            raise ValueError("replacement_contact_unavailable")
        contact = await self.repository.contact(scope, session=session)
        identity, now = uuid4(), utc(self.clock.now())
        await self.repository.append_contact(
            dict(
                contact_id=identity,
                replacement_id=command.replacement_id,
                actor_id=command.actor_id,
                reason=command.reason,
                evidence_reference=command.evidence_reference,
                contact=contact,
                recorded_at=now,
            ),
            session=session,
        )
        return await self._save(
            command,
            dict(
                contact_id=str(identity),
                replacement_id=str(command.replacement_id),
                operation_key=command.operation_key,
                contact=contact,
                billable_positions_added=0,
                state="disclosed",
            ),
            session,
        )

    async def request(self, command, *, principal=None, session):
        self._enabled()
        scope, _, previous = await self._locked(
            command.actor_id,
            command.paid_item_id,
            command.candidate_interest_id,
            principal,
            session,
            command=command,
        )
        previous = previous or await self._replay(command, session)
        if previous is not None:
            return previous
        now = utc(self.clock.now())
        self._replaceable(scope, command.expected_assignment_version, now)
        await self.repository.require_clear(scope.paid_item_id, session=session)
        candidate = await self._candidate(
            command.candidate_interest_id, scope, now, session
        )
        identity = uuid4()
        fact = dict(
            request_id=identity,
            paid_item_id=scope.paid_item_id,
            order_id=scope.order_id,
            client_id=scope.client_id,
            payment_id=scope.payment_id,
            old_assignment_id=scope.assignment_id,
            old_assignment_version=scope.assignment_version,
            candidate_interest_id=candidate.interest_id,
            actor_id=command.actor_id,
            reason_code=command.reason_code,
            reason=command.reason,
            evidence_reference=command.evidence_reference,
            original_paid_pool=scope.original_paid_pool,
            capture_hash=scope.capture_hash,
            version=1,
            requested_at=now,
        )
        await self.repository.append_request(fact, session=session)
        return await self._save(
            command,
            dict(
                request_id=str(identity),
                operation_key=command.operation_key,
                version=1,
                state="pending",
                paid_item_id=str(scope.paid_item_id),
            ),
            session,
        )

    async def decide(self, command, *, principal=None, session):
        self._enabled()
        request = await self.repository.request(
            command.request_id, session=session
        )
        if request is None:
            raise ValueError("replacement_request_not_found")
        scope, grounds, previous = await self._locked(
            command.actor_id,
            request["paid_item_id"],
            request["candidate_interest_id"],
            principal,
            session,
            admin=True,
            command=command,
        )
        previous = previous or await self._replay(command, session)
        if previous is not None:
            return previous
        if (
            await self.repository.decision(command.request_id, session=session)
            is not None
        ):
            raise ValueError("replacement_request_already_reviewed")
        if command.expected_version != request["version"]:
            raise ValueError("replacement_request_version_conflict")
        now, identity = utc(self.clock.now()), uuid4()
        if now < request["requested_at"]:
            raise ValueError("replacement_fact_in_future")
        fact = dict(
            replacement_id=identity,
            request_id=command.request_id,
            paid_item_id=scope.paid_item_id,
            order_id=scope.order_id,
            actor_id=command.actor_id,
            version=2,
            action=command.action,
            reason=command.reason,
            evidence_reference=command.evidence_reference,
            exception_reason=command.exception_reason,
            exception_evidence=command.exception_evidence,
            original_paid_pool=scope.original_paid_pool,
            prior_replacements=scope.replacement_count,
            reserve_limit=scope.original_paid_pool // 5,
            reviewed_at=now,
        )
        if command.action == "reject":
            await self.repository.append_decision(fact, session=session)
            return await self._save(
                command,
                dict(
                    replacement_id=str(identity),
                    request_id=str(command.request_id),
                    operation_key=command.operation_key,
                    version=2,
                    state="rejected",
                ),
                session,
            )
        self._replaceable(scope, request["old_assignment_version"], now)
        if (
            scope.assignment_id != request["old_assignment_id"]
            or scope.payment_id != request["payment_id"]
            or scope.capture_hash != request["capture_hash"]
            or scope.original_paid_pool != request["original_paid_pool"]
        ):
            raise ValueError("replacement_source_changed")
        await self.repository.require_clear(scope.paid_item_id, session=session)
        candidate = await self._candidate(
            request["candidate_interest_id"], scope, now, session
        )
        exception = scope.replacement_count >= scope.original_paid_pool // 5
        if exception and not command.exception_reason:
            raise ValueError("replacement_reserve_exception_required")
        manager = (
            command.manager_id
            if command.manager_id is not None
            else scope.manager_id
        )
        if manager is not None and (
            not scope.accompaniment or manager not in scope.manager_ids
        ):
            raise ValueError("replacement_active_manager_required")
        await self.repository.append_decision(fact, session=session)
        movements = await self._cancel(
            grounds, scope, identity, command.actor_id, now, session
        )
        assignment = await self.repository.replace_assignment(
            scope,
            candidate,
            manager,
            command.actor_id,
            command.reason,
            now,
            session=session,
        )
        await self.repository.append_allocation(
            dict(
                replacement_id=identity,
                paid_item_id=scope.paid_item_id,
                old_assignment_id=scope.assignment_id,
                assignment_id=assignment,
                assignment_version=scope.assignment_version + 1,
                candidate_interest_id=candidate.interest_id,
                manager_id=manager,
                movement_ids=list(movements),
                allocated_at=now,
            ),
            session=session,
        )
        result = dict(
            replacement_id=str(identity),
            request_id=str(command.request_id),
            operation_key=command.operation_key,
            version=2,
            state="approved",
            paid_item_id=str(scope.paid_item_id),
            assignment_id=str(assignment),
            assignment_version=scope.assignment_version + 1,
            creator_id=str(candidate.creator_id),
            original_paid_pool=scope.original_paid_pool,
            reserve_limit=scope.original_paid_pool // 5,
            replacement_count=scope.replacement_count + 1,
            reserve_exception=exception,
            billable_positions_added=0,
            cancelled_movement_ids=[str(value) for value in movements],
        )
        return await self._save(command, result, session)

    async def _cancel(self, grounds, scope, identity, actor_id, now, session):
        movements = []
        for ground in sorted(grounds, key=lambda g: str(g.obligation_id)):
            original = await self.ledger.repository.get_issue(
                ground.business_key, session=session
            )
            if (
                original is None
                or original.basis.paid_item_id != scope.paid_item_id
                or original.basis.order_id != scope.order_id
                or original.basis.payment_id != scope.payment_id
                or original.basis.assignment_id not in scope.assignment_ids
                or original.basis.kind not in ("creator_referral", "management")
            ):
                raise ValueError("replacement_original_ground_mismatch")
            journal = await self.ledger.repository.list_for_recipient(
                ground.recipient_id, ground.currency, session=session
            )
            entries = [
                entry
                for entry in journal
                if entry.obligation_id == original.obligation_id
            ]
            prior = sum(
                entry.amount_minor
                for entry in entries
                if entry.movement_type in ("reversal", "debt")
            )
            reserved = sum(
                entry.amount_minor
                * (
                    (entry.bucket_to == "reserved")
                    - (entry.bucket_from == "reserved")
                )
                for entry in entries
            )
            if reserved:
                raise ValueError("correction_reserved_review_required")
            if any(
                entry.bucket_to == "paid" or entry.movement_type == "debt"
                for entry in entries
            ):
                raise ValueError("replacement_paid_ground_review_required")
            movements.extend(
                await self.compensation.cancel(
                    original,
                    target_minor=original.movement.amount_minor,
                    already_cancelled_minor=prior,
                    case_id=identity,
                    refund_id=identity,
                    actor_id=actor_id,
                    now=now,
                    session=session,
                )
            )
        return tuple(movements)
