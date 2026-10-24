"""Typed financial contracts with opaque caller-owned sessions."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from ugc_bot.domain.financial import MAX_MINOR, utc

Bucket = Literal[
    "pending", "hold", "available", "reserved", "paid", "cancelled", "blocked"
]
MovementType = Literal["issuance", "transfer", "reversal", "debt", "recovery"]


@dataclass(frozen=True, slots=True, kw_only=True)
class JournalMovement:
    obligation_id: UUID
    operation_key: str
    event_id: str
    movement_type: MovementType
    amount_minor: int
    currency: str
    effective_at: datetime
    recorded_at: datetime
    actor_id: UUID | None
    reason: str
    actor_kind: Literal["user", "admin", "system"] = "user"
    system_actor: str | None = None
    bucket_from: Bucket | None = None
    bucket_to: Bucket | None = None
    source_entry_id: UUID | None = None
    request_id: UUID | None = None
    allocation_id: UUID | None = None
    execution_id: UUID | None = None
    refund_id: UUID | None = None
    case_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            type(self.amount_minor) is not int
            or not 0 < self.amount_minor <= MAX_MINOR
        ):
            raise ValueError("positive_minor_amount_required")
        if self.currency != "RUB":
            raise ValueError("unpublished_currency")
        self._validate_actor()
        object.__setattr__(self, "effective_at", utc(self.effective_at))
        object.__setattr__(self, "recorded_at", utc(self.recorded_at))
        if not all(
            isinstance(value, str) and value.strip()
            for value in (self.operation_key, self.event_id, self.reason)
        ):
            raise ValueError("journal_provenance_required")
        self._validate_references()
        self._validate_movement()

    def _validate_actor(self) -> None:
        if self.actor_kind == "system":
            if (
                self.actor_id is not None
                or not isinstance(self.system_actor, str)
                or not self.system_actor.strip()
            ):
                raise ValueError("journal_actor_ambiguous")
            object.__setattr__(self, "system_actor", self.system_actor.strip())
        elif self.actor_kind in ("user", "admin"):
            if not isinstance(self.actor_id, UUID) or self.actor_id.int == 0:
                raise ValueError("journal_actor_required")
            if self.system_actor is not None:
                raise ValueError("journal_actor_ambiguous")
        else:
            raise ValueError("journal_actor_kind_invalid")

    def _validate_references(self) -> None:
        if (
            not isinstance(self.obligation_id, UUID)
            or self.obligation_id.int == 0
        ):
            raise ValueError("journal_reference_required")
        for reference in (
            self.source_entry_id,
            self.request_id,
            self.allocation_id,
            self.execution_id,
            self.refund_id,
            self.case_id,
        ):
            if reference is not None and (
                not isinstance(reference, UUID) or reference.int == 0
            ):
                raise ValueError("journal_reference_invalid")

    def _validate_movement(self) -> None:
        if self.movement_type not in (
            "issuance",
            "transfer",
            "reversal",
            "debt",
            "recovery",
        ):
            raise ValueError("invalid_movement_type")
        buckets = (
            "pending",
            "hold",
            "available",
            "reserved",
            "paid",
            "cancelled",
            "blocked",
            None,
        )
        if self.bucket_from not in buckets or self.bucket_to not in buckets:
            raise ValueError("invalid_bucket")
        if (
            self.movement_type in ("reversal", "debt", "recovery")
            and self.source_entry_id is None
        ):
            raise ValueError("correction_source_required")
        if self.movement_type in ("debt", "recovery") and self.case_id is None:
            raise ValueError("recovery_case_required")
        if self.movement_type == "issuance" and (
            self.bucket_from is not None or self.bucket_to != "pending"
        ):
            raise ValueError("issuance_pending_required")
        if self.movement_type == "transfer":
            self._validate_transfer()

    def _validate_transfer(self) -> None:
        if self.bucket_from == "paid":
            raise ValueError("historical_paid_immutable")
        if "cancelled" in (self.bucket_from, self.bucket_to):
            raise ValueError("economic_cancellation_requires_correction")
        if self.bucket_to == "paid" and (
            self.execution_id is None
            or self.request_id is None
            or self.allocation_id is None
        ):
            raise ValueError("paid_execution_required")
        if (
            self.bucket_from is None
            or self.bucket_to is None
            or self.bucket_from == self.bucket_to
        ):
            raise ValueError("transfer_buckets_required")
        if "reserved" in (self.bucket_from, self.bucket_to) and (
            self.request_id is None or self.allocation_id is None
        ):
            raise ValueError("reservation_references_required")


class FinancialTransactionManager(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[object]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class JournalRepository(Protocol):
    async def append(
        self, movement: JournalMovement, *, session: object
    ) -> JournalMovement:
        """Idempotent by operation key and canonical economic payload."""
        ...

    async def list_for_recipient(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> tuple[JournalMovement, ...]: ...


class FinancialLocks(Protocol):
    async def lock_recipients(
        self, recipient_ids: tuple[UUID, ...], *, session: object
    ) -> None:
        """Sorted exclusive user-row mutexes shared with every legacy writer."""
        ...

    async def lock_wallets(
        self, keys: tuple[tuple[UUID, str], ...], *, session: object
    ) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class IssueBasis:
    """Already assessed referral or fixed-fee basis; caller authorizes it.

    For management, base_minor is the assessed manager reward (not the
    customer's accompaniment price), referred_user_id identifies its creator
    subject, and registration/rate/grade are N/A.
    This DTO does not establish paid funding or manager entitlement itself.
    """

    business_key: str
    kind: Literal["client_referral", "creator_referral", "management"]
    recipient_id: UUID | None
    paid_item_id: UUID
    order_id: UUID
    assignment_id: UUID | None
    referred_user_id: UUID
    payment_id: UUID
    currency: str
    base_minor: int
    rate_bps: int | None
    policy_version: str | None
    snapshot_at: datetime
    registered_at: datetime | None
    # None is an explicit not-applicable grade for CLIENT, never a measured 0.
    verified_count: int | None
    event_id: str
    reason: str
    actor_id: UUID | None
    available_at: datetime | None = None
    rate_source: Literal["standard", "override"] = "standard"
    override_id: UUID | None = None
    actor_kind: Literal["user", "admin", "system"] = "user"
    system_actor: str | None = None

    def __post_init__(self) -> None:
        for name in ("snapshot_at", "registered_at"):
            if (
                name == "registered_at"
                and self.registered_at is None
                and (
                    self.kind == "management"
                    or self.recipient_id is None
                    or self.rate_bps is None
                    or self.policy_version is None
                )
            ):
                continue
            object.__setattr__(self, name, utc(getattr(self, name)))
        if self.available_at is not None:
            object.__setattr__(self, "available_at", utc(self.available_at))
            if self.available_at < self.snapshot_at:
                raise ValueError("availability_before_snapshot")
        if (
            not self.business_key.strip()
            or not self.event_id.strip()
            or not self.reason.strip()
        ):
            raise ValueError("basis_provenance_required")
        self._validate_scope()
        self._validate_values()
        self._validate_actor()
        if self.rate_source not in ("standard", "override"):
            raise ValueError("invalid_rate_provenance")
        if (self.rate_source == "override") != (self.override_id is not None):
            raise ValueError("override_reference_required")
        if self.kind == "management" and self.rate_source != "standard":
            raise ValueError("management_override_not_applicable")

    def _validate_actor(self) -> None:
        if self.actor_kind == "system":
            if (
                self.actor_id is not None
                or not isinstance(self.system_actor, str)
                or not self.system_actor.strip()
            ):
                raise ValueError("basis_actor_provenance_required")
            object.__setattr__(self, "system_actor", self.system_actor.strip())
        elif self.actor_kind not in ("user", "admin") or (
            self.actor_id is None or self.system_actor is not None
        ):
            raise ValueError("basis_actor_provenance_required")

    def _validate_values(self) -> None:
        if self.kind == "management" and any(
            value is not None
            for value in (
                self.registered_at,
                self.verified_count,
                self.rate_bps,
            )
        ):
            raise ValueError("management_referral_fields_not_applicable")
        if self.kind not in (
            "client_referral",
            "creator_referral",
            "management",
        ):
            raise ValueError("invalid_referral_kind")
        if self.kind == "creator_referral" and self.assignment_id is None:
            raise ValueError("creator_assignment_required")
        if self.kind == "management" and self.assignment_id is None:
            raise ValueError("management_assignment_required")
        if self.currency != "RUB":
            raise ValueError("unpublished_currency")
        if (
            type(self.base_minor) is not int
            or not 0 < self.base_minor <= MAX_MINOR
        ):
            raise ValueError("positive_base_required")
        count_unknown = self.verified_count is None and (
            self.kind in ("client_referral", "management")
            or (self.kind == "creator_referral" and self.rate_bps is None)
        )
        if not count_unknown and (
            type(self.verified_count) is not int or self.verified_count < 0
        ):
            raise ValueError("invalid_verified_count")
        if self.policy_version is not None and not self.policy_version.strip():
            raise ValueError("invalid_policy_version")

    def _validate_scope(self) -> None:
        for ref in (
            self.recipient_id,
            self.paid_item_id,
            self.order_id,
            self.assignment_id,
            self.referred_user_id,
            self.payment_id,
            self.actor_id,
            self.override_id,
        ):
            if ref is not None and (not isinstance(ref, UUID) or ref.int == 0):
                raise ValueError("invalid_basis_reference")


@dataclass(frozen=True, slots=True)
class IssuedObligation:
    obligation_id: UUID
    snapshot_id: UUID
    basis: IssueBasis
    movement: JournalMovement


@dataclass(frozen=True, slots=True)
class PotentialBasis:
    """Durable non-monetary assessment, stored as an immutable audit event."""

    basis: IssueBasis
    reason: str
    recorded_at: datetime
    assessment_id: UUID


@dataclass(frozen=True, slots=True)
class ObligationBasis:
    """Persisted monetary basis, independent of journal coverage."""

    obligation_id: UUID
    recipient_id: UUID
    currency: str
    amount_minor: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovedRateOverride:
    """Immutable server approval loaded by the policy repository."""

    override_id: UUID
    recipient_id: UUID
    side: Literal["client", "creator"]
    rate_bps: int
    policy_version: str
    effective_from: datetime
    effective_until: datetime
    approved_by: UUID
    approved_at: datetime
    reason: str

    def __post_init__(self):
        for name in ("effective_from", "effective_until", "approved_at"):
            object.__setattr__(self, name, utc(getattr(self, name)))
        if any(
            not isinstance(x, UUID) or x.int == 0
            for x in (self.override_id, self.recipient_id, self.approved_by)
        ):
            raise ValueError("override_identity_required")
        if (
            self.side not in ("client", "creator")
            or type(self.rate_bps) is not int
            or not 0 < self.rate_bps <= 10000
        ):
            raise ValueError("invalid_override_rate")
        if (
            self.effective_until <= self.effective_from
            or self.approved_at > self.effective_from
        ):
            raise ValueError("invalid_override_period")
        if not self.reason.strip() or not self.policy_version.strip():
            raise ValueError("override_provenance_required")

    def applies(self, basis: IssueBasis) -> bool:
        return (
            self.recipient_id == basis.recipient_id
            and self.policy_version == basis.policy_version
            and self.side
            == ("client" if basis.kind == "client_referral" else "creator")
            and self.rate_bps == basis.rate_bps
            and self.effective_from <= basis.snapshot_at < self.effective_until
            and self.approved_at <= basis.snapshot_at
        )


@dataclass(frozen=True, slots=True)
class ActiveEconomicGround:
    obligation_id: UUID
    business_key: str
    recipient_id: UUID
    currency: str
    paid_item_id: UUID
    kind: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkMaturitySource:
    source_id: UUID
    source_event_id: UUID
    assignment_id: UUID
    paid_item_id: UUID
    order_id: UUID
    policy_version: str
    creator_id: UUID
    manager_id: UUID | None
    state: str
    assignment_ended_at: datetime | None
    success_final_at: datetime
    release_at: datetime

    def __post_init__(self):
        for name in ("success_final_at", "release_at", "assignment_ended_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, utc(value))
        if self.release_at != self.success_final_at + timedelta(days=14):
            raise ValueError("invalid_work_maturity_schedule")

    def require_for(self, basis: IssueBasis) -> None:
        if (
            self.state not in ("success_final", "available")
            or self.assignment_ended_at is not None
            or self.assignment_id != basis.assignment_id
            or self.paid_item_id != basis.paid_item_id
            or self.order_id != basis.order_id
            or self.policy_version != basis.policy_version
            or self.creator_id != basis.referred_user_id
            or basis.kind not in ("creator_referral", "management")
            or (
                basis.kind == "management"
                and self.manager_id != basis.recipient_id
            )
        ):
            raise ValueError("maturity_source_not_eligible")


@dataclass(frozen=True, slots=True)
class ObligationMaturity:
    maturity_id: UUID
    obligation_id: UUID
    source_id: UUID
    assignment_id: UUID
    paid_item_id: UUID
    success_final_at: datetime
    release_at: datetime
    producer: str
    recorded_at: datetime


class LedgerRepository(JournalRepository, FinancialLocks, Protocol):
    async def get_rate_override(
        self,
        override_id: UUID,
        *,
        as_of: datetime | None = None,
        session: object,
    ) -> ApprovedRateOverride | None:
        """Server approval effective at capture, including revocation facts."""
        ...

    async def list_item_grounds(
        self, item_id: UUID, kind: str, *, session: object
    ) -> tuple[ActiveEconomicGround, ...]:
        """All immutable historical obligations, independent of projections."""
        ...

    async def get_active_ground(
        self, item_id: UUID, kind: str, *, session: object
    ) -> ActiveEconomicGround | None: ...

    async def set_active_ground(
        self, record: IssuedObligation, *, session: object
    ) -> None: ...

    async def get_entry_ref(
        self, operation_key: str, *, session: object
    ) -> UUID | None: ...

    async def load_maturity_source(
        self, source_id: UUID, *, session: object
    ) -> WorkMaturitySource | None: ...

    async def get_maturity(
        self, obligation_id: UUID, *, session: object
    ) -> ObligationMaturity | None: ...

    async def save_maturity(
        self, fact: ObligationMaturity, *, session: object
    ) -> ObligationMaturity: ...
    async def list_obligation_bases(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> tuple[ObligationBasis, ...]: ...

    async def save_potential(
        self,
        basis: IssueBasis,
        reason: str,
        *,
        recorded_at: datetime,
        session: object,
    ) -> PotentialBasis: ...

    async def lock_item(self, item_id: UUID, *, session: object) -> None: ...

    async def get_issue(
        self, key: str, *, session: object
    ) -> IssuedObligation | None: ...

    async def save_issue(
        self, record: IssuedObligation, *, session: object
    ) -> IssuedObligation: ...

    async def apply_projection(
        self, movement: JournalMovement, *, session: object
    ) -> None: ...

    async def read_projection(
        self, recipient_id: UUID, currency: str, *, session: object
    ) -> dict[str, int]: ...
