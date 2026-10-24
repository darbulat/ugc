"""Committed attempt -> unlocked transport -> fresh lifecycle observation.

This dedicated owner handles only notice_requested. Uncertain dispatches are
never automatically retried; first failures remain sticky in the lifecycle.
No provider acceptance is described as reading, consent, or an entitlement.
"""

from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.application.notice_delivery_ports import (
    NOTICE_EVENT_TYPE,
    DeliveryFailure,
    DeliveryReceipt,
    NoticeAttempt,
    NoticeDeliveryRepository,
    NoticeOutcome,
    NoticeReceiptTransport,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.application.services.notice_message import notice_message
from ugc_bot.domain.collaboration import CollaborationState
from ugc_bot.domain.enums import OutboxEventStatus
from ugc_bot.domain.financial import utc


@dataclass(slots=True)
class CollaborationNoticeDelivery:
    lifecycle: CollaborationService
    repository: NoticeDeliveryRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport
    miniapp_url: str | dict[str, str]
    lease_seconds: int = 120
    default_locale: str = "ru"

    def _now(self):
        return utc(self.lifecycle.clock.now())

    @staticmethod
    def _proof(origin):
        if origin is None:
            return False
        event, notice, source = origin.event, origin.notice, origin.source
        if notice is None or source is None:
            return False
        work = source.result.collaboration
        objection = notice.purpose == "objection"
        expected_recipient = (
            work.client_id
            if work.claimant_id == work.creator_id
            else work.creator_id
        )
        return (
            event.event_type == NOTICE_EVENT_TYPE
            and event.event_id == notice.notice_id
            and event.aggregate_type == "collaboration"
            and event.aggregate_id == str(notice.assignment_id)
            and event.payload == {"notice_id": str(notice.notice_id)}
            and source.event_id == notice.source_event_id
            and source.assignment_id
            == notice.assignment_id
            == work.assignment_id
            and notice.created_at == source.occurred_at == event.created_at
            and (
                objection
                and source.event_type
                == "financial.collaboration.success_claimed"
                and source.parameters.get("action") == "claim"
                and work.state == CollaborationState.SUCCESS_CLAIMED
                and work.claimed_at == source.occurred_at
                and notice.recipient_id == expected_recipient
                or not objection
                and notice.purpose == "confirmation"
                and source.event_type
                == "financial.collaboration.confirmation_requested"
                and source.parameters.get("action") == "request_confirmation"
                and notice.recipient_id in (work.client_id, work.creator_id)
            )
        )

    async def _current(self, origin, session):
        """Item lock only; current contact/role reads must never lock users."""
        repo = self.lifecycle.repository
        notice, source = origin.notice, origin.source
        try:
            scope = await repo.lock_scope(notice.assignment_id, session=session)
        except ValueError:
            return None, None, "assignment_not_found", True
        current = await repo.get(notice.assignment_id, session=session)
        contact = await self.repository.contact(
            notice.recipient_id, session=session
        )
        if current is None:
            return None, contact, "collaboration_not_found", True
        work, original = current.collaboration, source.result.collaboration
        if (
            scope.valid_to is not None
            or not scope.selection_funded
            or not scope.policy_version
            or scope.captured_at is None
            or (
                scope.client_id,
                scope.creator_id,
                scope.manager_id,
                scope.paid_item_id,
                scope.order_id,
                scope.policy_version,
            )
            != (
                work.client_id,
                work.creator_id,
                work.manager_id,
                current.paid_item_id,
                current.order_id,
                current.policy_version,
            )
            or (
                original.client_id,
                original.creator_id,
                source.result.paid_item_id,
                source.result.order_id,
            )
            != (
                work.client_id,
                work.creator_id,
                current.paid_item_id,
                current.order_id,
            )
        ):
            return current, contact, "assignment_obsolete", True
        for user_id, role in (
            (work.client_id, "is_client"),
            (work.creator_id, "is_creator"),
        ):
            actor = await repo.load_actor(user_id, session=session)
            if (
                actor is None
                or not getattr(actor, role)
                or actor.status not in ("active", "pause", "bot_blocked")
            ):
                return current, contact, "party_role_revoked", True
        invalid, obsolete = await self._phase_error(
            origin, scope, current, session
        )
        if invalid:
            return current, contact, invalid, obsolete
        if (
            contact is None
            or contact.user_id != notice.recipient_id
            or not contact.address
        ):
            return current, contact, "recipient_contact_unavailable", False
        if contact.status not in ("active", "pause"):
            return current, contact, "recipient_unreachable", False
        if contact.channel not in ("telegram", "max"):
            return current, contact, "receipt_channel_unavailable", False
        return current, contact, None, False

    async def _phase_error(self, origin, scope, current, session):
        repo = self.lifecycle.repository
        notice, source = origin.notice, origin.source
        work, original = current.collaboration, source.result.collaboration
        if notice.purpose == "objection":
            if (
                work.state != CollaborationState.SUCCESS_CLAIMED
                or work.claimant_id != original.claimant_id
                or work.claimed_at != original.claimed_at
                or work.evidence != original.evidence
            ):
                return "claim_obsolete", True
            if work.notice_delivered_at is not None:
                return "notice_already_recorded", True
            deadline = work.objection_deadline
        else:
            if (
                work.state
                not in (
                    CollaborationState.ASSIGNED,
                    CollaborationState.IN_PROGRESS,
                )
                or work.due_version != original.due_version
                or current.terms_reference != source.result.terms_reference
            ):
                return "confirmation_obsolete", True
            initiator = await repo.load_actor(source.actor_id, session=session)
            if (
                initiator is None
                or initiator.status not in ("active", "pause", "bot_blocked")
                or not (
                    initiator.user_id == scope.client_id
                    and initiator.is_client
                    or initiator.user_id == scope.manager_id
                    and scope.order_id in initiator.manager_order_ids
                )
            ):
                return "requester_role_revoked", True
            deadline = work.first_claim_deadline
        if self._now() >= deadline:
            return "notice_deadline_elapsed", False
        return None, False

    async def _state(self, job, state, session, reason=None):
        await self.repository.save_job(
            replace(job, state=state), session=session
        )
        await self.repository.settle_event(
            job.event_id, state, self._now(), reason, session=session
        )

    async def _observation(
        self,
        origin,
        attempt,
        kind,
        status,
        reference,
        reason,
        session,
        *,
        apply=True,
    ):
        previous = await self.repository.list_outcomes(
            attempt.attempt_id, session=session
        )
        if any(item.kind == kind for item in previous):
            return
        current, _, invalid, obsolete = await self._current(origin, session)
        applied = False
        if (
            apply
            and not obsolete
            and current is not None
            and origin.notice.purpose == "objection"
            and attempt.channel in ("telegram", "max")
        ):
            accepted = status == "accepted"
            if not accepted or invalid is None:
                await self.lifecycle.execute(
                    CollaborationCommand(
                        assignment_id=attempt.assignment_id,
                        action="notice",
                        operation_key=f"notifier:{attempt.attempt_id}:{kind}",
                        expected_version=current.version,
                        system_actor="collaboration_notifier",
                        notice_id=attempt.notice_id,
                        accepted=accepted,
                        channel=attempt.channel,
                        external_reference=reference if accepted else None,
                        reason=reason if not accepted else None,
                    ),
                    session=session,
                )
                applied = True
        await self.repository.save_outcome(
            NoticeOutcome(
                uuid5(attempt.attempt_id, kind),
                attempt.attempt_id,
                kind,
                status,
                self._now(),
                reference,
                reason or invalid,
                applied,
            ),
            session=session,
        )

    async def _recover(self, origin, job, session):
        attempt = await self.repository.get_attempt(
            job.current_attempt_id, session=session
        )
        await self._observation(
            origin,
            attempt,
            "recovery",
            "unknown",
            None,
            "delivery_result_unknown",
            session,
        )
        await self._state(job, "unknown", session, "delivery_result_unknown")

    async def prepare(self, event_id: UUID) -> NoticeAttempt | None:
        async with self.transactions.transaction() as session:
            origin = await self.repository.origin(event_id, session=session)
            if origin is None:
                return None
            if not self._proof(origin):
                await self.repository.settle_event(
                    event_id,
                    "failed",
                    self._now(),
                    "notice_event_proof_invalid",
                    session=session,
                )
                return None
            # Lock the authoritative item before the queue/lease.
            current, contact, invalid, obsolete = await self._current(
                origin, session
            )
            job = await self.repository.lock_job(origin, session=session)
            origin = await self.repository.origin(event_id, session=session)
            if not self._proof(origin):
                await self._state(
                    job, "failed", session, "notice_event_proof_invalid"
                )
                return None
            assert origin is not None
            assert origin.notice is not None and origin.source is not None
            if job.state in ("prepared", "sending"):
                if job.lease_until <= self._now():
                    await self._recover(origin, job, session)
                return None
            if (
                job.state != "ready"
                or origin.event.status != OutboxEventStatus.PENDING
            ):
                return None
            now = self._now()
            locale = (
                contact.locale
                if contact and contact.locale
                else self.default_locale
            )
            action_url = action_label = None
            try:
                miniapp_url = (
                    self.miniapp_url.get(contact.channel if contact else "", "")
                    if isinstance(self.miniapp_url, dict)
                    else self.miniapp_url
                )
                rendered = notice_message(origin, locale, miniapp_url)
                text, deadline = rendered.text, rendered.deadline
                action_url, action_label = (
                    rendered.action_url,
                    rendered.action_label,
                )
            except (ValueError, UnicodeError) as exc:
                text, deadline = (
                    "",
                    origin.source.result.collaboration.objection_deadline
                    or origin.source.result.collaboration.first_claim_deadline,
                )
                invalid, obsolete = str(exc), False
            attempt = NoticeAttempt(
                uuid4(),
                event_id,
                origin.notice.notice_id,
                origin.notice.assignment_id,
                origin.notice.source_event_id,
                origin.notice.recipient_id,
                job.attempt_count + 1,
                uuid4(),
                now,
                now + timedelta(seconds=self.lease_seconds),
                current.version if current else origin.source.result.version,
                contact.channel if contact else None,
                contact.address if contact else None,
                contact.address_kind if contact else "chat_id",
                locale,
                text,
                deadline,
                action_url,
                action_label,
            )
            await self.repository.save_attempt(attempt, session=session)
            job = replace(
                job,
                state="prepared",
                attempt_count=attempt.number,
                current_attempt_id=attempt.attempt_id,
                lease_token=attempt.lease_token,
                lease_until=attempt.lease_until,
            )
            await self._state(job, "prepared", session)
            if invalid:
                status = "obsolete" if obsolete else "failed"
                await self._observation(
                    origin,
                    attempt,
                    "transport",
                    status,
                    None,
                    invalid,
                    session,
                    apply=not obsolete,
                )
                await self._state(job, status, session, invalid)
                return None
            if attempt.number > 1 and origin.notice.purpose == "objection":
                # A retry is review-only even if an earlier unsupported channel
                # could not be expressed in the lifecycle's channel vocabulary.
                await self._observation(
                    origin,
                    attempt,
                    "retry_guard",
                    "failed",
                    None,
                    "redelivery_requires_manual_review",
                    session,
                )
            return attempt

    async def _begin_dispatch(self, attempt: NoticeAttempt) -> bool:
        async with self.transactions.transaction() as session:
            stored = await self.repository.get_attempt(
                attempt.attempt_id, session=session
            )
            if stored != attempt:
                raise ValueError("notice_attempt_snapshot_invalid")
            origin = await self.repository.origin(
                attempt.event_id, session=session
            )
            if not self._proof(origin):
                return False
            assert origin is not None
            _, contact, invalid, obsolete = await self._current(origin, session)
            job = await self.repository.lock_job(origin, session=session)
            if (
                job.current_attempt_id != attempt.attempt_id
                or job.lease_token != attempt.lease_token
                or job.state != "prepared"
            ):
                return False
            if job.lease_until <= self._now():
                await self._recover(origin, job, session)
                return False
            if not invalid and (
                contact.channel,
                contact.address,
                contact.address_kind,
                contact.locale or self.default_locale,
            ) != (
                attempt.channel,
                attempt.address,
                attempt.address_kind,
                attempt.locale,
            ):
                invalid = "recipient_contact_changed"
            if invalid:
                status = "obsolete" if obsolete else "failed"
                await self._observation(
                    origin,
                    attempt,
                    "transport",
                    status,
                    None,
                    invalid,
                    session,
                    apply=not obsolete,
                )
                await self._state(job, status, session, invalid)
                return False
            await self._state(job, "sending", session)
        return True

    async def _send_once(self, attempt):
        try:
            receipt = await self.transport.send(attempt)
            if (
                not isinstance(receipt, DeliveryReceipt)
                or receipt.channel != attempt.channel
                or not isinstance(receipt.reference, str)
                or not receipt.reference.strip()
            ):
                raise DeliveryFailure(
                    "provider_receipt_unavailable", uncertain=True
                )
            status, reference, reason = "accepted", receipt.reference, None
        except DeliveryFailure as exc:
            status, reference, reason = (
                "unknown" if exc.uncertain else "failed",
                None,
                exc.code,
            )
        except Exception:
            status, reference, reason = "unknown", None, "transport_exception"
        return status, reference, reason

    async def _finish_dispatch(self, attempt, status, reference, reason):
        async with self.transactions.transaction() as session:
            origin = await self.repository.origin(
                attempt.event_id, session=session
            )
            if not self._proof(origin):
                # The immutable prepared attempt is still authoritative for
                # auditing the actual I/O. A changed envelope cannot authorize
                # any lifecycle mutation, but must not erase a real receipt.
                await self._audit_unproven_result(
                    attempt, status, reference, reason, session
                )
                return
            _, contact, invalid, obsolete = await self._current(origin, session)
            job = await self.repository.lock_job(origin, session=session)
            owned = (
                job.current_attempt_id == attempt.attempt_id
                and job.lease_token == attempt.lease_token
                and job.state == "sending"
            )
            if owned and job.lease_until <= self._now():
                await self._recover(origin, job, session)
                owned = False
            if not invalid and (
                contact.channel,
                contact.address,
                contact.address_kind,
                contact.locale or self.default_locale,
            ) != (
                attempt.channel,
                attempt.address,
                attempt.address_kind,
                attempt.locale,
            ):
                invalid = "recipient_contact_changed"
            if owned and invalid and not obsolete:
                await self._observation(
                    origin,
                    attempt,
                    "context_guard",
                    "failed",
                    None,
                    invalid,
                    session,
                )
            await self._observation(
                origin,
                attempt,
                "transport",
                status,
                reference,
                reason or invalid,
                session,
                apply=owned and not invalid,
            )
            if owned:
                settled = (
                    "obsolete"
                    if obsolete
                    else "failed"
                    if invalid
                    else "complete"
                    if status == "accepted"
                    else status
                )
                await self._state(job, settled, session, reason or invalid)

    async def _audit_unproven_result(
        self, attempt, status, reference, reason, session
    ):
        previous = await self.repository.list_outcomes(
            attempt.attempt_id, session=session
        )
        if any(item.kind == "transport" for item in previous):
            return
        await self.repository.save_outcome(
            NoticeOutcome(
                uuid5(attempt.attempt_id, "transport"),
                attempt.attempt_id,
                "transport",
                status,
                self._now(),
                reference,
                "notice_event_proof_invalid" + (f":{reason}" if reason else ""),
                False,
            ),
            session=session,
        )

    async def deliver(self, attempt: NoticeAttempt) -> None:
        if not await self._begin_dispatch(attempt):
            return
        # Provider I/O has no open transaction or locked ORM object.
        status, reference, reason = await self._send_once(attempt)
        await self._finish_dispatch(attempt, status, reference, reason)

    async def run_once(self, *, limit: int = 100) -> int:
        if (
            type(limit) is not int
            or not 1 <= limit <= 1000
            or type(self.lease_seconds) is not int
            or self.lease_seconds < 1
        ):
            raise ValueError("notice_batch_or_lease_invalid")
        async with self.transactions.transaction() as session:
            ids = await self.repository.candidates(
                self._now(), limit, session=session
            )
        for event_id in ids:
            attempt = await self.prepare(event_id)
            if attempt is not None:
                await self.deliver(attempt)
        return len(ids)

    async def retry_notice(self, event_id, *, actor_id, reason, operation_key):
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > 1000
        ):
            raise ValueError("notice_retry_reason_required")
        if (
            not isinstance(operation_key, str)
            or not operation_key.strip()
            or len(operation_key) > 200
        ):
            raise ValueError("notice_retry_key_required")
        async with self.transactions.transaction() as session:
            origin = await self.repository.origin(event_id, session=session)
            if not self._proof(origin):
                raise ValueError("notice_event_proof_invalid")
            _, _, invalid, obsolete = await self._current(origin, session)
            actor = await self.lifecycle.repository.load_actor(
                actor_id, session=session
            )
            if actor is None or actor.status != "active" or not actor.is_admin:
                raise PermissionError("current_notice_admin_required")
            job = await self.repository.lock_job(origin, session=session)
            key = f"{event_id}:{operation_key}"
            previous = await self.repository.retry_outcome(key, session=session)
            if previous is not None:
                if (
                    previous.actor_id != actor_id
                    or previous.reason != reason.strip()
                ):
                    raise ValueError("notice_retry_payload_conflict")
                return
            if obsolete:
                raise ValueError(invalid)
            if job.state not in ("failed", "unknown"):
                raise ValueError("notice_retry_state_conflict")
            await self.repository.save_outcome(
                NoticeOutcome(
                    uuid5(NAMESPACE_URL, key),
                    job.current_attempt_id,
                    "retry",
                    "authorized",
                    self._now(),
                    None,
                    reason.strip(),
                    False,
                    actor_id,
                    key,
                ),
                session=session,
            )
            await self._state(
                replace(job, lease_token=None, lease_until=None),
                "ready",
                session,
            )
