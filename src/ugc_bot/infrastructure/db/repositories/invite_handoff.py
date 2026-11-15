"""Shared authorization for Telegram and Mini App contact handoff."""

import re

from sqlalchemy import func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import SHARING, VISITS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerOrderModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
    preview_order,
)


async def handoff_installed(db: AsyncSession) -> bool:
    if db.get_bind().dialect.name != "postgresql":
        return False
    return bool(await db.scalar(select(func.to_regclass(SHARING.name))))


def eligible_order(order_id):
    return select(OrderModel.order_id).where(
        OrderModel.order_id == order_id,
        OrderModel.status == "active",
        or_(
            preview_order(),
            OrderModel.financial_version.is_not(None)
            & OrderModel.complimentary.is_(False),
        ),
    )


def public_telegram(value):
    handle = (value or "").strip().removeprefix("@")
    return (
        f"@{handle}"
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", handle)
        else None
    )


async def save_sharing(db, order_id, client, enabled):
    if not await db.scalar(
        eligible_order(order_id)
        .where(OrderModel.advertiser_id == client.user_id)
        .with_for_update()
    ):
        raise PermissionError("invite_order_unavailable")
    if enabled and not public_telegram(client.telegram):
        raise ValueError("invite_client_telegram_required")
    await db.execute(
        insert(SHARING)
        .values(order_id=order_id, client_id=client.user_id, enabled=enabled)
        .on_conflict_do_update(
            index_elements=[SHARING.c.order_id],
            set_={"enabled": enabled, "client_id": client.user_id},
        )
    )


async def sharing_state(db, order_id, client):
    if not await db.scalar(
        eligible_order(order_id).where(
            OrderModel.advertiser_id == client.user_id
        )
    ):
        raise PermissionError("invite_order_unavailable")
    return bool(
        await db.scalar(
            select(SHARING.c.enabled).where(
                SHARING.c.order_id == order_id,
                SHARING.c.client_id == client.user_id,
            )
        )
    )


async def creator_destination(db, invite_id, creator_id, at):
    row = (
        await db.execute(
            select(
                INVITES.c.order_id,
                INVITES.c.manager_id,
                OrderModel.advertiser_id,
            )
            .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
            .where(
                INVITES.c.id == invite_id,
                INVITES.c.expires_at > at,
                OrderModel.status == "active",
                or_(
                    INVITES.c.creator_id == creator_id,
                    (INVITES.c.target_id == creator_id)
                    & (INVITES.c.consent_source == PREVIEW_CONSENT)
                    & preview_order(),
                ),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    client = await db.scalar(
        select(UserModel.telegram)
        .join(SHARING, SHARING.c.client_id == UserModel.user_id)
        .where(
            SHARING.c.order_id == row.order_id,
            SHARING.c.enabled.is_(True),
            UserModel.user_id == row.advertiser_id,
            UserModel.status == "active",
        )
    )
    if client := public_telegram(client):
        return "Заказчик", client
    manager = await db.scalar(
        select(UserModel.telegram)
        .join(ManagerOrderModel, ManagerOrderModel.user_id == UserModel.user_id)
        .where(
            ManagerOrderModel.order_id == row.order_id,
            UserModel.user_id == row.manager_id,
            UserModel.status == "active",
        )
    )
    if manager := public_telegram(manager):
        return "Менеджер", manager
    return None


async def track_visit(db, invite_id, user_id, at):
    await db.execute(
        insert(VISITS)
        .values(invite_id=invite_id, user_id=user_id, opened_at=at)
        .on_conflict_do_update(
            index_elements=[VISITS.c.invite_id, VISITS.c.user_id],
            set_={"opened_at": at},
        )
    )


async def recent_invitation(transactions, user_id, at):
    if transactions is None:
        return None
    async with transactions.transaction() as session:
        db = _session(session)
        if not await handoff_installed(db):
            return None
        profile = await db.get(BloggerProfileModel, user_id)
        if (
            profile is None
            or not profile.confirmed
            or not profile.instagram_user_id
        ):
            return None
        try:
            instagram = instagram_handle(profile.instagram_url)
        except ValueError:
            return None
        return await db.scalar(
            select(INVITES.c.id)
            .join(VISITS, VISITS.c.invite_id == INVITES.c.id)
            .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
            .where(
                VISITS.c.user_id == user_id,
                INVITES.c.instagram == instagram,
                INVITES.c.expires_at > at,
                INVITES.c.consented_at.is_(None),
                or_(
                    INVITES.c.consent_source.is_(None),
                    INVITES.c.consent_source != PREVIEW_CONSENT,
                ),
                or_(
                    INVITES.c.target_id.is_(None),
                    INVITES.c.target_id == user_id,
                ),
                OrderModel.status == "active",
                OrderModel.advertiser_id != user_id,
            )
            .order_by(VISITS.c.opened_at.desc())
            .limit(1)
        )


def first_staff_open(item, installed):
    from ugc_bot.infrastructure.db.invite_handoff_models import STAFF_DELIVERIES

    return (
        select(STAFF_DELIVERIES.c.accepted_at)
        .where(STAFF_DELIVERIES.c.paid_item_id == item.paid_item_id)
        .correlate(item)
        .scalar_subquery()
        if installed
        else literal(None)
    )
