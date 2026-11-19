"""Batch delivery counters for visible orders, separate from paid positions."""

from dataclasses import dataclass

from sqlalchemy import String, cast, func, literal, select, union_all

from ugc_bot.admin.manual_deliveries import (
    delivery_schema,
    manual_delivery_rows,
)
from ugc_bot.infrastructure.db.creator_transfer_models import TRANSFERS
from ugc_bot.infrastructure.db.models import OrderModel
from ugc_bot.infrastructure.db.order_selection import (
    picked_order_count,
    use_financial_positions,
)
from ugc_bot.infrastructure.db.replacement_models import TABLES as REPLACEMENTS
from ugc_bot.infrastructure.db.repositories.creator_transfers import (
    delivered_author_rows,
)
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED


@dataclass(frozen=True, slots=True)
class OrderProgress:
    picked_count: int
    transferred_count: int
    manual_count: int = 0


def financial_order_ids(orders):
    return [
        order.order_id
        for order in orders
        if order.financial_version is not None and not order.complimentary
    ]


async def load_async_order_progress(session, orders):
    order_ids = financial_order_ids(orders)
    if not order_ids:
        return {}
    return await session.run_sync(load_order_progress, order_ids)


def load_order_progress(session, order_ids):
    if not order_ids:
        return {}
    tables = {
        TRANSFERS.name,
        ACCEPTED.name,
        REPLACEMENTS["allocations"].name,
        REPLACEMENTS["contacts"].name,
    }
    installed, manual_available = delivery_schema(session, tables)
    if not tables <= installed:
        return {}
    authors = delivered_author_rows(order_ids)
    sources = [
        select(
            authors.c.order_id,
            cast(authors.c.creator_id, String).label("creator_key"),
            literal(0).label("manual"),
        )
    ]
    if manual_available:
        manual = manual_delivery_rows(order_ids).subquery()
        sources.append(
            select(
                manual.c.order_id,
                func.coalesce(
                    cast(manual.c.user_id, String),
                    literal("instagram:") + func.lower(manual.c.instagram),
                ).label("creator_key"),
                literal(1).label("manual"),
            )
        )
    combined = union_all(*sources).subquery()
    unique = (
        select(
            combined.c.order_id,
            combined.c.creator_key,
            func.max(combined.c.manual).label("manual"),
        )
        .group_by(combined.c.order_id, combined.c.creator_key)
        .subquery()
    )
    rows = session.execute(
        select(
            OrderModel.order_id,
            func.count(unique.c.creator_key),
            picked_order_count(),
            func.coalesce(func.sum(unique.c.manual), 0),
        )
        .outerjoin(unique, unique.c.order_id == OrderModel.order_id)
        .where(OrderModel.order_id.in_(order_ids), use_financial_positions())
        .group_by(OrderModel.order_id)
    )
    return {
        order_id: OrderProgress(int(picked), int(transferred), int(manual))
        for order_id, transferred, picked, manual in rows
    }
