"""Batch delivery counters for visible orders, separate from paid positions."""

from dataclasses import dataclass

from sqlalchemy import func, inspect, select

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
    if session.get_bind().dialect.name == "postgresql":
        installed = session.execute(
            select(
                *(
                    func.to_regclass(name).is_not(None)
                    for name in sorted(tables)
                )
            )
        ).one()
        if not all(installed):
            return {}
    elif not tables <= set(inspect(session.connection()).get_table_names()):
        return {}
    authors = delivered_author_rows(order_ids)
    rows = session.execute(
        select(
            OrderModel.order_id,
            func.count(authors.c.creator_id),
            picked_order_count(),
        )
        .outerjoin(authors, authors.c.order_id == OrderModel.order_id)
        .where(OrderModel.order_id.in_(order_ids), use_financial_positions())
        .group_by(OrderModel.order_id)
    )
    return {
        order_id: OrderProgress(int(picked), int(transferred))
        for order_id, transferred, picked in rows
    }
