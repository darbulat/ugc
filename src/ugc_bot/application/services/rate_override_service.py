"""Admin commands append temporal facts; payment snapshots stay immutable."""

from dataclasses import replace
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.financial_ports import ApprovedRateOverride, Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.override_ports import (
    CreateRateOverride,
    OverrideCommandResult,
    OverrideEvent,
    OverrideReceipt,
    OverrideState,
    RateOverrideCommand,
    RateOverrideRepository,
    RevokeRateOverride,
    Side,
    SupersedeRateOverride,
    command_hash,
)
from ugc_bot.domain.financial import utc


class RateOverrideService:
    def __init__(self, repository: RateOverrideRepository, clock: Clock):
        self.repository, self.clock = repository, clock

    async def execute(
        self,
        command: RateOverrideCommand,
        *,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> OverrideCommandResult:
        if not isinstance(
            command,
            (CreateRateOverride, RevokeRateOverride, SupersedeRateOverride),
        ):
            raise ValueError("typed_override_command_required")
        repo = self.repository
        users = await repo.lock_users(
            tuple(sorted({command.actor_id, command.recipient_id}, key=str)),
            session=session,
        )
        self._require_admin(
            users.get(command.actor_id), command.actor_id, principal
        )
        policy = await repo.lock_policy(
            command.policy_version, command.operation_key, session=session
        )
        digest = command_hash(command)
        previous = await repo.get_command(
            command.operation_key, session=session
        )
        if previous is not None:
            if previous.payload_hash != digest:
                raise ValueError("idempotency_payload_conflict")
            return previous.result
        if command.recipient_id not in users:
            raise ValueError("override_recipient_not_found")
        if (
            policy is None
            or policy.version != command.policy_version
            or not isinstance(policy.approved_by, UUID)
            or policy.approved_by.int == 0
            or utc(policy.approved_at) > utc(policy.effective_from)
        ):
            raise ValueError("approved_policy_required")
        now = utc(self.clock.now())
        effective = (
            command.effective_at
            if isinstance(command, RevokeRateOverride)
            else command.effective_from
        )
        if effective < now or effective < utc(policy.effective_from):
            raise ValueError("override_backdating_forbidden")
        old = await self._target(command, session=session)
        approvals: tuple[ApprovedRateOverride, ...]
        events: tuple[OverrideEvent, ...]
        if isinstance(command, RevokeRateOverride):
            assert old is not None
            result = OverrideCommandResult(
                command.operation_key,
                command.action,
                replace(old, version=old.version + 1, revoked_at=effective),
                None,
                now,
            )
            approvals = ()
            events = (
                self._event(
                    command, result.override, "revoked", effective, None, now
                ),
            )
        else:
            await self._require_no_overlap(
                command,
                excluded=old.approval.override_id if old else None,
                session=session,
            )
            approval = ApprovedRateOverride(
                override_id=uuid5(
                    NAMESPACE_URL, "ugc:rate-override:" + command.operation_key
                ),
                recipient_id=command.recipient_id,
                side=command.side,
                rate_bps=command.rate_bps,
                policy_version=command.policy_version,
                effective_from=command.effective_from,
                effective_until=command.effective_until,
                approved_by=command.actor_id,
                approved_at=now,
                reason=command.reason,
            )
            new = OverrideState(approval, 1)
            approvals = (approval,)
            created = self._event(command, new, "created", effective, None, now)
            if old is None:
                result = OverrideCommandResult(
                    command.operation_key, command.action, new, None, now
                )
                events = (created,)
            else:
                ended = replace(
                    old, version=old.version + 1, revoked_at=effective
                )
                result = OverrideCommandResult(
                    command.operation_key, command.action, ended, new, now
                )
                events = (
                    self._event(
                        command,
                        ended,
                        "superseded",
                        effective,
                        approval.override_id,
                        now,
                    ),
                    created,
                )
        await repo.persist(
            OverrideReceipt(
                command.operation_key,
                digest,
                command.actor_id,
                command.action,
                command.reason,
                now,
                result,
            ),
            approvals,
            events,
            session=session,
        )
        return result

    async def _target(self, command, *, session):
        if isinstance(command, CreateRateOverride):
            return None
        old = await self.repository.get(command.override_id, session=session)
        if old is None:
            raise ValueError("override_not_found")
        a = old.approval
        if (a.recipient_id, a.side, a.policy_version) != (
            command.recipient_id,
            command.side,
            command.policy_version,
        ):
            raise ValueError("override_scope_mismatch")
        if command.expected_version != old.version:
            raise ValueError("override_version_conflict")
        if old.revoked_at is not None:
            raise ValueError("override_already_revoked")
        effective = (
            command.effective_at
            if isinstance(command, RevokeRateOverride)
            else command.effective_from
        )
        if effective >= a.effective_until:
            raise ValueError("override_change_outside_period")
        return old

    async def _require_no_overlap(self, command, *, excluded, session):
        states = await self.repository.list_scope(
            command.recipient_id,
            command.side,
            command.policy_version,
            session=session,
        )
        for state in states:
            a = state.approval
            end = min(a.effective_until, state.revoked_at or a.effective_until)
            if (
                a.override_id != excluded
                and a.effective_from < end
                and command.effective_from < end
                and a.effective_from < command.effective_until
            ):
                raise ValueError("override_period_overlaps")

    @staticmethod
    def _event(command, state, event_type, effective, replacement, now):
        return OverrideEvent(
            uuid5(
                NAMESPACE_URL,
                f"ugc:rate-override-event:{command.operation_key}:{state.approval.override_id}",
            ),
            command.operation_key,
            state.approval.override_id,
            state.version,
            event_type,
            effective,
            replacement,
            command.actor_id,
            command.reason,
            now,
        )

    @staticmethod
    def _require_admin(actor, actor_id, principal):
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor is not None else None,
            actor.telegram_id if actor is not None else None,
            actor.max_id if actor is not None else None,
        )
        if (
            actor is None
            or actor.status != "active"
            or actor.is_admin is not True
        ):
            raise ValueError("active_admin_required")

    async def get_for_admin(
        self,
        override_id: UUID,
        *,
        actor_id: UUID,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> OverrideState | None:
        users = await self.repository.lock_users((actor_id,), session=session)
        self._require_admin(users.get(actor_id), actor_id, principal)
        return await self.repository.get(override_id, session=session)

    async def lookup(
        self, override_id: UUID, *, as_of: datetime, session: object
    ) -> ApprovedRateOverride | None:
        state = await self.repository.get(override_id, session=session)
        return (
            state.approval
            if state is not None and state.active_at(as_of)
            else None
        )

    async def list_for_admin(
        self,
        recipient_id: UUID,
        side: Side,
        policy_version: str,
        *,
        actor_id: UUID,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> tuple[OverrideState, ...]:
        users = await self.repository.lock_users(
            tuple(sorted({actor_id, recipient_id}, key=str)), session=session
        )
        self._require_admin(users.get(actor_id), actor_id, principal)
        if recipient_id not in users:
            raise ValueError("override_recipient_not_found")
        if side not in ("client", "creator"):
            raise ValueError("invalid_override_side")
        return await self.repository.list_scope(
            recipient_id, side, policy_version, session=session
        )

    async def select_effective(
        self,
        *,
        recipient_id: UUID,
        side: Side,
        policy_version: str,
        as_of: datetime,
        session: object,
    ) -> ApprovedRateOverride | None:
        at = utc(as_of)
        if side not in ("client", "creator"):
            raise ValueError("invalid_override_side")
        return await self.repository.select_effective_override(
            recipient_id, side, policy_version, at, session=session
        )
