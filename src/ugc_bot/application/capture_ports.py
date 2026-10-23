"""Trusted capture boundary, deliberately unavailable to frontend callers."""

from decimal import Decimal
from typing import Protocol
from uuid import UUID

from ugc_bot.application.messenger.dto import PaymentSuccess
from ugc_bot.domain.entities import Payment


class FinancialCaptureRepository(Protocol):
    async def lock_order(self, order_id: UUID, *, session: object) -> None: ...

    async def issue(
        self, order_id: UUID, client_id: UUID, account: str, *, session: object
    ) -> tuple[Decimal, str]: ...

    async def capture(
        self,
        order_id: UUID,
        client_id: UUID,
        account: str,
        receipt: PaymentSuccess,
        *,
        session: object,
    ) -> Payment: ...
