"""Read-only admin projection of evidenced manual contact handoffs."""

from sqlalchemy import and_, exists, func, inspect, or_, select

from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import (
    NOTICES,
    STAFF_DELIVERIES,
)
from ugc_bot.infrastructure.db.models import OrderItemModel, OrderModel
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    staff_consent_available,
)

MANUAL_TABLES = {INVITES.name, NOTICES.name, STAFF_DELIVERIES.name}


def delivery_schema(session, tables):
    """Probe once per batch; old schemas keep their existing counters."""
    names = sorted(set(tables) | MANUAL_TABLES)
    if session.get_bind().dialect.name == "postgresql":
        result = session.execute(
            select(
                *(func.to_regclass(name).is_not(None) for name in names),
                staff_consent_available(),
            )
        ).one()
        installed = {
            name
            for name, present in zip(names, result[:-1], strict=True)
            if present
        }
        return installed, installed >= MANUAL_TABLES and bool(result[-1])
    inspector = inspect(session.connection())
    installed = set(inspector.get_table_names())
    manual = installed >= MANUAL_TABLES and "reported_at" in {
        column["name"] for column in inspector.get_columns(INVITES.name)
    }
    return installed, manual


def manual_delivery_rows(order_ids):
    acknowledged = exists().where(
        STAFF_DELIVERIES.c.delivery_id == INVITES.c.id,
        STAFF_DELIVERIES.c.order_id == OrderModel.order_id,
        STAFF_DELIVERIES.c.paid_item_id == OrderItemModel.paid_item_id,
        STAFF_DELIVERIES.c.client_id == OrderModel.advertiser_id,
    )
    return (
        select(
            INVITES.c.id.label("invite_id"),
            INVITES.c.order_id,
            INVITES.c.item_id,
            func.coalesce(INVITES.c.creator_id, INVITES.c.target_id).label(
                "user_id"
            ),
            INVITES.c.instagram,
            INVITES.c.telegram,
            INVITES.c.creator_name,
            OrderItemModel.ordinal,
        )
        .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
        .join(
            OrderItemModel,
            and_(
                OrderItemModel.paid_item_id == INVITES.c.item_id,
                OrderItemModel.order_id == INVITES.c.order_id,
            ),
        )
        .outerjoin(
            NOTICES,
            and_(
                NOTICES.c.invite_id == INVITES.c.id,
                NOTICES.c.kind == "customer",
                NOTICES.c.state == "sent",
            ),
        )
        .where(
            INVITES.c.order_id.in_(order_ids),
            INVITES.c.reported_at.is_not(None),
            OrderModel.financial_version.is_not(None),
            OrderModel.complimentary.is_(False),
            or_(NOTICES.c.invite_id.is_not(None), acknowledged),
        )
    )


def load_manual_history(session, order_ids):
    if not order_ids or not delivery_schema(session, MANUAL_TABLES)[1]:
        return []
    return [
        dict(
            creator_id=row.user_id or f"instagram:{row.instagram.lower()}",
            profile_id=row.user_id,
            contact={
                "name": row.creator_name or f"@{row.instagram}",
                "instagram": f"https://instagram.com/{row.instagram}",
                "telegram": row.telegram,
            },
            source="manual",
            manual=True,
            ordinal=row.ordinal,
            # The legacy notice stores acceptance state, not a send timestamp.
            sent_at=None,
            feedback=None,
            requested_price=None,
        )
        for row in session.execute(manual_delivery_rows(order_ids))
    ]


def merge_manual_history(history, manual):
    result = {str(row["creator_id"]): dict(row) for row in history}
    for row in manual:
        key = str(row["creator_id"])
        if key in result:
            result[key].update(manual=True, ordinal=row["ordinal"])
        else:
            result[key] = row
    return list(result.values())
