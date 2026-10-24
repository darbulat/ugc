"""Administrative override commands and immutable temporal facts."""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import ClassVar, Literal, Protocol
from uuid import UUID

from ugc_bot.application.financial_ports import ApprovedRateOverride
from ugc_bot.domain.financial import utc

Side = Literal["client", "creator"]


@dataclass(frozen=True, slots=True)
class OverrideUser:
    user_id: UUID
    status: str
    is_admin: bool
    telegram_id: str | None = None
    max_id: str | None = None


@dataclass(frozen=True, slots=True)
class OverridePolicy:
    version: str
    approved_by: UUID
    approved_at: datetime
    effective_from: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class OverrideCommand:
    operation_key: str
    actor_id: UUID
    recipient_id: UUID
    side: Side
    policy_version: str
    reason: str
    action: ClassVar[str]

    def __post_init__(self):
        self._validate_references()
        self._validate_provenance()
        self._validate_temporal()

    def _validate_references(self):
        for name in ("actor_id", "recipient_id", "override_id"):
            if not hasattr(self, name):
                continue
            value = getattr(self, name)
            if not isinstance(value, UUID) or value.int == 0:
                raise ValueError("override_identity_required")
        if self.side not in ("client", "creator"):
            raise ValueError("invalid_override_side")

    def _validate_provenance(self):
        for name, limit in (
            ("operation_key", 256),
            ("reason", 4000),
            ("policy_version", 256),
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
            ):
                raise ValueError("override_provenance_required")

    def _validate_temporal(self):
        for name in ("effective_from", "effective_until", "effective_at"):
            if hasattr(self, name):
                object.__setattr__(self, name, utc(getattr(self, name)))
        if hasattr(self, "rate_bps") and (
            type(self.rate_bps) is not int or not 0 < self.rate_bps <= 10000
        ):
            raise ValueError("invalid_override_rate")
        if (
            hasattr(self, "effective_until")
            and self.effective_until <= self.effective_from
        ):
            raise ValueError("invalid_override_period")
        if hasattr(self, "expected_version") and (
            type(self.expected_version) is not int or self.expected_version < 1
        ):
            raise ValueError("override_expected_version_required")


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateRateOverride(OverrideCommand):
    action: ClassVar[str] = "create"
    rate_bps: int
    effective_from: datetime
    effective_until: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class RevokeRateOverride(OverrideCommand):
    action: ClassVar[str] = "revoke"
    override_id: UUID
    expected_version: int
    effective_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SupersedeRateOverride(OverrideCommand):
    action: ClassVar[str] = "supersede"
    override_id: UUID
    expected_version: int
    rate_bps: int
    effective_from: datetime
    effective_until: datetime


RateOverrideCommand = (
    CreateRateOverride | RevokeRateOverride | SupersedeRateOverride
)


@dataclass(frozen=True, slots=True)
class OverrideState:
    approval: ApprovedRateOverride
    version: int
    revoked_at: datetime | None = None

    def active_at(self, as_of: datetime) -> bool:
        at = utc(as_of)
        return (
            self.approval.approved_at <= at
            and self.approval.effective_from
            <= at
            < self.approval.effective_until
            and (self.revoked_at is None or at < self.revoked_at)
        )


@dataclass(frozen=True, slots=True)
class OverrideCommandResult:
    operation_key: str
    action: str
    override: OverrideState
    replacement: OverrideState | None
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class OverrideReceipt:
    operation_key: str
    payload_hash: str
    actor_id: UUID
    action: str
    reason: str
    recorded_at: datetime
    result: OverrideCommandResult


@dataclass(frozen=True, slots=True)
class OverrideEvent:
    event_id: UUID
    operation_key: str
    override_id: UUID
    version: int
    event_type: Literal["created", "revoked", "superseded"]
    effective_at: datetime
    replacement_id: UUID | None
    actor_id: UUID
    reason: str
    recorded_at: datetime


def canonical(value):
    if isinstance(value, datetime):
        return utc(value).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    return value


def select_approval(
    states: tuple[OverrideState, ...], as_of: datetime
) -> ApprovedRateOverride | None:
    at = utc(as_of)
    active = [state.approval for state in states if state.active_at(at)]
    if len(active) > 1:
        raise ValueError("override_approval_ambiguous")
    return active[0] if active else None


def command_hash(command: RateOverrideCommand) -> str:
    payload = {"action": command.action, **asdict(command)}
    return hashlib.sha256(
        json.dumps(
            canonical(payload), sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def result_from_payload(payload: dict) -> OverrideCommandResult:
    def state(value):
        approval = dict(value["approval"])
        for name in ("override_id", "recipient_id", "approved_by"):
            approval[name] = UUID(approval[name])
        for name in ("effective_from", "effective_until", "approved_at"):
            approval[name] = datetime.fromisoformat(approval[name])
        return OverrideState(
            ApprovedRateOverride(**approval),
            value["version"],
            datetime.fromisoformat(value["revoked_at"])
            if value["revoked_at"]
            else None,
        )

    return OverrideCommandResult(
        payload["operation_key"],
        payload["action"],
        state(payload["override"]),
        state(payload["replacement"]) if payload["replacement"] else None,
        datetime.fromisoformat(payload["recorded_at"]),
    )


class RateOverrideRepository(Protocol):
    async def lock_users(
        self, user_ids: tuple[UUID, ...], *, session: object
    ) -> dict[UUID, OverrideUser]: ...
    async def lock_policy(
        self, policy_version: str, operation_key: str, *, session: object
    ) -> OverridePolicy | None: ...
    async def get_command(
        self, operation_key: str, *, session: object
    ) -> OverrideReceipt | None: ...
    async def get(
        self, override_id: UUID, *, session: object
    ) -> OverrideState | None: ...
    async def list_scope(
        self,
        recipient_id: UUID,
        side: Side,
        policy_version: str,
        *,
        session: object,
    ) -> tuple[OverrideState, ...]: ...
    async def select_effective_override(
        self,
        recipient_id: UUID,
        side: Side,
        policy_version: str,
        as_of: datetime,
        *,
        session: object,
    ) -> ApprovedRateOverride | None: ...
    async def persist(
        self,
        receipt: OverrideReceipt,
        approvals: tuple[ApprovedRateOverride, ...],
        events: tuple[OverrideEvent, ...],
        *,
        session: object,
    ) -> None: ...


class RateOverrideSelector(Protocol):
    async def select_effective_override(
        self,
        recipient_id: UUID,
        side: Side,
        policy_version: str,
        as_of: datetime,
        *,
        session: object,
    ) -> ApprovedRateOverride | None: ...
