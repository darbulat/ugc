"""Shared count of assigned positions for an order."""

from sqlalchemy import case, func, select

from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
)


def picked_order_count():
    positions = (
        select(func.count())
        .select_from(ItemAssignmentModel)
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
        )
        .where(
            OrderItemModel.order_id == OrderModel.order_id,
            ItemAssignmentModel.valid_to.is_(None),
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )
    responses = (
        select(func.count())
        .select_from(OfferDispatchModel)
        .where(
            OfferDispatchModel.order_id == OrderModel.order_id,
            OfferDispatchModel.in_offer.is_(True),
        )
        .correlate(OrderModel)
        .scalar_subquery()
    )
    return case(
        (use_financial_positions(), positions),
        else_=responses,
    )


def use_financial_positions():
    return OrderModel.financial_version.is_not(
        None
    ) & OrderModel.complimentary.is_(False)
