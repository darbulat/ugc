"""Bounded, owner-scoped order pages read saved payment and position facts."""

from sqlalchemy import func, select

from ugc_bot.domain.enums import InteractionStatus, PaymentStatus
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.collaboration_models import CollaborationModel
from ugc_bot.infrastructure.db.models import (
    InteractionModel,
    ItemAssignmentModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyClientOrderViewRepository:
    async def _progress(self, order, session):
        db = _session(session)
        if order.financial_version:
            active = (
                select(ItemAssignmentModel.assignment_id)
                .join(
                    OrderItemModel,
                    OrderItemModel.paid_item_id
                    == ItemAssignmentModel.paid_item_id,
                )
                .where(
                    OrderItemModel.order_id == order.order_id,
                    ItemAssignmentModel.valid_to.is_(None),
                )
            )
            assigned = await db.scalar(
                select(func.count()).select_from(active.subquery())
            )
            completed = await db.scalar(
                select(func.count())
                .select_from(CollaborationModel)
                .where(
                    CollaborationModel.order_id == order.order_id,
                    CollaborationModel.assignment_id.in_(active),
                    CollaborationModel.state.in_(
                        ("success_final", "available")
                    ),
                )
            )
        else:
            assigned = await db.scalar(
                select(func.count())
                .select_from(InteractionModel)
                .where(
                    InteractionModel.order_id == order.order_id,
                    InteractionModel.status != InteractionStatus.DELETED,
                )
            )
            completed = await db.scalar(
                select(func.count())
                .select_from(InteractionModel)
                .where(
                    InteractionModel.order_id == order.order_id,
                    InteractionModel.status == InteractionStatus.OK,
                )
            )
        return {
            "assigned": assigned or 0,
            "completed": completed or 0,
            "total": order.bloggers_needed,
        }

    async def _summary(self, order, session):
        db = _session(session)
        payment = await db.scalar(
            select(PaymentModel.status)
            .where(PaymentModel.order_id == order.order_id)
            .order_by(PaymentModel.created_at.desc(), PaymentModel.payment_id)
            .limit(1)
        )
        totals = (
            await db.execute(
                select(
                    func.coalesce(func.sum(OrderItemModel.selection_minor), 0),
                    func.coalesce(
                        func.sum(OrderItemModel.accompaniment_minor), 0
                    ),
                ).where(OrderItemModel.order_id == order.order_id)
            )
        ).one()
        progress = await self._progress(order, session)
        status = order.status.value
        customer_status = (
            "selecting"
            if status == "active" and progress["assigned"] < progress["total"]
            else status
        )
        return {
            "order_id": str(order.order_id),
            "public_number": public_order_number(order.order_id),
            "status": status,
            "customer_status": customer_status,
            "public_title": order.offer_text.strip().splitlines()[0][:120]
            if order.offer_text.strip()
            else order.product_link,
            "product_link": order.product_link,
            "offer_text": order.offer_text,
            "price": float(order.price),
            "order_type": order.order_type.value,
            "created_at": order.created_at.isoformat(),
            "financial_version": order.financial_version,
            "bloggers_needed": order.bloggers_needed,
            "deadlines": order.deadlines,
            "payment_state": "paid"
            if payment == PaymentStatus.PAID
            else str(payment or "unpaid"),
            "progress": progress,
            "selection_base_minor": totals[0],
            "accompaniment_minor": totals[1],
            "total_minor": totals[0] + totals[1],
            "currency_symbol": "₽"
            if order.currency == "RUB"
            else order.currency,
            "payment_link": "",
        }

    async def page(self, owner_id, page, limit, status, *, session):
        db = _session(session)
        conditions = [OrderModel.advertiser_id == owner_id]
        if status:
            conditions.append(OrderModel.status == status)
        count = (
            await db.scalar(
                select(func.count()).select_from(OrderModel).where(*conditions)
            )
            or 0
        )
        rows = (
            await db.scalars(
                select(OrderModel)
                .where(*conditions)
                .order_by(OrderModel.created_at.desc(), OrderModel.order_id)
                .offset(page * limit)
                .limit(limit)
            )
        ).all()
        items = [await self._summary(order, session) for order in rows]
        return {
            "orders": items,
            "total": count,
            "page": page,
            "has_more": (page + 1) * limit < count,
        }
