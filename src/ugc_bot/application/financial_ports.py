"""Typed financial contracts with opaque caller-owned sessions."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
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
