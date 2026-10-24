"""Immutable identity observations and truthful historical grade inputs."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware_timestamp_required")
    return value.astimezone(timezone.utc)


class IdentityHistoryUnavailable(ValueError):
    """Coverage is insufficient to claim a historical verified count."""


@dataclass(frozen=True, slots=True)
class IdentityObservation:
    sequence: int
    creator_user_id: UUID
    instagram_user_id: str | None
    active: bool
    observed_at: datetime
    fact_at: datetime | None
    source: str
    business_key: str


@dataclass(frozen=True, slots=True)
class DirectBindingObservation:
    sequence: int
    referrer_user_id: UUID
    referred_user_id: UUID
    active: bool
    created_at: datetime
    observed_at: datetime
    source: str
    business_key: str
    registered_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IdentityHistoryCoverage:
    covered_from: datetime
    complete: bool
    version: str = "creator_identity_history_v1"


@dataclass(frozen=True, slots=True)
class IdentityCountInputs:
    coverage: IdentityHistoryCoverage | None
    checked_at: datetime
    identities: tuple[IdentityObservation, ...]
    bindings: tuple[DirectBindingObservation, ...]


@dataclass(frozen=True, slots=True)
class HistoricalBindingInputs:
    coverage: IdentityHistoryCoverage | None
    checked_at: datetime
    binding: DirectBindingObservation | None


@dataclass(frozen=True, slots=True)
class HistoricalDirectAttribution:
    referred_user_id: UUID
    referrer_user_id: UUID | None
    as_of: datetime
    registered_at: datetime | None
    binding_created_at: datetime | None
    binding_effective_at: datetime | None
    observation_sequence: int | None
    reason: str | None
    covered_from: datetime
    observed_through: datetime
    coverage_version: str


@dataclass(frozen=True, slots=True)
class VerifiedCreatorCount:
    partner_user_id: UUID
    as_of: datetime
    verified_count: int
    covered_from: datetime
    observed_through: datetime
    identity_watermark: int
    binding_watermark: int
    coverage_version: str
