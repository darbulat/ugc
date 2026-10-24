"""Confirmed selection interest and durable delivery, separate from work."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SelectionInterest:
    interest_id: UUID
    order_id: UUID
    creator_id: UUID
    client_id: UUID
    confirmed_at: datetime
    instagram_user_id: str
    instagram_url: str
    accepted: bool
    paid_item_id: UUID | None
    assignment_id: UUID | None
    job_id: UUID | None
    manager_id: UUID | None
    delivery_state: str


class PaidSelectionRepository(Protocol):
    async def count_accepted(
        self, order_id: UUID, *, session: object
    ) -> int: ...

    async def discover(
        self, order_id: UUID, *, session: object
    ) -> tuple[UUID, ...] | None: ...

    async def lock_users(
        self, users: tuple[UUID, ...], *, session: object
    ) -> None: ...

    async def confirm(
        self,
        order_id: UUID,
        creator_id: UUID,
        locked_users: tuple[UUID, ...],
        now: Callable[[], datetime],
        *,
        session: object,
    ) -> SelectionInterest: ...
