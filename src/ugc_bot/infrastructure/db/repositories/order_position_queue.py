"""Read the same position queue for admins and assigned order managers."""

from sqlalchemy import case, exists, func, literal, select, union_all

from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.models import (
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.invite_preview import preview_item
from ugc_bot.infrastructure.db.repositories.order_review import (
    _attention,
    _order_team,
    _positions,
)

STAGES = {
    "waiting": "Ждём ответа",
    "manual": "Ручной подбор",
    "received": "Контакт получен",
}


def _invite_exists(item, item_id, *conditions):
    return exists(
        select(INVITES.c.id)
        .where(INVITES.c.item_id == item_id, *conditions)
        .correlate(item)
    )


def _paid_rows(at, order_id):
    p = _positions()
    stage = case(
        (p.c.report_state.in_(("queued", "waiting")), "waiting"),
        (p.c.contact_at.is_not(None), "received"),
        (
            _invite_exists(
                p, p.c.paid_item_id, INVITES.c.reported_at.is_not(None)
            )
            | _invite_exists(
                p,
                p.c.paid_item_id,
                INVITES.c.consented_at.is_(None),
                INVITES.c.expires_at > at,
            )
            | p.c.delivery_state.in_(("card_ready", "ready", "sending")),
            "waiting",
        ),
        else_="manual",
    )
    query = select(
        p,
        stage.label("stage"),
        _attention(p.c, at).is_(True).label("needs_review"),
        literal(False).label("preview"),
    )
    return query if order_id is None else query.where(p.c.order_id == order_id)


def _preview_rows(at, order_id, columns):
    # An explicit order is required. Complimentary demos never enter the
    # global queue, paid delivery, ledger, or the staff alert scheduler.
    item, order = OrderItemModel, OrderModel
    received = _invite_exists(
        item, item.paid_item_id, INVITES.c.reported_at.is_not(None)
    )
    waiting = _invite_exists(item, item.paid_item_id, INVITES.c.expires_at > at)
    managers = _order_team(order.order_id, order.advertiser_id).correlate(order)
    projection = {
        "order_id": order.order_id,
        "advertiser_id": order.advertiser_id,
        "offer_text": order.offer_text,
        "paid_item_id": item.paid_item_id,
        "ordinal": item.ordinal,
        "deadline": item.selection_due_at,
        "manager_id": case(
            (
                managers.with_only_columns(
                    func.count(UserModel.user_id)
                ).scalar_subquery()
                == 1,
                managers.with_only_columns(UserModel.user_id)
                .limit(1)
                .scalar_subquery(),
            ),
        ),
        "stage": case(
            (received, "received"), (waiting, "waiting"), else_="manual"
        ),
        "needs_review": literal(False),
        "preview": literal(True),
    }
    return (
        select(
            *(
                projection.get(column.key, literal(None, type_=column.type))
                for column in columns
            )
        )
        .select_from(item)
        .join(order, order.order_id == item.order_id)
        .where(item.order_id == order_id, preview_item())
    )


def queue_rows(
    db,
    at,
    order_id=None,
    *,
    stage="all",
    manager_id=None,
    unassigned=False,
    offset=0,
    limit=50,
):
    paid = _paid_rows(at, order_id)
    rows = (
        union_all(paid, _preview_rows(at, order_id, paid.selected_columns))
        if order_id is not None
        else paid
    ).subquery()
    query = select(rows)
    if stage in STAGES:
        query = query.where(rows.c.stage == stage)
    if unassigned:
        query = query.where(rows.c.manager_id.is_(None))
    elif manager_id is not None:
        query = query.where(rows.c.manager_id == manager_id)
    return (
        db.execute(
            query.order_by(rows.c.deadline, rows.c.order_id, rows.c.ordinal)
            .offset(offset)
            .limit(limit)
        )
        .mappings()
        .all()
    )


def is_order_manager(db, actor, order_id):
    client = (
        select(OrderModel.advertiser_id)
        .where(OrderModel.order_id == order_id)
        .scalar_subquery()
    )
    return (
        db.execute(
            _order_team(order_id, client).where(UserModel.user_id == actor)
        ).first()
        is not None
    )
