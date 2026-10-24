"""Transactional memory adapter for authorized immutable override commands."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

from ugc_bot.application.override_ports import OverrideState, select_approval


class InMemoryRateOverrideRepository:
    def __init__(self, *, users=None, policies=None):
        self.users, self.policies = dict(users or {}), dict(policies or {})
        self.approvals, self.commands, self.events = {}, {}, {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            before = deepcopy((self.approvals, self.commands, self.events))
            session = {"owner": self}
            try:
                yield session
            except BaseException:
                self.approvals, self.commands, self.events = before
                raise
            finally:
                session["owner"] = None

    def _session(self, session):
        if not isinstance(session, dict) or session.get("owner") is not self:
            raise ValueError("caller_transaction_required")

    async def lock_users(self, user_ids, *, session):
        self._session(session)
        return {
            uid: self.users[uid]
            for uid in sorted(set(user_ids), key=str)
            if uid in self.users
        }

    async def lock_policy(self, policy_version, operation_key, *, session):
        self._session(session)
        return self.policies.get(policy_version)

    async def get_command(self, operation_key, *, session):
        self._session(session)
        return self.commands.get(operation_key)

    async def get(self, override_id, *, session):
        self._session(session)
        approval = self.approvals.get(override_id)
        if approval is None:
            return None
        events = [
            e for e in self.events.values() if e.override_id == override_id
        ]
        revoked = [
            e.effective_at
            for e in events
            if e.event_type in ("revoked", "superseded")
        ]
        return OverrideState(
            approval,
            max((e.version for e in events), default=1),
            min(revoked) if revoked else None,
        )

    async def list_scope(self, recipient_id, side, policy_version, *, session):
        self._session(session)
        return tuple(
            [
                await self.get(a.override_id, session=session)
                for a in self.approvals.values()
                if (a.recipient_id, a.side, a.policy_version)
                == (recipient_id, side, policy_version)
            ]
        )

    async def select_effective_override(
        self, recipient_id, side, policy_version, as_of, *, session
    ):
        if side not in ("client", "creator"):
            raise ValueError("invalid_override_side")
        return select_approval(
            await self.list_scope(
                recipient_id, side, policy_version, session=session
            ),
            as_of,
        )

    async def persist(self, receipt, approvals, events, *, session):
        self._session(session)
        old = self.commands.get(receipt.operation_key)
        if old is not None:
            if old.payload_hash != receipt.payload_hash:
                raise ValueError("idempotency_payload_conflict")
            return
        self.commands[receipt.operation_key] = receipt
        for approval in approvals:
            if approval.override_id in self.approvals:
                raise ValueError("override_approval_immutable")
            self.approvals[approval.override_id] = approval
        for event in events:
            if any(
                e.override_id == event.override_id
                and e.version == event.version
                for e in self.events.values()
            ):
                raise ValueError("override_version_conflict")
            self.events[event.event_id] = event
