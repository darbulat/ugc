"""Shared authorization and normalized idempotency for customer requests."""

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID, uuid4

from ugc_bot.application.customer_workflow_ports import (
    CustomerWorkflowRepository,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc


@dataclass
class CustomerWorkflowService:
    repository: CustomerWorkflowRepository
    transactions: TransactionManager
    clock: Clock

    async def authorize(
        self,
        user_id: UUID,
        principal: AuthenticatedMessengerPrincipal | None,
        *,
        session: object,
        admin: bool = False,
    ) -> dict:
        actor = await self.repository.actor(user_id, session=session)
        require_current_principal(
            principal,
            user_id,
            actor.get("user_id"),
            actor.get("telegram_id"),
            actor.get("max_id"),
        )
        if actor.get("status") != "active" or not actor.get(
            "admin" if admin else "advertiser"
        ):
            raise PermissionError(
                "active_admin_required"
                if admin
                else "active_advertiser_required"
            )
        return actor

    async def require_order(
        self, user_id: UUID, order_id: UUID, *, session: object
    ) -> None:
        if not await self.repository.owns_order(
            user_id, order_id, session=session
        ):
            raise PermissionError("customer_order_forbidden")

    async def create_request(
        self,
        user_id: UUID,
        kind: str,
        payload: dict,
        principal: AuthenticatedMessengerPrincipal | None,
    ) -> dict:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        async with self.transactions.transaction() as session:
            await self.authorize(user_id, principal, session=session)
            order_id = (
                UUID(payload["order_id"]) if payload.get("order_id") else None
            )
            if order_id:
                await self.require_order(user_id, order_id, session=session)
            blogger_id = payload.get("blogger_id")
            if (
                blogger_id
                and order_id is not None
                and not await self.repository.blogger_on_order(
                    UUID(blogger_id), order_id, session=session
                )
            ):
                raise PermissionError("customer_blogger_forbidden")
            previous = await self.repository.request(
                user_id, kind, payload["operation_key"], session=session
            )
            if previous:
                if previous["payload_hash"] != digest:
                    raise ValueError("idempotency_payload_conflict")
                return previous
            result = dict(
                request_id=uuid4(),
                user_id=user_id,
                order_id=order_id,
                kind=kind,
                operation_key=payload["operation_key"],
                payload_hash=digest,
                payload=await self.request_payload(payload, session=session),
                state="new",
                created_at=utc(self.clock.now()),
                expanded_at=None,
            )
            await self.repository.save_request(result, session=session)
            return result

    async def request_payload(self, payload: dict, *, session: object) -> dict:
        return payload
