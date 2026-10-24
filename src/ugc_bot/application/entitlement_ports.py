"""Server-owned capture inputs and durable client assessment receipts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from ugc_bot.application.financial_ports import ApprovedRateOverride
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.domain.entities import OutboxEvent


@dataclass(frozen=True, slots=True)
class FundedSelection:
    paid_item_id: UUID
    selection_minor: int
    accompaniment_minor: int


@dataclass(frozen=True, slots=True)
class ClientCapture:
    event_id: UUID
    order_id: UUID
    payment_id: UUID
    client_id: UUID
    policy: FinancialPolicy
    captured_at: datetime
    registered_at: datetime | None
    captured_referrer_id: UUID | None
    items: tuple[FundedSelection, ...]
    source_hash: str


class ClientEntitlementRepository(Protocol):
    async def source_hash(
        self, event: OutboxEvent, *, session: object
    ) -> str: ...

    async def load_capture(
        self, event: OutboxEvent, *, session: object
    ) -> ClientCapture: ...

    async def lock_funding(
        self, capture: ClientCapture, *, session: object
    ) -> None: ...

    async def get_receipt(
        self, event_id: UUID, *, session: object
    ) -> dict[str, Any] | None: ...

    async def save_receipt(
        self,
        capture: ClientCapture,
        assessment: dict[str, Any],
        *,
        recorded_at: datetime,
        session: object,
    ) -> None: ...


class EffectiveRateOverrides(Protocol):
    async def select_effective_override(
        self,
        recipient_id: UUID,
        side: Literal["client", "creator"],
        policy_version: str,
        as_of: datetime,
        *,
        session: object,
    ) -> ApprovedRateOverride | None: ...
