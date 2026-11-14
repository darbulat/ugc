"""Create invitations and accept them through the normal paid allocation."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import exists, func, select

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS, JOBS


async def invitations_available(db):
    # Ordinary paid delivery also runs against historical schemas before 0134.
    return await db.scalar(select(func.to_regclass(INVITES.name))) is not None


def free_positions(order_id):
    return select(OrderItemModel).where(
        OrderItemModel.order_id == order_id,
        OrderItemModel.captured_at.is_not(None),
        OrderItemModel.selection_state == "paid",
        ~exists().where(
            ItemAssignmentModel.paid_item_id == OrderItemModel.paid_item_id
        ),
    )


def team(order):
    return (
        select(UserModel.user_id, UserModel.username, UserModel.telegram)
        .join(ManagerOrderModel, ManagerOrderModel.user_id == UserModel.user_id)
        .where(
            ManagerOrderModel.order_id == order.order_id,
            UserModel.status == "active",
            UserModel.user_id != order.advertiser_id,
        )
        .order_by(UserModel.username, UserModel.user_id)
    )


def order_for_invite(db, order_id, *, lock=False):
    query = select(OrderModel).where(
        OrderModel.order_id == order_id,
        OrderModel.status == OrderStatus.ACTIVE,
        OrderModel.financial_version.is_not(None),
        OrderModel.complimentary.is_(False),
        exists().where(
            OrderItemModel.order_id == order_id,
            OrderItemModel.captured_at.is_not(None),
        ),
    )
    return db.scalar(query.with_for_update() if lock else query)


def create_invite(db, order_id, item_id, manager_id, instagram, at):
    handle = instagram_handle(instagram)
    order = order_for_invite(db, order_id, lock=True)
    if order is None or not db.scalar(
        free_positions(order_id).where(OrderItemModel.paid_item_id == item_id)
    ):
        raise ValueError("creator_invite_position_unavailable")
    if (
        manager_id is not None
        and not db.execute(
            team(order).where(UserModel.user_id == manager_id)
        ).first()
    ):
        raise ValueError("creator_invite_manager_unavailable")
    profiles = db.execute(
        select(BloggerProfileModel.user_id, BloggerProfileModel.instagram_url)
        .where(BloggerProfileModel.confirmed.is_(True))
        .where(BloggerProfileModel.instagram_url.ilike(f"%{handle}%"))
    ).all()
    matches = [
        row.user_id for row in profiles if _matches(row.instagram_url, handle)
    ]
    if len(matches) > 1 or order.advertiser_id in matches:
        raise ValueError("creator_invite_profile_conflict")
    existing = db.execute(
        select(INVITES.c.id).where(
            INVITES.c.order_id == order_id,
            INVITES.c.item_id == item_id,
            INVITES.c.instagram == handle,
            INVITES.c.manager_id.is_not_distinct_from(manager_id),
            INVITES.c.consented_at.is_(None),
            INVITES.c.expires_at > at,
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    identity = uuid4()
    db.execute(
        INVITES.insert().values(
            id=identity,
            order_id=order_id,
            item_id=item_id,
            manager_id=manager_id,
            target_id=matches[0] if matches else None,
            instagram=handle,
            expires_at=at + timedelta(days=7),
        )
    )
    return identity


def _matches(url, handle):
    try:
        return instagram_handle(url) == handle
    except ValueError:
        return False


async def invitation(db, identity, at, creator_id=None, *, lock=False):
    stmt = (
        select(
            INVITES,
            OrderModel.offer_text,
            OrderModel.geography,
            OrderModel.status,
        )
        .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
        .where(INVITES.c.id == identity)
    )
    if lock:
        stmt = stmt.with_for_update(of=INVITES)
    row = (await db.execute(stmt)).mappings().one_or_none()
    if (
        row is None
        or (row["target_id"] is not None and row["target_id"] != creator_id)
        or (row["creator_id"] is not None and row["creator_id"] != creator_id)
        or (
            row["consented_at"] is None
            and (row["expires_at"] <= at or row["status"] != OrderStatus.ACTIVE)
        )
    ):
        raise ValueError("creator_invite_unavailable")
    return row


def contact_job_query(client_id, assignment_id):
    return (
        select(JOBS.c.job_id, JOBS.c.state, JOBS.c.current_attempt_id)
        .join(INTERESTS, INTERESTS.c.interest_id == JOBS.c.interest_id)
        .join(INVITES, INVITES.c.interest_id == INTERESTS.c.interest_id)
        .join(
            ItemAssignmentModel,
            ItemAssignmentModel.assignment_id == INTERESTS.c.assignment_id,
        )
        .join(OrderModel, OrderModel.order_id == INTERESTS.c.order_id)
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == INTERESTS.c.paid_item_id,
        )
        .where(
            INTERESTS.c.client_id == client_id,
            INTERESTS.c.assignment_id == assignment_id,
            OrderModel.advertiser_id == client_id,
            OrderModel.status.in_((OrderStatus.ACTIVE, OrderStatus.CLOSED)),
            OrderItemModel.selection_state.in_(("paid", "delivered")),
            ItemAssignmentModel.valid_to.is_(None),
        )
    )
