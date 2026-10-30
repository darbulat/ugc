"""Order event delivery contracts, independent of Telegram and persistence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

OrderNoticeKind = Literal["created", "paid"]


@dataclass(frozen=True)
class OrderNoticeJob:
    job_id: UUID
    order_id: UUID
    event_kind: OrderNoticeKind
    recipient: str
    attempt: int


class OrderNoticeRepository(Protocol):
    async def enqueue(
        self, order_id: UUID, event_kind: OrderNoticeKind, *, session: object
    ) -> None: ...

    async def claim(
        self,
        now: datetime,
        admin_recipients: tuple[str, ...],
        support_recipient: str,
        *,
        session: object,
    ) -> OrderNoticeJob | None: ...

    async def finish(
        self,
        job: OrderNoticeJob,
        state: str,
        reason: str | None,
        *,
        session: object,
        retry_after_seconds: int | None = None,
    ) -> None: ...

    async def begin(
        self, job: OrderNoticeJob, now: datetime, *, session: object
    ) -> bool: ...
