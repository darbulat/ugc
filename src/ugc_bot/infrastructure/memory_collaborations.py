"""Transactional in-memory lifecycle adapter with the same caller boundary."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

from ugc_bot.application.collaboration_ports import (
    CollaborationPrincipalScope,
    next_transition_at,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OutboxEventStatus


class InMemoryCollaborationRepository:
    def __init__(self, scopes=None, actors=None):
        self.scopes = dict(scopes or {})
        self.actors = dict(actors or {})
        self.records = {}
        self.events = {}
        self.notices = {}
        self.schedules = {}
        self.outbox = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            session = {
                "owner": self,
                "records": deepcopy(self.records),
                "events": deepcopy(self.events),
                "notices": deepcopy(self.notices),
                "schedules": deepcopy(self.schedules),
                "outbox": deepcopy(self.outbox),
            }
            try:
                yield session
                for name in (
                    "records",
                    "events",
                    "notices",
                    "schedules",
                    "outbox",
                ):
                    setattr(self, name, session[name])
            finally:
                session["owner"] = None

    def _session(self, session):
        if not isinstance(session, dict) or session.get("owner") is not self:
            raise ValueError("caller_transaction_required")
        return session

    async def _lock_principal_users(self, user_ids, *, session):
        self._session(session)
        return {uid: self.actors.get(uid) for uid in user_ids}

    async def prepare_principal_scope(
        self,
        assignment_id,
        actor_id,
        principal,
        *,
        session,
    ):
        self._session(session)
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        scope = self.scopes.get(assignment_id)
        user_ids = tuple(
            sorted(
                {actor_id}
                if scope is None
                else {actor_id, scope.client_id, scope.creator_id}
                | ({scope.manager_id} if scope.manager_id else set())
            )
        )
        prepared = (
            CollaborationPrincipalScope(
                assignment_id=scope.assignment_id,
                paid_item_id=scope.paid_item_id,
                order_id=scope.order_id,
                client_id=scope.client_id,
                creator_id=scope.creator_id,
                manager_id=scope.manager_id,
                actor_id=actor_id,
                user_ids=user_ids,
                owner_session=session,
                root_transaction=session,
            )
            if scope
            else None
        )
        users = await self._lock_principal_users(user_ids, session=session)
        actor = users.get(actor_id)
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        if prepared is None:
            return None
        if any(user is None for user in users.values()):
            raise ValueError("collaboration_scope_changed")
        await self.lock_scope(
            assignment_id,
            session=session,
            expected_scope=prepared,
        )
        return prepared

    async def lock_scope(
        self,
        assignment_id,
        *,
        session,
        expected_scope=None,
    ):
        self._session(session)
        if expected_scope is not None and (
            expected_scope.owner_session is not session
            or expected_scope.root_transaction is not session
        ):
            raise ValueError("caller_transaction_required")
        if assignment_id not in self.scopes:
            raise ValueError(
                "collaboration_scope_changed"
                if expected_scope
                else "assignment_not_found"
            )
        scope = self.scopes[assignment_id]
        if expected_scope is not None:
            expected_scope.require_source(scope)
        return scope

    async def load_actor(self, actor_id, *, session):
        self._session(session)
        return self.actors.get(actor_id)

    async def get(self, assignment_id, *, session):
        return self._session(session)["records"].get(assignment_id)

    async def get_command(self, assignment_id, operation_key, *, session):
        return self._session(session)["events"].get(
            (assignment_id, operation_key)
        )

    async def get_notice(self, notice_id, *, session):
        return self._session(session)["notices"].get(notice_id)

    async def list_due(self, at, limit, *, session):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("invalid_batch_limit")
        due = [
            record
            for record in self._session(session)["records"].values()
            if (deadline := next_transition_at(record.collaboration))
            is not None
            and deadline <= at
            and self.scopes[record.collaboration.assignment_id].valid_to is None
        ]
        return tuple(
            sorted(
                due,
                key=lambda record: (
                    next_transition_at(record.collaboration),
                    str(record.collaboration.assignment_id),
                ),
            )[:limit]
        )

    async def persist(self, event, *, notices, schedule, session):
        state = self._session(session)
        state["records"][event.assignment_id] = event.result
        state["events"][(event.assignment_id, event.operation_key)] = event
        state["outbox"][event.event_id] = self._outbox(
            event.event_id,
            event.event_type,
            event.assignment_id,
            {"collaboration_event_id": str(event.event_id)},
            event.occurred_at,
        )
        for notice in notices:
            if notice.notice_id not in state["notices"]:
                state["notices"][notice.notice_id] = notice
                state["outbox"][notice.notice_id] = self._outbox(
                    notice.notice_id,
                    "financial.collaboration.notice_requested",
                    notice.assignment_id,
                    {"notice_id": str(notice.notice_id)},
                    notice.created_at,
                )
        if schedule is not None:
            state["schedules"][schedule.schedule_id] = schedule

    @staticmethod
    def _outbox(event_id, event_type, assignment_id, payload, at):
        return OutboxEvent(
            event_id=event_id,
            event_type=event_type,
            aggregate_id=str(assignment_id),
            aggregate_type="collaboration",
            payload=payload,
            status=OutboxEventStatus.PENDING,
            created_at=at,
            processed_at=None,
            retry_count=0,
            last_error=None,
        )
