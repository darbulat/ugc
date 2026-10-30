"""Pure correction evidence and pending-only cumulative compensation values.

These contracts do not authorize a refund or write a journal. Original capture,
reviewed sources and actual evidence come from trusted application ports.
"""

import hashlib
import json
import re
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from ugc_bot.domain.financial import MAX_MINOR, commission_minor, utc

Component = Literal[
    "selection", "accompaniment", "management", "replacement", "unknown"
]
COMPONENTS = (
    "selection",
    "accompaniment",
    "management",
    "replacement",
    "unknown",
)
type CanonicalValue = (
    None | bool | int | str | list[CanonicalValue] | dict[str, CanonicalValue]
)


def require_uuid(value: UUID) -> None:
    if not isinstance(value, UUID) or not value.int:
        raise ValueError("correction_identity_invalid")


def require_text(value: str, limit: int = 4000) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("correction_provenance_required")


def require_hash(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("correction_hash_invalid")


def require_version(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_MINOR:
        raise ValueError("correction_version_invalid")


def require_minor(value: int, *, positive: bool = False) -> None:
    if type(value) is not int or not int(positive) <= value <= MAX_MINOR:
        raise ValueError("correction_minor_invalid")


def require_currency(value: str) -> None:
    if value != "RUB":
        raise ValueError("unpublished_currency")


def uuid_tuple(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
    if type(values) is not tuple:
        raise ValueError("correction_immutable_ids_required")
    for value in values:
        require_uuid(value)
    if len(set(values)) != len(values):
        raise ValueError("correction_duplicate_identity")
    return tuple(sorted(values))


def _canonical(value: object) -> CanonicalValue:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _canonical(getattr(value, item.name))
            for item in fields(value)
        }
    if type(value) is tuple:
        return [_canonical(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise ValueError("correction_immutable_payload_required")


def correction_payload_hash(value: object) -> str:
    """Existing sorted compact UTF-8 canonical JSON convention, no aliases."""
    return hashlib.sha256(
        json.dumps(
            _canonical(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def cumulative_cancellation_target(
    base_minor: int,
    cumulative_refund_minor: int,
    frozen_rate_bps: int,
    currency: str,
) -> int:
    """E(original gross) - E(remaining base), using the original frozen rate."""
    original = commission_minor(base_minor, frozen_rate_bps, currency)
    require_minor(cumulative_refund_minor)
    if cumulative_refund_minor > base_minor:
        raise ValueError("correction_refund_capacity_exceeded")
    return original - commission_minor(
        base_minor - cumulative_refund_minor, frozen_rate_bps, currency
    )


def pending_cancellation_delta(
    base_minor: int,
    cumulative_refund_minor: int,
    frozen_rate_bps: int,
    currency: str,
    *,
    already_source_linked_cancelled: int,
    pending_minor: int,
    bucket: str = "pending",
) -> int:
    """Zero means no journal; only the entirely pending liability fits."""
    target = cumulative_cancellation_target(
        base_minor, cumulative_refund_minor, frozen_rate_bps, currency
    )
    require_minor(already_source_linked_cancelled)
    require_minor(pending_minor)
    if (
        bucket != "pending"
        or already_source_linked_cancelled > target
        or pending_minor + already_source_linked_cancelled
        != commission_minor(base_minor, frozen_rate_bps, currency)
    ):
        raise ValueError("correction_original_pending_unavailable")
    return target - already_source_linked_cancelled


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionState:
    case_id: UUID
    version: int
    source_hash: str
    request_status: Literal["none", "requested"] = "none"
    review_status: Literal["pending", "approved", "rejected"] = "pending"
    match_status: Literal["unmatched", "matched"] = "unmatched"
    application_status: Literal[
        "unapplied", "awaiting_assessment", "applied", "unavailable"
    ] = "unapplied"
    observation_ids: tuple[UUID, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_uuid(self.case_id)
        require_version(self.version)
        require_hash(self.source_hash)
        if (
            self.request_status not in ("none", "requested")
            or self.review_status not in ("pending", "approved", "rejected")
            or self.match_status not in ("unmatched", "matched")
            or self.application_status
            not in (
                "unapplied",
                "awaiting_assessment",
                "applied",
                "unavailable",
            )
        ):
            raise ValueError("correction_state_invalid")
        object.__setattr__(
            self, "observation_ids", uuid_tuple(self.observation_ids)
        )
        if type(self.blockers) is not tuple:
            raise ValueError("correction_immutable_blockers_required")
        for blocker in self.blockers:
            require_text(blocker, 256)
        if len(set(self.blockers)) != len(self.blockers):
            raise ValueError("correction_duplicate_blocker")

    @property
    def payload_hash(self) -> str:
        return correction_payload_hash(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectionEvent:
    event_id: UUID
    case_id: UUID
    version: int
    command_id: UUID
    source_id: UUID
    source_hash: str
    actor_id: UUID
    reason: str
    evidence_reference: str
    evidence_hash: str
    recorded_at: datetime
    previous_state_hash: str | None
    result_state: CorrectionState
    result_state_hash: str

    def __post_init__(self) -> None:
        for value in (
            self.event_id,
            self.case_id,
            self.command_id,
            self.source_id,
            self.actor_id,
        ):
            require_uuid(value)
        require_version(self.version)
        for text in (self.reason, self.evidence_reference):
            require_text(text)
        for digest in (
            self.source_hash,
            self.evidence_hash,
            self.result_state_hash,
        ):
            require_hash(digest)
        if self.previous_state_hash is not None:
            require_hash(self.previous_state_hash)
        object.__setattr__(self, "recorded_at", utc(self.recorded_at))
        if (
            not isinstance(self.result_state, CorrectionState)
            or self.result_state.case_id != self.case_id
            or self.result_state.version != self.version
            or self.result_state.source_hash != self.source_hash
            or self.result_state.payload_hash != self.result_state_hash
        ):
            raise ValueError("correction_full_result_invalid")


def replay_correction_events(
    events: tuple[CorrectionEvent, ...],
) -> CorrectionState:
    if type(events) is not tuple or not events:
        raise ValueError("correction_history_unavailable")
    previous: CorrectionState | None = None
    for index, event in enumerate(events, start=1):
        if not isinstance(event, CorrectionEvent):
            raise ValueError("correction_event_invalid")
        event.__post_init__()
        if (
            event.version != index
            or event.previous_state_hash
            != (previous.payload_hash if previous else None)
            or (
                previous is not None
                and (
                    event.case_id != previous.case_id
                    or not set(previous.observation_ids).issubset(
                        event.result_state.observation_ids
                    )
                )
            )
        ):
            raise ValueError("correction_event_chain_invalid")
        previous = event.result_state
    assert previous is not None
    return previous


@dataclass(frozen=True, slots=True, kw_only=True)
class ComponentFunding:
    allocation_key: str
    payment_id: UUID
    paid_item_id: UUID
    component: Component
    currency: str
    gross_minor: int
    cumulative_refund_minor: int
    net_minor: int | None
    unresolved_observation_ids: tuple[UUID, ...] = ()
    unresolved_case_ids: tuple[UUID, ...] = ()
    state_consistent: bool = True

    def __post_init__(self) -> None:
        require_text(self.allocation_key, 256)
        require_uuid(self.payment_id)
        require_uuid(self.paid_item_id)
        require_currency(self.currency)
        require_minor(self.gross_minor)
        require_minor(self.cumulative_refund_minor)
        if self.net_minor is not None:
            require_minor(self.net_minor)
        if (
            self.component not in COMPONENTS
            or type(self.state_consistent) is not bool
            or self.cumulative_refund_minor > self.gross_minor
            or (
                self.state_consistent
                and self.net_minor
                != self.gross_minor - self.cumulative_refund_minor
            )
            or (not self.state_consistent and self.net_minor is not None)
        ):
            raise ValueError("correction_funding_invalid")
        for name in ("unresolved_observation_ids", "unresolved_case_ids"):
            object.__setattr__(self, name, uuid_tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True, kw_only=True)
class CapturedSelectionComponent:
    """Actual allocation and complete historical fulfillment facts."""

    allocation_key: str
    payment_id: UUID
    paid_item_id: UUID
    gross_minor: int
    currency: str
    selection_due_at: datetime | None
    due_evidence_hash: str | None
    assignment_ids: tuple[UUID, ...] = ()
    accepted_delivery_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        require_text(self.allocation_key, 256)
        require_uuid(self.payment_id)
        require_uuid(self.paid_item_id)
        require_minor(self.gross_minor, positive=True)
        require_currency(self.currency)
        if self.selection_due_at is not None:
            object.__setattr__(
                self, "selection_due_at", utc(self.selection_due_at)
            )
        if self.due_evidence_hash is not None:
            require_hash(self.due_evidence_hash)
        for name in ("assignment_ids", "accepted_delivery_ids"):
            object.__setattr__(self, name, uuid_tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionRefundBundle:
    """Full original selected allocations without a caller-selected amount."""

    components: tuple[CapturedSelectionComponent, ...]

    def __post_init__(self) -> None:
        if (
            type(self.components) is not tuple
            or not 1 <= len(self.components) <= 30
            or any(
                not isinstance(c, CapturedSelectionComponent)
                for c in self.components
            )
        ):
            raise ValueError("correction_full_bundle_required")
        if (
            len({c.paid_item_id for c in self.components})
            != len(self.components)
            or len({c.allocation_key for c in self.components})
            != len(self.components)
            or len({c.payment_id for c in self.components}) != 1
        ):
            raise ValueError("correction_bundle_source_invalid")
        require_minor(self.total_minor, positive=True)
        object.__setattr__(
            self,
            "components",
            tuple(sorted(self.components, key=lambda c: c.paid_item_id)),
        )

    @property
    def total_minor(self) -> int:
        return sum(component.gross_minor for component in self.components)

    def positive_a1_refusal(self, as_of: datetime) -> str | None:
        as_of = utc(as_of)
        for component in self.components:
            if (
                component.selection_due_at is None
                or component.due_evidence_hash is None
            ):
                return "selection_due_unavailable"
            if as_of <= component.selection_due_at:
                return "selection_due_not_passed"
            if component.assignment_ids:
                return "selection_previously_assigned"
            if component.accepted_delivery_ids:
                return "selection_already_delivered"
            if component.gross_minor != 50_000:
                return "full_selection_component_required"
        return None
