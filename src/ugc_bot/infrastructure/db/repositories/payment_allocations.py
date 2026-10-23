"""Immutable payment allocation adapter; DB guards remain authoritative."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.infrastructure.db.models import (
    PaymentItemAllocationModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyPaymentAllocationRepository:
    async def add(
        self, allocation: PaymentItemAllocationModel, *, session: AsyncSession
    ) -> PaymentItemAllocationModel:
        db = _session(session)
        # Lock before reading idempotency/caps; no separate owned transaction.
        payment = await db.scalar(
            select(PaymentModel)
            .where(PaymentModel.payment_id == allocation.payment_id)
            .with_for_update()
        )
        if payment is None:
            raise ValueError("payment_not_found")
        existing = await db.get(
            PaymentItemAllocationModel, allocation.allocation_key
        )
        if existing is not None:
            if any(
                getattr(existing, c.name) != getattr(allocation, c.name)
                for c in PaymentItemAllocationModel.__table__.columns
            ):
                raise ValueError("idempotency_payload_conflict")
            return existing
        db.add(allocation)
        await db.flush()
        return allocation
