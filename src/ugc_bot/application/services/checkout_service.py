"""Commit issuance before one-shot I/O; keep uncertainty and money separate."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from ugc_bot.application.checkout_ports import (
    CheckoutRepository,
    InvoiceLinkGateway,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.checkout import (
    CheckoutActor,
    LinkRejected,
    PreparedInvoice,
    invoice_url,
)


@dataclass(frozen=True)
class CheckoutService:
    repository: CheckoutRepository
    transactions: TransactionManager
    gateway: InvoiceLinkGateway | None
    core_enabled: bool
    new_orders_enabled: bool

    async def request_invoice(
        self, order_id: UUID, actor: CheckoutActor, operation_key: str
    ) -> dict[str, Any]:
        return await self._request(order_id, actor, operation_key, None)

    async def retry_link(
        self,
        order_id: UUID,
        actor: CheckoutActor,
        operation_key: str,
        previous_attempt_id: UUID,
    ) -> dict[str, Any]:
        return await self._request(
            order_id, actor, operation_key, previous_attempt_id
        )

    async def _request(self, order_id, actor, operation_key, retry_of):
        if actor.platform != "telegram":
            raise PermissionError("telegram_checkout_required")
        if not isinstance(operation_key, str) or not operation_key.strip():
            raise ValueError("operation_key_required")
        async with self.transactions.transaction() as session:
            prepared = await self.repository.prepare(
                order_id,
                actor,
                operation_key,
                allow_new=self.core_enabled
                and self.new_orders_enabled
                and self.gateway is not None,
                retry_of=retry_of,
                session=session,
            )
        if not isinstance(prepared, PreparedInvoice):
            return prepared
        outcome, url = "unknown", None
        try:
            if self.gateway is None:
                raise LinkRejected("invoice_gateway_unavailable")
            url = invoice_url(await self.gateway.create_link(prepared))
            outcome = "ready"
        except LinkRejected:
            outcome = "failed"
        except Exception:
            # Network errors/invalid returned URL never prove a failed charge.
            # No automatic retry of even this nonmonetary operation.
            outcome = "unknown"
        async with self.transactions.transaction() as session:
            return await self.repository.complete(
                prepared, outcome=outcome, url=url, session=session
            )

    async def status(
        self, order_id: UUID, actor: CheckoutActor
    ) -> dict[str, Any]:
        async with self.transactions.transaction() as session:
            value = await self.repository.status(
                order_id, actor, session=session
            )
        value["writes_paused"] = not (
            self.core_enabled and self.new_orders_enabled
        )
        value["can_open"] = (
            value.get("can_open", False) and not value["writes_paused"]
        )
        return value

    async def authorize(
        self,
        order_id: UUID,
        payer_external_id: str,
        query_id: str,
        amount: int,
        currency: str,
    ) -> dict[str, Any]:
        async with self.transactions.transaction() as session:
            return await self.repository.authorize(
                order_id,
                payer_external_id,
                query_id,
                amount,
                currency,
                session=session,
                allow_new=self.core_enabled and self.new_orders_enabled,
            )

    async def review_authorization(
        self,
        authorization_id: UUID,
        actor: CheckoutActor,
        operation_key: str,
        expected_version: int,
        reason: str,
        evidence_reference: str,
    ) -> dict[str, Any]:
        async with self.transactions.transaction() as session:
            return await self.repository.review_authorization(
                authorization_id,
                actor,
                operation_key,
                expected_version,
                reason,
                evidence_reference,
                session=session,
            )

    async def review_context(
        self, order_id: UUID, actor: CheckoutActor
    ) -> dict[str, Any]:
        async with self.transactions.transaction() as session:
            return await self.repository.review_context(
                order_id, actor, session=session
            )
