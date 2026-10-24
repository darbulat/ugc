"""Checkout transport and durable state boundaries."""

from typing import Any, Protocol
from uuid import UUID

from ugc_bot.domain.checkout import CheckoutActor, PreparedInvoice


class InvoiceLinkGateway(Protocol):
    async def create_link(self, invoice: PreparedInvoice) -> str: ...


class CheckoutRepository(Protocol):
    async def review_context(
        self, order_id: UUID, actor: CheckoutActor, *, session: object
    ) -> dict[str, Any]: ...

    async def authorize(
        self,
        order_id: UUID,
        external_id: str,
        query_id: str,
        amount: int,
        currency: str,
        *,
        session: object,
        allow_new: bool = True,
    ) -> dict[str, Any]: ...

    async def review_authorization(
        self,
        authorization_id: UUID,
        actor: CheckoutActor,
        operation_key: str,
        expected_version: int,
        reason: str,
        evidence_reference: str,
        *,
        session: object,
    ) -> dict[str, Any]: ...

    async def prepare(
        self,
        order_id: UUID,
        actor: CheckoutActor,
        operation_key: str,
        *,
        allow_new: bool,
        retry_of: UUID | None,
        session: object,
    ) -> PreparedInvoice | dict[str, Any]: ...

    async def complete(
        self,
        attempt: PreparedInvoice,
        *,
        outcome: str,
        url: str | None,
        session: object,
    ) -> dict[str, Any]: ...

    async def status(
        self, order_id: UUID, actor: CheckoutActor, *, session: object
    ) -> dict[str, Any]: ...


class PaidReceiptRepository(Protocol):
    async def accept_receipt(
        self, receipt: Any, *, session: object
    ) -> bool: ...
    async def claim_receipt(
        self, *, session: object
    ) -> dict[str, Any] | None: ...
    async def finish_receipt(
        self,
        claim: dict[str, Any],
        state: str,
        *,
        error: str | None,
        session: object,
    ) -> None: ...


class PaidNoticeRepository(Protocol):
    async def claim_notice(self, *, session: object) -> Any: ...
    async def finish_notice(
        self,
        notice: Any,
        outcome: str,
        reference: str | None,
        *,
        session: object,
    ) -> None: ...
