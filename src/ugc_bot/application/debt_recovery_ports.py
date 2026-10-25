"""Actual incoming repayment evidence and a separate recovery decision."""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.domain.corrections import (
    require_hash,
    require_minor,
    require_text,
    require_uuid,
)
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True, kw_only=True)
class RecordDebtRepayment:
    actor_id: UUID
    operation_key: str
    recipient_id: UUID
    case_id: UUID
    amount_minor: int
    currency: str
    bank_account_label: str
    bank_reference: str
    occurred_at: datetime
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        for value in (self.actor_id, self.recipient_id, self.case_id):
            require_uuid(value)
        for value in (
            self.operation_key,
            self.bank_account_label,
            self.bank_reference,
            self.reason,
            self.evidence_reference,
        ):
            require_text(value)
        require_hash(self.evidence_hash)
        require_minor(self.amount_minor, positive=True)
        if self.currency != "RUB":
            raise ValueError("unpublished_currency")
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplyDebtRecovery:
    """Review total case debt; business_key identifies a case member."""

    actor_id: UUID
    operation_key: str
    observation_id: UUID
    business_key: str
    case_id: UUID
    expected_debt_minor: int
    reason: str
    evidence_reference: str
    evidence_hash: str

    def __post_init__(self):
        for value in (self.actor_id, self.observation_id, self.case_id):
            require_uuid(value)
        for value in (
            self.operation_key,
            self.business_key,
            self.reason,
            self.evidence_reference,
        ):
            require_text(value)
        require_hash(self.evidence_hash)
        require_minor(self.expected_debt_minor, positive=True)


class DebtRecoveryRepository(Protocol):
    async def actor(self, actor_id: UUID, *, session: object): ...
    async def lock_operation(
        self, actor_id: UUID, operation_key: str, *, session: object
    ) -> None: ...
    async def command(
        self, actor_id: UUID, operation_key: str, *, session: object
    ) -> dict | None: ...
    async def observation(
        self, observation_id: UUID, *, session: object
    ) -> dict | None: ...
    async def application(
        self, observation_id: UUID, *, session: object
    ) -> dict | None: ...
    async def case_grounds(
        self,
        case_id: UUID,
        recipient_id: UUID,
        currency: str,
        *,
        session: object,
    ) -> tuple[str, ...]: ...

    async def append_observation(
        self, value: dict, *, session: object
    ) -> None: ...
    async def append_application(
        self, value: dict, *, session: object
    ) -> None: ...
    async def save_command(self, value: dict, *, session: object) -> None: ...

    async def cases(
        self, *, limit: int, offset: int, session: object
    ) -> list[dict]: ...

    async def observations(
        self, *, limit: int, offset: int, session: object
    ) -> list[dict]: ...
