"""Own-only read facts, separate from monetary writers and private cases."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)

PAGE_SIZE = 20
KINDS = ("client_referral", "creator_referral", "management")


@dataclass(frozen=True, slots=True)
class PartnerWaitingParty:
    role: str
    display_name: str | None = None
    telegram_username: str | None = None


@dataclass(frozen=True, slots=True)
class PartnerPendingContext:
    reason: str
    state: str | None = None
    due_at: datetime | None = None
    waiting_for: tuple[PartnerWaitingParty, ...] = ()


@dataclass(frozen=True, slots=True)
class PartnerObligation:
    obligation_id: UUID
    kind: str
    order_id: UUID
    paid_item_id: UUID
    assignment_id: UUID | None
    amount_minor: int
    base_minor: int
    rate_bps: int | None
    rate_source: str
    policy_version: str
    snapshot_at: datetime
    registered_at: datetime | None
    verified_count: int | None
    pending_context: PartnerPendingContext | None = None


@dataclass(frozen=True, slots=True)
class PartnerMovement:
    movement_id: UUID
    movement: JournalMovement


@dataclass(frozen=True, slots=True)
class PartnerFinancialFacts:
    obligations: tuple[PartnerObligation, ...]
    movements: tuple[PartnerMovement, ...]
    projection: dict[str, int] | None


@dataclass(frozen=True, slots=True)
class PartnerReadFacts:
    actor_id: UUID
    account_status: str
    referral_code: str | None
    verified_creators: int
    network_total: int
    network_members: tuple[dict, ...]
    financial: PartnerFinancialFacts | None
    overrides: tuple[dict, ...] | None
    assignments: tuple[dict, ...] | None
    assignment_total: int | None
    is_admin: bool = False


class PartnerViewRepository(Protocol):
    async def read(
        self,
        actor_id: UUID,
        at: datetime,
        *,
        network_page: int,
        assignment_page: int,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> PartnerReadFacts | None: ...
