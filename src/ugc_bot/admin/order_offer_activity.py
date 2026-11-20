"""Read-only delivery and response data for a single order."""

from collections import Counter
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ugc_bot.domain.enums import OrderStatus, RejectionReason
from ugc_bot.domain.offer_intake import intake_open, reserve_notice
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.dispatch_control import CLAIMS, CONTROLS
from ugc_bot.infrastructure.db.messenger_attribution import OFFER_CHANNELS
from ugc_bot.infrastructure.db.models import (
    OfferDispatchModel,
    OrderModel,
    UserModel,
)

_REASONS = {
    RejectionReason.LOW_PRICE: "Низкая цена",
    RejectionReason.WRONG_FORMAT: "Не подходит формат",
    RejectionReason.UNINTERESTING_PRODUCT: "Не заинтересовал продукт",
    RejectionReason.NO_TIME: "Нет времени",
    RejectionReason.ALREADY_WORKING_WITH_BRAND: "Уже работает с брендом",
}


def _dispatch_status(row) -> str | None:
    if row.audience_ready and not row.targeted:
        return "Нет получателей"
    remaining = (
        row.targeted - row.sent_to_audience - row.failed - row.via_invite
    )
    if row.audience_ready and remaining == 0:
        return "Рассылка завершена"
    if row.dispatch_stopped or row.status == OrderStatus.CLOSED:
        return "Рассылка остановлена"
    if row.paused:
        return "Рассылка на паузе"
    if row.audience_ready:
        return f"Авторов без результата отправки — {remaining}"
    if row.audience_ready is False:
        return "Готовим выборку для рассылки"
    return None


async def load_order_offer_activity(
    session: AsyncSession, order_id: UUID
) -> dict | None:
    # One snapshot keeps the counts consistent with the list of refusals.
    sent = or_(
        OFFER_CHANNELS.c.telegram_sent_at.is_not(None),
        OFFER_CHANNELS.c.max_sent_at.is_not(None),
        # Older sends have no channel record. A personal link can also create a
        # response row on its own, even though no bot offer was sent.
        ~exists().where(
            INVITES.c.order_id == order_id,
            INVITES.c.creator_id == OfferDispatchModel.blogger_id,
            INVITES.c.consented_at.is_not(None),
        ),
    )
    offers = (
        select(
            OfferDispatchModel.blogger_id,
            sent.label("sent"),
            OfferDispatchModel.accepted,
            OfferDispatchModel.rejection_reason,
            OfferDispatchModel.desired_price,
            func.coalesce(
                OfferDispatchModel.updated_at, OfferDispatchModel.created_at
            ).label("responded_at"),
        )
        .outerjoin(
            OFFER_CHANNELS,
            and_(
                OFFER_CHANNELS.c.order_id == OfferDispatchModel.order_id,
                OFFER_CHANNELS.c.blogger_id == OfferDispatchModel.blogger_id,
            ),
        )
        .where(OfferDispatchModel.order_id == order_id)
        .cte()
    )
    responses = select(
        func.count().filter(offers.c.sent.is_(True)).label("sent"),
        func.count().filter(offers.c.accepted.is_(True)).label("accepted"),
    ).subquery()
    audience = (
        select(
            func.count(CLAIMS.c.blogger_id).label("targeted"),
            func.count()
            .filter(offers.c.sent.is_(True))
            .label("sent_to_audience"),
            func.count()
            .filter(CLAIMS.c.rejected.is_(True), offers.c.sent.is_not(True))
            .label("failed"),
            func.count()
            .filter(CLAIMS.c.rejected.is_(False), offers.c.sent.is_(False))
            .label("via_invite"),
        )
        .select_from(
            CLAIMS.outerjoin(offers, CLAIMS.c.blogger_id == offers.c.blogger_id)
        )
        .where(CLAIMS.c.order_id == order_id)
        .subquery()
    )
    declines = (
        select(
            offers.c.blogger_id,
            offers.c.rejection_reason,
            offers.c.desired_price,
            offers.c.responded_at,
            UserModel.username.label("name"),
        )
        .select_from(
            offers.outerjoin(
                UserModel, UserModel.user_id == offers.c.blogger_id
            )
        )
        .where(offers.c.accepted.is_(False))
        .subquery()
    )
    result = await session.execute(
        select(
            OrderModel.status,
            OrderModel.offer_reserve_until,
            OrderModel.currency,
            OrderModel.dispatch_stopped,
            CONTROLS.c.audience_ready,
            CONTROLS.c.paused,
            responses,
            audience,
            declines,
        )
        .select_from(OrderModel)
        .outerjoin(CONTROLS, CONTROLS.c.order_id == OrderModel.order_id)
        .join(responses, true())
        .join(audience, true())
        .outerjoin(declines, true())
        .where(
            OrderModel.order_id == order_id,
            OrderModel.status != OrderStatus.DELETED,
        )
        .order_by(
            declines.c.desired_price.is_(None),
            declines.c.responded_at.desc(),
            declines.c.blogger_id,
        )
    )
    rows = result.all()
    if not rows:
        return None
    summary = rows[0]
    refused = [
        {
            "creator_id": row.blogger_id,
            "name": row.name,
            "reason": _REASONS.get(row.rejection_reason, "Причина не указана"),
            "price": row.desired_price,
        }
        for row in rows
        if row.blogger_id is not None
    ]
    return {
        "intake_notice": (
            reserve_notice(summary.offer_reserve_until)
            if summary.offer_reserve_until is not None
            and intake_open(
                summary.status,
                summary.dispatch_stopped,
                summary.offer_reserve_until,
            )
            else "Набор завершён"
            if not intake_open(
                summary.status,
                summary.dispatch_stopped,
                summary.offer_reserve_until,
            )
            else None
        ),
        "sent": summary.sent_to_audience
        if summary.audience_ready
        else summary.sent,
        "targeted": summary.targeted if summary.audience_ready else None,
        "failed": summary.failed if summary.audience_ready else None,
        "via_invite": summary.via_invite if summary.audience_ready else 0,
        "accepted": summary.accepted,
        "declined": len(refused),
        "currency": summary.currency,
        "dispatch_status": _dispatch_status(summary),
        "refused": refused,
        "reasons": dict(Counter(row["reason"] for row in refused)),
    }
