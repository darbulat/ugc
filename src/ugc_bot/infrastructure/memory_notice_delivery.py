"""Atomic in-memory notice adapter sharing the lifecycle caller transaction."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace

from ugc_bot.application.notice_delivery_ports import (
    NOTICE_EVENT_TYPE,
    DeliveryJob,
    NoticeOrigin,
)
from ugc_bot.domain.enums import OutboxEventStatus


class InMemoryNoticeDeliveryRepository:
    def __init__(self, collaborations, contacts=None):
        self.collaborations = collaborations
        self.contacts = dict(contacts or {})
        self.jobs = {}
        self.attempts = {}
        self.outcomes = {}

    @asynccontextmanager
    async def transaction(self):
        async with self.collaborations.transaction() as session:
            session["notice_owner"] = self
            for key in ("jobs", "attempts", "outcomes"):
                session["notice_" + key] = deepcopy(getattr(self, key))
            yield session
            for key in ("jobs", "attempts", "outcomes"):
                setattr(self, key, session["notice_" + key])
            session["notice_owner"] = None

    def _state(self, session, key):
        self.collaborations._session(session)
        if session.get("notice_owner") is not self:
            raise ValueError("caller_notice_transaction_required")
        return session["notice_" + key]

    async def candidates(self, at, limit, *, session):
        jobs = self._state(session, "jobs")
        events = session["outbox"]
        return tuple(
            event.event_id
            for event in sorted(
                events.values(), key=lambda x: (x.created_at, str(x.event_id))
            )
            if event.event_type == NOTICE_EVENT_TYPE
            and (
                event.status == OutboxEventStatus.PENDING
                or (
                    event.status == OutboxEventStatus.PROCESSING
                    and event.event_id in jobs
                    and jobs[event.event_id].lease_until <= at
                )
            )
        )[:limit]

    async def origin(self, event_id, *, session):
        self._state(session, "jobs")
        event = session["outbox"].get(event_id)
        if event is None or event.event_type != NOTICE_EVENT_TYPE:
            return None
        notice = session["notices"].get(event_id)
        source = next(
            (
                item
                for item in session["events"].values()
                if notice and item.event_id == notice.source_event_id
            ),
            None,
        )
        return NoticeOrigin(event, notice, source)

    async def contact(self, recipient_id, *, session):
        self._state(session, "jobs")
        return self.contacts.get(recipient_id)

    async def lock_job(self, origin, *, session):
        jobs = self._state(session, "jobs")
        if origin.event.event_id not in jobs:
            jobs[origin.event.event_id] = DeliveryJob(
                origin.event.event_id, origin.notice.notice_id
            )
        return jobs[origin.event.event_id]

    async def save_job(self, job, *, session):
        self._state(session, "jobs")[job.event_id] = job

    async def save_attempt(self, attempt, *, session):
        attempts = self._state(session, "attempts")
        if attempt.attempt_id in attempts:
            raise ValueError("notice_attempt_immutable")
        attempts[attempt.attempt_id] = attempt

    async def get_attempt(self, attempt_id, *, session):
        return self._state(session, "attempts")[attempt_id]

    async def list_outcomes(self, attempt_id, *, session):
        return tuple(
            item
            for item in self._state(session, "outcomes").values()
            if item.attempt_id == attempt_id
        )

    async def retry_outcome(self, operation_key, *, session):
        return next(
            (
                item
                for item in self._state(session, "outcomes").values()
                if item.kind == "retry" and item.operation_key == operation_key
            ),
            None,
        )

    async def save_outcome(self, outcome, *, session):
        outcomes = self._state(session, "outcomes")
        previous = outcomes.get(outcome.outcome_id)
        if previous is not None and previous != outcome:
            raise ValueError("notice_outcome_immutable")
        outcomes[outcome.outcome_id] = outcome

    async def settle_event(self, event_id, state, at, reason=None, *, session):
        self._state(session, "jobs")
        event = session["outbox"][event_id]
        if event.event_type != NOTICE_EVENT_TYPE:
            raise ValueError("notice_event_owner_required")
        status = {
            "ready": OutboxEventStatus.PENDING,
            "prepared": OutboxEventStatus.PROCESSING,
            "sending": OutboxEventStatus.PROCESSING,
            "complete": OutboxEventStatus.PUBLISHED,
            "obsolete": OutboxEventStatus.PUBLISHED,
            "failed": OutboxEventStatus.FAILED,
            "unknown": OutboxEventStatus.FAILED,
        }[state]
        session["outbox"][event_id] = replace(
            event,
            status=status,
            processed_at=at
            if status in (OutboxEventStatus.PUBLISHED, OutboxEventStatus.FAILED)
            else None,
            last_error=reason,
        )
