"""Create invitations and accept them through the normal paid allocation."""

import re
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select, text

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
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    preview_item,
    preview_order,
)


async def invitations_available(db):
    # Ordinary paid delivery also runs against historical schemas before 0135.
    return await db.scalar(select(func.to_regclass(INVITES.name))) is not None


def staff_consent_available():
    return text(
        "EXISTS (SELECT 1 FROM pg_attribute WHERE "
        "attrelid = to_regclass('order_creator_invites') "
        "AND attname = 'reported_at' AND NOT attisdropped)"
    )


def free_positions(order_id):
    return select(OrderItemModel).where(
        OrderItemModel.order_id == order_id,
        or_(
            and_(
                OrderItemModel.captured_at.is_not(None),
                OrderItemModel.selection_state == "paid",
            ),
            preview_item(),
        ),
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
        or_(
            and_(
                OrderModel.financial_version.is_not(None),
                OrderModel.complimentary.is_(False),
                exists().where(
                    OrderItemModel.order_id == order_id,
                    OrderItemModel.captured_at.is_not(None),
                ),
            ),
            preview_order(),
        ),
    )
    return db.scalar(query.with_for_update() if lock else query)


def telegram_handle(value):
    clean = value.strip().removeprefix("https://t.me/").removeprefix("@")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", clean):
        raise ValueError("creator_invite_telegram_invalid")
    return clean.lower()


def matching_creator_profiles(db, instagram, telegram):
    handle = instagram_handle(instagram)
    telegram = telegram_handle(telegram) if telegram else None
    profiles = db.execute(
        select(BloggerProfileModel.user_id, BloggerProfileModel.instagram_url)
        .where(BloggerProfileModel.confirmed.is_(True))
        .where(BloggerProfileModel.instagram_url.ilike(f"%{handle}%"))
    ).all()
    matches = {
        row.user_id for row in profiles if _matches(row.instagram_url, handle)
    }
    if telegram:
        aliases = db.execute(
            select(
                UserModel.user_id,
                BloggerProfileModel.instagram_url,
                BloggerProfileModel.confirmed,
            )
            .outerjoin(
                BloggerProfileModel,
                BloggerProfileModel.user_id == UserModel.user_id,
            )
            .where(func.lower(func.ltrim(UserModel.telegram, "@")) == telegram)
        ).all()
        telegram_users = {row.user_id for row in aliases}
        different_profile = any(
            row.confirmed and not _matches(row.instagram_url, handle)
            for row in aliases
        )
        if (
            different_profile
            or len(telegram_users) > 1
            or (matches and telegram_users and telegram_users != matches)
        ):
            raise ValueError("creator_invite_profile_conflict")
    if len(matches) > 1:
        raise ValueError("creator_invite_profile_conflict")
    return matches


def create_invite(  # noqa: C901, PLR0912
    db,
    order_id,
    item_id,
    manager_id,
    instagram,
    at,
    *,
    telegram="",
    actor_id=None,
    consent_source="",
    creator_name="",
):
    handle = instagram_handle(instagram)
    telegram = telegram_handle(telegram) if telegram else None
    order = order_for_invite(db, order_id, lock=True)
    if order is None or not db.scalar(
        free_positions(order_id).where(OrderItemModel.paid_item_id == item_id)
    ):
        raise ValueError("creator_invite_position_unavailable")
    managers = {row.user_id for row in db.execute(team(order))}
    if manager_id is not None and manager_id not in managers:
        raise ValueError("creator_invite_manager_unavailable")
    if actor_id is not None and (
        actor_id not in managers or manager_id != actor_id
    ):
        raise PermissionError("creator_invite_manager_unavailable")

    matches = matching_creator_profiles(db, handle, telegram)
    if order.advertiser_id in matches:
        raise ValueError("creator_invite_profile_conflict")
    target_id = next(iter(matches), None)
    if consent_source and not telegram:
        raise ValueError("creator_invite_telegram_invalid")
    if consent_source and db.scalar(
        select(INTERESTS.c.interest_id).where(
            INTERESTS.c.order_id == order_id,
            func.lower(
                func.split_part(
                    func.rtrim(INTERESTS.c.instagram_url, "/"), "/", -1
                )
            )
            == handle,
        )
    ):
        raise ValueError("creator_invite_already_interested")

    reserved = db.execute(
        select(
            INVITES.c.id,
            INVITES.c.instagram,
            INVITES.c.telegram,
            INVITES.c.manager_id,
            INVITES.c.expires_at,
        ).where(
            INVITES.c.item_id == item_id,
            INVITES.c.reported_at.is_not(None),
        )
    ).one_or_none()
    if reserved:
        if (
            reserved.instagram != handle
            or reserved.telegram != telegram
            or reserved.manager_id != manager_id
        ):
            raise ValueError("creator_invite_position_unavailable")
        if reserved.expires_at <= at:
            db.execute(
                INVITES.update()
                .where(INVITES.c.id == reserved.id)
                .values(
                    expires_at=at + timedelta(days=30),
                )
            )
        return reserved.id
    if db.scalar(
        select(INVITES.c.id)
        .where(
            INVITES.c.order_id == order_id,
            INVITES.c.item_id != item_id,
            INVITES.c.reported_at.is_not(None),
            ((INVITES.c.instagram == handle) | (INVITES.c.telegram == telegram))
            if telegram
            else INVITES.c.instagram == handle,
        )
        .limit(1)
    ):
        raise ValueError("creator_invite_already_interested")
    existing = db.execute(
        select(INVITES.c.id, INVITES.c.reported_at, INVITES.c.expires_at)
        .where(
            INVITES.c.order_id == order_id,
            INVITES.c.item_id == item_id,
            INVITES.c.instagram == handle,
            INVITES.c.telegram.is_not_distinct_from(telegram),
            INVITES.c.manager_id.is_not_distinct_from(manager_id),
            INVITES.c.consented_at.is_(None),
            (INVITES.c.expires_at > at) | INVITES.c.reported_at.is_not(None),
        )
        .order_by(
            INVITES.c.reported_at.is_not(None).desc(),
            INVITES.c.expires_at.desc(),
        )
        .limit(1)
    ).one_or_none()
    values = {}
    if consent_source and (existing is None or existing.reported_at is None):
        values = dict(
            reported_at=at,
            reported_by=str(actor_id) if actor_id else "admin",
            consent_source=consent_source,
            creator_name=creator_name or None,
        )
    if existing:
        if values and existing.expires_at < at + timedelta(days=30):
            values["expires_at"] = at + timedelta(days=30)
        if values:
            db.execute(
                INVITES.update()
                .where(INVITES.c.id == existing.id)
                .values(**values)
            )
        return existing.id
    identity = uuid4()
    db.execute(
        INVITES.insert().values(
            id=identity,
            order_id=order_id,
            item_id=item_id,
            manager_id=manager_id,
            target_id=target_id,
            instagram=handle,
            telegram=telegram,
            expires_at=at + timedelta(days=30),
            **values,
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
            OrderModel.complimentary,
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
        or row["expires_at"] <= at
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
