"""Persist a problem report and its admin notification intent atomically."""

from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.customer_workflow_common import (
    CustomerWorkflowService,
)
from ugc_bot.domain.customer_workflows import SupportInput


class OrderSupportService(CustomerWorkflowService):
    async def request_payload(self, payload: dict, *, session: object) -> dict:
        if payload.get("topic") != "payment":
            return payload
        payment_state = await self.repository.payment_state(
            UUID(payload["order_id"]), session=session
        )
        return payload | {"payment_state": payment_state}

    async def create(
        self,
        user_id: UUID,
        command: SupportInput,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        return await self.create_request(
            user_id, "support", command.model_dump(mode="json"), principal
        )

    async def create_payment_request(
        self,
        user_id: UUID,
        command: SupportInput,
        *,
        principal: AuthenticatedMessengerPrincipal,
    ) -> dict:
        return await self.create_request(
            user_id,
            "support",
            command.model_dump(mode="json") | {"topic": "payment"},
            principal,
        )

    async def list(
        self,
        user_id: UUID,
        order_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> list[dict]:
        async with self.transactions.transaction() as session:
            await self.authorize(user_id, principal, session=session)
            await self.require_order(user_id, order_id, session=session)
            return await self.repository.requests(
                user_id, order_id, session=session
            )

    async def update_status(
        self,
        actor_id: UUID,
        request_id: UUID,
        state: str,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> None:
        if state not in ("new", "in_progress", "resolved"):
            raise ValueError("support_state_invalid")
        async with self.transactions.transaction() as session:
            await self.authorize(
                actor_id, principal, admin=True, session=session
            )
            await self.repository.support_status(
                request_id, state, session=session
            )
