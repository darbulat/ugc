"""Nonfinancial immutable quota facts and current-policy admission decisions."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from ugc_bot.domain.campaign_moderation import (
    require_digest,
    require_positive_version,
    require_uuid,
)
from ugc_bot.domain.campaigns import LIMIT_NAMES, digest
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True)
class CampaignLimits:
    values: tuple[tuple[str, int], ...]

    def __post_init__(self):
        if type(self.values) is not tuple or tuple(
            name for name, _ in self.values
        ) != tuple(sorted(LIMIT_NAMES)):
            raise ValueError("campaign_all_positive_limits_required")
        for _, value in self.values:
            require_positive_version(value)

    @classmethod
    def from_mapping(cls, values):
        if type(values) is not dict or set(values) != set(LIMIT_NAMES):
            raise ValueError("campaign_all_positive_limits_required")
        return cls(tuple(sorted(values.items())))

    @property
    def payload(self):
        return dict(self.values)

    def __getitem__(self, key: str) -> int:
        return self.payload[key]

    def with_values(self, **changes):
        return CampaignLimits.from_mapping({**self.payload, **changes})


@dataclass(frozen=True, slots=True)
class CampaignWindow:
    start: datetime
    end: datetime

    def __post_init__(self):
        if utc(self.start) >= utc(self.end):
            raise ValueError("campaign_window_invalid")

    @property
    def payload(self):
        return (utc(self.start).isoformat(), utc(self.end).isoformat())


def window_at(at: datetime, window_seconds: int) -> CampaignWindow:
    require_positive_version(window_seconds)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    width = timedelta(seconds=window_seconds)
    start = epoch + ((utc(at) - epoch) // width) * width
    return CampaignWindow(start, start + width)


@dataclass(frozen=True, slots=True)
class CampaignRecipientScope:
    creator_id: UUID
    canonical_identity: str
    destination: str

    def __post_init__(self):
        require_uuid(self.creator_id)
        if (
            not isinstance(self.canonical_identity, str)
            or not self.canonical_identity.strip()
            or self.canonical_identity != self.canonical_identity.strip()
            or not isinstance(self.destination, str)
            or not self.destination.isascii()
            or not self.destination.isdigit()
            or int(self.destination) < 1
            or str(int(self.destination)) != self.destination
        ):
            raise ValueError("campaign_recipient_scope_invalid")

    @property
    def keys(self):
        return (
            ("creator", str(self.creator_id)),
            ("identity", self.canonical_identity),
            ("destination", self.destination),
        )

    @property
    def payload(self):
        return self.keys


@dataclass(frozen=True, slots=True)
class CampaignUsage:
    event_id: UUID
    kind: Literal["submission", "attempt_started"]
    owner_id: UUID
    occurred_at: datetime
    recipient: CampaignRecipientScope | None = None

    def __post_init__(self):
        require_uuid(self.event_id)
        require_uuid(self.owner_id)
        utc(self.occurred_at)
        if self.kind not in ("submission", "attempt_started") or (
            (self.kind == "attempt_started")
            != isinstance(self.recipient, CampaignRecipientScope)
        ):
            raise ValueError("campaign_usage_invalid")


@dataclass(frozen=True, slots=True)
class CampaignReservation:
    reservation_id: UUID
    job_id: UUID
    campaign_id: UUID
    owner_id: UUID
    recipient: CampaignRecipientScope
    window: CampaignWindow
    expires_at: datetime
    status: Literal["reserved", "released", "consumed"] = "reserved"

    def __post_init__(self):
        for identifier in (
            self.reservation_id,
            self.job_id,
            self.campaign_id,
            self.owner_id,
        ):
            require_uuid(identifier)
        if (
            not isinstance(self.recipient, CampaignRecipientScope)
            or not isinstance(self.window, CampaignWindow)
            or not self.window.start < utc(self.expires_at) <= self.window.end
            or self.status not in ("reserved", "released", "consumed")
        ):
            raise ValueError("campaign_reservation_invalid")


@dataclass(frozen=True, slots=True)
class CampaignOccupation:
    campaign_id: UUID
    owner_id: UUID
    deadline: datetime

    def __post_init__(self):
        require_uuid(self.campaign_id)
        require_uuid(self.owner_id)
        utc(self.deadline)


def _typed_tuple(values, cls):
    if type(values) is not tuple or any(
        not isinstance(value, cls) for value in values
    ):
        raise ValueError("campaign_immutable_capacity_facts_required")


@dataclass(frozen=True, slots=True)
class CampaignCapacityFacts:
    usage: tuple[CampaignUsage, ...]
    reservations: tuple[CampaignReservation, ...]
    occupations: tuple[CampaignOccupation, ...]

    def __post_init__(self):
        for values, cls in (
            (self.usage, CampaignUsage),
            (self.reservations, CampaignReservation),
            (self.occupations, CampaignOccupation),
        ):
            _typed_tuple(values, cls)


@dataclass(frozen=True, slots=True)
class CampaignReservationRelease:
    reservation_id: UUID
    at: datetime
    reason: str

    def __post_init__(self):
        require_uuid(self.reservation_id)
        utc(self.at)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("campaign_release_reason_required")


@dataclass(frozen=True, slots=True)
class CampaignOccupationClose:
    campaign_id: UUID
    at: datetime
    reason: str

    def __post_init__(self):
        require_uuid(self.campaign_id)
        utc(self.at)
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("campaign_release_reason_required")


@dataclass(frozen=True, slots=True)
class CampaignCapacityDelta:
    usage: tuple[CampaignUsage, ...] = ()
    reservations: tuple[CampaignReservation, ...] = ()
    releases: tuple[CampaignReservationRelease, ...] = ()
    opened: tuple[CampaignOccupation, ...] = ()
    closed: tuple[CampaignOccupationClose, ...] = ()

    def __post_init__(self):
        for values, cls in (
            (self.usage, CampaignUsage),
            (self.reservations, CampaignReservation),
            (self.releases, CampaignReservationRelease),
            (self.opened, CampaignOccupation),
            (self.closed, CampaignOccupationClose),
        ):
            _typed_tuple(values, cls)

    def plus(self, other: "CampaignCapacityDelta") -> "CampaignCapacityDelta":
        return CampaignCapacityDelta(
            *(
                getattr(self, name) + getattr(other, name)
                for name in (
                    "usage",
                    "reservations",
                    "releases",
                    "opened",
                    "closed",
                )
            )
        )


def _unique(values, attribute):
    result = {}
    for value in values:
        key = getattr(value, attribute)
        if key in result and result[key] != value:
            raise ValueError("campaign_capacity_integrity_unavailable")
        result[key] = value
    return tuple(result.values())


def apply_capacity_delta(
    facts: CampaignCapacityFacts, delta: CampaignCapacityDelta
) -> CampaignCapacityFacts:
    """Pure intended-state calculation; this performs no persistence."""
    releases = {row.reservation_id for row in delta.releases}
    closed = {row.campaign_id for row in delta.closed}
    reservations = tuple(
        replace(row, status="released")
        if row.reservation_id in releases and row.status == "reserved"
        else row
        for row in facts.reservations
    )
    opened = {
        row.campaign_id: row
        for row in facts.occupations
        if row.campaign_id not in closed
    }
    opened.update({row.campaign_id: row for row in delta.opened})
    return CampaignCapacityFacts(
        _unique(facts.usage + delta.usage, "event_id"),
        _unique(reservations + delta.reservations, "reservation_id"),
        tuple(opened.values()),
    )


@dataclass(frozen=True, slots=True)
class CampaignCapacityObservation:
    window: CampaignWindow
    summary: tuple[tuple[str, int], ...]
    reasons: tuple[str, ...]
    blocked_recipients: tuple[UUID, ...]
    evidence_digest: str
    observed_at: datetime

    def __post_init__(self):
        require_digest(self.evidence_digest)
        if (
            not isinstance(self.window, CampaignWindow)
            or type(self.summary) is not tuple
            or any(
                type(row) is not tuple
                or len(row) != 2
                or not isinstance(row[0], str)
                or type(row[1]) is not int
                or row[1] < 0
                for row in self.summary
            )
            or type(self.reasons) is not tuple
            or any(
                not isinstance(value, str) or not value
                for value in self.reasons
            )
            or type(self.blocked_recipients) is not tuple
            or not self.window.start <= utc(self.observed_at) < self.window.end
        ):
            raise ValueError("campaign_capacity_observation_invalid")
        for identifier in self.blocked_recipients:
            require_uuid(identifier)

    @property
    def digest(self):
        return digest(
            {
                "window": self.window.payload,
                "summary": self.summary,
                "reasons": self.reasons,
                "blocked": tuple(map(str, self.blocked_recipients)),
                "evidence": self.evidence_digest,
            }
        )

    @property
    def safe(self):
        return {
            **dict(self.summary),
            "window_start": self.window.payload[0],
            "window_end": self.window.payload[1],
            "reasons": list(self.reasons),
        }


def evaluate_capacity(
    facts: CampaignCapacityFacts,
    *,
    limits: CampaignLimits,
    owner_id: UUID,
    recipients: tuple[CampaignRecipientScope, ...],
    at: datetime,
    intent: Literal["submit", "approve", "observe"],
) -> CampaignCapacityObservation:
    require_uuid(owner_id)
    _typed_tuple(recipients, CampaignRecipientScope)
    at = utc(at)
    if intent not in ("submit", "approve", "observe"):
        raise ValueError("campaign_capacity_intent_invalid")
    window = window_at(at, limits["window_seconds"])
    usage = _unique(facts.usage, "event_id")
    reservations = tuple(
        row
        for row in _unique(facts.reservations, "reservation_id")
        if row.status == "reserved"
    )
    occupations = _unique(facts.occupations, "campaign_id")
    if any(row.occurred_at > at for row in usage):
        raise ValueError("campaign_capacity_integrity_unavailable")
    current = tuple(
        row for row in usage if window.start <= row.occurred_at < window.end
    )
    starts = tuple(row for row in current if row.kind == "attempt_started")
    owner_starts = sum(row.owner_id == owner_id for row in starts)
    owner_reserved = sum(row.owner_id == owner_id for row in reservations)
    submissions = sum(
        row.kind == "submission" and row.owner_id == owner_id for row in current
    )
    active = sum(row.owner_id == owner_id for row in occupations)
    summary = tuple(
        sorted(
            {
                "submissions_used": submissions,
                "active_used": active,
                "owner_starts_used": owner_starts,
                "global_starts_used": len(starts),
                "owner_reserved": owner_reserved,
                "global_reserved": len(reservations),
                "requested": len(recipients),
            }.items()
        )
    )
    reasons = []
    if any(row.expires_at <= at for row in reservations) or any(
        row.deadline <= at for row in occupations
    ):
        reasons.append("settlement_required")
    if len(recipients) > limits["recipients_per_campaign"]:
        reasons.append("recipients_per_campaign")
    reasons.extend(_admission_reasons(intent, limits, dict(summary)))
    all_starts = tuple(row for row in usage if row.kind == "attempt_started")
    blocked = _blocked_recipients(
        recipients, starts, all_starts, reservations, limits, at
    )
    if intent == "approve" and blocked:
        reasons.append("recipient_capacity")
    evidence = digest(
        {
            "usage": sorted(
                (
                    str(row.event_id),
                    row.kind,
                    str(row.owner_id),
                    utc(row.occurred_at).isoformat(),
                    row.recipient.payload if row.recipient else None,
                )
                for row in usage
            ),
            "reservations": sorted(
                (
                    str(row.reservation_id),
                    str(row.owner_id),
                    row.recipient.payload,
                    row.window.payload,
                    utc(row.expires_at).isoformat(),
                )
                for row in reservations
            ),
            "occupations": sorted(
                (
                    str(row.campaign_id),
                    str(row.owner_id),
                    utc(row.deadline).isoformat(),
                )
                for row in occupations
            ),
            "limits": limits.payload,
        }
    )
    return CampaignCapacityObservation(
        window, summary, tuple(reasons), tuple(blocked), evidence, at
    )


def _admission_reasons(intent, limits, used):
    reasons = []
    if intent == "submit":
        if used["submissions_used"] + 1 > limits["submissions_per_owner"]:
            reasons.append("submissions_per_owner")
        if used["active_used"] + 1 > limits["active_per_owner"]:
            reasons.append("active_per_owner")
    if intent == "approve":
        if (
            used["owner_starts_used"]
            + used["owner_reserved"]
            + used["requested"]
            > limits["attempts_per_owner"]
        ):
            reasons.append("owner_attempts")
        if (
            used["global_starts_used"]
            + used["global_reserved"]
            + used["requested"]
            > limits["attempts_global"]
        ):
            reasons.append("global_attempts")
    return reasons


def _blocked_recipients(
    recipients, starts, all_starts, reservations, limits, at
):
    blocked = []
    for recipient in recipients:
        keys = set(recipient.keys)
        over_limit = any(
            sum(
                row.recipient is not None and key in row.recipient.keys
                for row in starts
            )
            + sum(key in row.recipient.keys for row in reservations)
            + 1
            > limits["attempts_per_recipient"]
            for key in keys
        )
        claimed = any(
            keys.intersection(row.recipient.keys) for row in reservations
        )
        cooling = any(
            row.recipient
            and keys.intersection(row.recipient.keys)
            and at - row.occurred_at
            < timedelta(seconds=limits["recipient_cooldown_seconds"])
            for row in all_starts
        )
        if over_limit or claimed or cooling:
            blocked.append(recipient.creator_id)
    return tuple(blocked)
