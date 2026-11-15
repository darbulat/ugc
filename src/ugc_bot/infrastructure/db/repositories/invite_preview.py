"""Private invitation rehearsals never enter paid selection."""

from datetime import timedelta

from sqlalchemy import and_, func, select

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    BloggerProfileModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
    UserModel,
)

PREVIEW_CONSENT = "telegram_preview"


def preview_order():
    marker = (
        select(AuditLogModel.new_values)
        .where(
            AuditLogModel.entity_type == "order_test_marker",
            AuditLogModel.entity_id == OrderModel.order_id,
        )
        .order_by(AuditLogModel.changed_at.desc(), AuditLogModel.id.desc())
        .limit(1)
        .correlate(OrderModel)
        .scalar_subquery()
    )
    return and_(
        OrderModel.status == "active",
        OrderModel.complimentary.is_(True),
        OrderModel.dispatch_stopped.is_(True),
        OrderModel.financial_version.is_(None),
        ~select(PaymentModel.payment_id)
        .where(PaymentModel.order_id == OrderModel.order_id)
        .correlate(OrderModel)
        .exists(),
        OrderModel.created_at > func.now() - timedelta(days=30),
        marker["test"].as_boolean().is_(True),
        marker["invite_preview"].as_boolean().is_(True),
    )


def preview_item():
    return and_(
        OrderItemModel.selection_state == "created",
        OrderItemModel.captured_at.is_(None),
        OrderItemModel.quote_payload["invite_preview"].as_boolean().is_(True),
        OrderItemModel.selection_due_at > func.now(),
        select(OrderModel.order_id)
        .where(OrderModel.order_id == OrderItemModel.order_id, preview_order())
        .correlate(OrderItemModel)
        .exists(),
    )


async def confirm_preview(db, invite, creator_id, at):
    creator = (
        await db.execute(
            select(UserModel, BloggerProfileModel)
            .join(
                BloggerProfileModel,
                BloggerProfileModel.user_id == UserModel.user_id,
            )
            .where(
                UserModel.user_id == creator_id,
                UserModel.status.in_(("active", "pause")),
                BloggerProfileModel.confirmed.is_(True),
            )
        )
    ).one_or_none()
    if not creator or not creator[1].instagram_user_id:
        raise ValueError("selection_verified_creator_required")
    user, profile = creator
    if instagram_handle(profile.instagram_url) != invite["instagram"]:
        raise ValueError("creator_invite_instagram_mismatch")
    handle = (user.telegram or "").lstrip("@")
    if not handle or len(handle) > 32:
        raise ValueError("creator_invite_preview_telegram_required")
    item = await db.scalar(
        select(OrderItemModel.paid_item_id).where(
            OrderItemModel.paid_item_id == invite["item_id"], preview_item()
        )
    )
    if item is None:
        raise ValueError("creator_invite_position_unavailable")
    common = (
        INVITES.c.order_id == invite["order_id"],
        INVITES.c.reported_at.is_not(None),
        INVITES.c.id != invite["id"],
    )
    if await db.scalar(
        select(INVITES.c.id).where(*common, INVITES.c.item_id == item).limit(1)
    ):
        raise ValueError("creator_invite_position_unavailable")
    if await db.scalar(
        select(INVITES.c.id)
        .where(
            *common,
            (INVITES.c.instagram == invite["instagram"])
            | (func.lower(INVITES.c.telegram) == handle.lower()),
        )
        .limit(1)
    ):
        raise ValueError("creator_invite_already_interested")
    if invite["consent_source"] != PREVIEW_CONSENT:
        await db.execute(
            INVITES.update()
            .where(INVITES.c.id == invite["id"])
            .values(
                target_id=user.user_id,
                reported_at=at,
                reported_by=PREVIEW_CONSENT,
                consent_source=PREVIEW_CONSENT,
                telegram=handle,
                creator_name=(user.username or "")[:80],
            )
        )


async def preview_positions(db, order_id, client_id):
    if not await db.scalar(
        select(OrderModel.order_id).where(
            OrderModel.order_id == order_id,
            OrderModel.advertiser_id == client_id,
            preview_order(),
        )
    ):
        raise PermissionError("creator_invite_unavailable")
    return (
        await db.execute(
            select(
                OrderItemModel.ordinal,
                INVITES.c.instagram,
                INVITES.c.telegram,
                INVITES.c.creator_name,
                INVITES.c.consent_source,
            )
            .outerjoin(
                INVITES,
                (INVITES.c.item_id == OrderItemModel.paid_item_id)
                & INVITES.c.reported_at.is_not(None),
            )
            .where(OrderItemModel.order_id == order_id, preview_item())
            .order_by(OrderItemModel.ordinal)
        )
    ).all()
