"""Atomic intake persistence; notification delivery has its own transaction."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.domain.order_intake import (
    AccompanimentLead,
    IntakeClient,
    OrderIntakeReceipt,
)


class OrderIntakeRepository(Protocol):
    async def policy_versions(
        self, at: datetime, *, session: object
    ) -> tuple[str, ...]: ...

    async def lock_client(
        self, client_id: UUID, *, session: object
    ) -> IntakeClient | None: ...

    async def lock_operation(
        self, client_id: UUID, operation_key: str, *, session: object
    ) -> None: ...

    async def get_receipt(
        self, client_id: UUID, operation_key: str, *, session: object
    ) -> OrderIntakeReceipt | None: ...

    async def save(
        self,
        receipt: OrderIntakeReceipt,
        lead: AccompanimentLead | None,
        *,
        session: object,
    ) -> None: ...
