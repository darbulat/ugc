"""Persistence boundary for operational customer workflows.

independent of money."""

from datetime import datetime
from typing import Protocol
from uuid import UUID


class CustomerWorkflowRepository(Protocol):
    async def actor(self, user_id: UUID, *, session: object) -> dict: ...
    async def owns_order(
        self, user_id: UUID, order_id: UUID, *, session: object
    ) -> bool: ...
    async def order_created_at(
        self, user_id: UUID, order_id: UUID, *, session: object
    ) -> datetime | None: ...
    async def blogger_on_order(
        self, blogger_id: UUID, order_id: UUID, *, session: object
    ) -> bool: ...
    async def request(
        self, user_id: UUID, kind: str, key: str, *, session: object
    ) -> dict | None: ...
    async def save_request(self, values: dict, *, session: object) -> None: ...
    async def requests(
        self, user_id: UUID, order_id: UUID, *, session: object
    ) -> list[dict]: ...
    async def support_status(
        self, request_id: UUID, state: str, *, session: object
    ) -> None: ...
    async def series(
        self, user_id: UUID, *, session: object
    ) -> dict | None: ...
    async def has_older_paid_series(
        self, user_id: UUID, since: datetime, *, session: object
    ) -> bool: ...
    async def intent_opened_at(
        self, user_id: UUID, intent_id: UUID, *, session: object
    ) -> datetime | None: ...
    async def intent_series(
        self, user_id: UUID, intent_id: UUID, *, session: object
    ) -> UUID | None: ...
    async def intent_order(
        self, user_id: UUID, intent_id: UUID, *, session: object
    ) -> UUID | None: ...
    async def bind_intent(
        self,
        user_id: UUID,
        intent_id: UUID,
        series_id: UUID,
        at: datetime,
        *,
        session: object,
    ) -> None: ...
    async def next_followup(
        self, series_id: UUID, *, session: object
    ) -> dict | None: ...
    async def has_relevant_payment(
        self,
        user_id: UUID,
        since: datetime,
        *,
        order_id: UUID | None = None,
        session: object,
    ) -> bool: ...
    async def payment_observed_at(
        self,
        user_id: UUID,
        since: datetime,
        *,
        order_id: UUID | None = None,
        fallback: datetime,
        session: object,
    ) -> datetime | None: ...

    async def save_series(self, values: dict, *, session: object) -> None: ...
    async def schedule(self, series: dict, *, session: object) -> None: ...
    async def expand_admin(self, at: datetime, *, session: object) -> None: ...
    async def claim(
        self,
        at: datetime,
        lease_seconds: int,
        *,
        session: object,
        include_followups: bool = True,
    ) -> dict | None: ...
    async def eligible(
        self,
        job: dict,
        at: datetime,
        *,
        session: object,
        mark_sending: bool = True,
    ) -> dict | None: ...
    async def retry_preparation(
        self, job: dict, at: datetime, *, session: object
    ) -> None: ...
    async def retry_before_transport(
        self,
        job: dict,
        at: datetime,
        *,
        session: object,
        retry_after_seconds: int = 0,
    ) -> None: ...
    async def finish(
        self,
        job: dict,
        state: str,
        reference: str | None,
        reason: str | None,
        *,
        session: object,
    ) -> None: ...
