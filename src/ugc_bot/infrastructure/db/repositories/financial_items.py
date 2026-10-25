"""Caller-transaction financial snapshots; no implicit commits."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.application.services.paid_item_service import (
    FinancialQuote,
    QuotedItem,
)
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import (
    OrderItemModel,
    OrderModel,
    PaymentItemAllocationModel,
    PaymentModel,
)


def _session(session: object) -> AsyncSession:
    if not isinstance(session, AsyncSession) or not session.in_transaction():
        raise ValueError("caller_transaction_required")
    return session


def _payload(quote: FinancialQuote) -> dict:
    payload: dict = {
        "client_id": str(quote.client_id) if quote.client_id else None,
        "currency": quote.currency,
        "policy_version": quote.policy_version,
        "selection_due_at": quote.selection_due_at.isoformat(),
        "client_contact_reference": quote.client_contact_reference,
        "terms_reference": quote.terms_reference,
        "components": [
            [item.ordinal, item.selection_minor, item.accompaniment_minor]
            for item in quote.items
        ],
    }
    if quote.refund_rules is not None:
        payload["refund_rules"] = quote.refund_rules.to_document()
    return payload


class SqlAlchemyFinancialItemRepository:
    async def lock_order(self, order_id: UUID, *, session: object) -> None:
        if not isinstance(session, AsyncSession):
            raise ValueError("caller_transaction_required")
        db = session
        # Existing TransactionManager begins lazily on first SQL.
        # Serialize a stable command identity even before the order row exists.
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(order_id)},
        )

    async def activate_new_order(
        self, order_id: UUID, policy_version: str, *, session: object
    ) -> None:
        db = _session(session)
        await db.flush()
        order = await db.get(OrderModel, order_id)
        if order is None or order.financial_version is not None:
            raise ValueError("explicit_new_order_policy_required")
        order.financial_version = policy_version
        await db.flush()

    async def save_quote(
        self, quote: FinancialQuote, *, session: object
    ) -> FinancialQuote:
        db = _session(session)
        order = await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == quote.order_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if order is None or order.financial_version != quote.policy_version:
            raise ValueError("explicit_new_order_policy_required")
        if (
            quote.client_id is not None
            and order.advertiser_id != quote.client_id
        ):
            raise ValueError("quote_client_mismatch")
        rows = list(
            (
                await db.scalars(
                    select(OrderItemModel)
                    .where(OrderItemModel.order_id == quote.order_id)
                    .order_by(OrderItemModel.ordinal)
                )
            ).all()
        )
        payload = _payload(quote)
        if rows:
            history = dict(rows[0].quote_payload.get("_history", {}))
            replay = self._replay(rows, quote, payload)
            if replay is not None:
                return replay
            if any(row.captured_at is not None for row in rows):
                raise ValueError("captured_quote_immutable")
            if (
                await db.scalar(
                    select(PaymentModel.payment_id)
                    .where(PaymentModel.order_id == quote.order_id)
                    .limit(1)
                )
                is not None
                or await db.scalar(
                    select(PaymentItemAllocationModel.allocation_key)
                    .where(
                        PaymentItemAllocationModel.order_id == quote.order_id
                    )
                    .limit(1)
                )
                is not None
            ):
                # Freeze any issued payment, including pending bank proof.
                raise ValueError("issued_payment_quote_immutable")
            if len(rows) != len(quote.items) or [r.ordinal for r in rows] != [
                i.ordinal for i in quote.items
            ]:
                raise ValueError("quote_shape_immutable")
            history[rows[0].quote_key] = {
                k: v
                for k, v in rows[0].quote_payload.items()
                if k != "_history"
            }
            payload = dict(payload, _history=history)
            for row, item in zip(rows, quote.items, strict=True):
                row.selection_minor = item.selection_minor
                row.accompaniment_minor = item.accompaniment_minor
                row.selection_due_at = quote.selection_due_at
                row.quote_key = quote.idempotency_key
                row.quote_payload = payload
            await db.flush()
            return self._quote(rows)
        for item in quote.items:
            db.add(
                OrderItemModel(
                    paid_item_id=item.paid_item_id,
                    order_id=quote.order_id,
                    ordinal=item.ordinal,
                    currency=quote.currency,
                    selection_minor=item.selection_minor,
                    accompaniment_minor=item.accompaniment_minor,
                    policy_version=quote.policy_version,
                    selection_due_at=quote.selection_due_at,
                    quote_key=quote.idempotency_key,
                    quote_payload=payload,
                )
            )
        await db.flush()
        return quote

    @classmethod
    def _replay(
        cls, rows: list[OrderItemModel], quote: FinancialQuote, payload: dict
    ) -> FinancialQuote | None:
        history = rows[0].quote_payload.get("_history", {})
        original = history.get(quote.idempotency_key)
        if rows[0].quote_key == quote.idempotency_key:
            original = {
                k: v
                for k, v in rows[0].quote_payload.items()
                if k != "_history"
            }
        if original is None:
            return None
        if original != payload:
            raise ValueError("idempotency_payload_conflict")
        return cls._quote(rows, original, quote.idempotency_key)

    @staticmethod
    def _quote(
        rows: list[OrderItemModel],
        payload: dict | None = None,
        key: str | None = None,
    ) -> FinancialQuote:
        row = rows[0]
        snapshot = payload if payload is not None else row.quote_payload
        components = {c[0]: c[1:] for c in snapshot["components"]}
        return FinancialQuote(
            row.order_id,
            snapshot["currency"],
            snapshot["policy_version"],
            datetime.fromisoformat(snapshot["selection_due_at"]),
            snapshot["client_contact_reference"],
            snapshot["terms_reference"],
            key if key is not None else row.quote_key,
            tuple(
                QuotedItem(r.paid_item_id, r.ordinal, *components[r.ordinal])
                for r in rows
            ),
            UUID(snapshot["client_id"]) if snapshot.get("client_id") else None,
            RefundRules.from_document(snapshot["refund_rules"])
            if "refund_rules" in snapshot
            else None,
        )
