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
    async def exact_city_for_order(
        self, order_id: UUID, *, session: object, for_update: bool = False
    ) -> str | None: ...

    async def filter_candidates(
        self, order_id: UUID, creator_ids: list[UUID], *, session: object
    ) -> list[UUID]: ...

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

    async def record_funnel(
        self,
        client_id: UUID,
        funnel_id: UUID,
        stage: str,
        at: datetime,
        *,
        order_id: UUID | None = None,
        session: object,
    ) -> None: ...

    async def funnel_report(self, *, session: object) -> dict: ...
