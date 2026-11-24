"""One explicit send action in the existing order workspace."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from aiogram import Bot
from fastapi import HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from starlette.requests import Request

from ugc_bot.admin.auth import admin_login_redirect
from ugc_bot.admin.manual_deliveries import (
    load_manual_history,
    merge_manual_history,
)
from ugc_bot.application.services.creator_transfer_service import (
    CreatorTransferService,
)
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.creator_transfer_models import TRANSFERS
from ugc_bot.infrastructure.db.models import (
    OfferDispatchModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_transfers import (
    SqlCreatorTransfers,
    delivery_history,
    transfers_installed,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
)

STATES = {
    "sent": "Отправлено заказчице",
    "sending": "Отправка началась",
    "failed": "Не доставлено · можно повторить вручную",
    "unknown": "Результат неизвестен · проверьте Telegram перед повтором",
}

ERRORS = {
    "transfer_order_unavailable": (
        "Отправлять можно из активного или закрытого заказа."
    ),
    "transfer_already_assigned": (
        "Автор уже назначен. Используется обычная передача контакта."
    ),
    "transfer_creator_unavailable": (
        "Нужен активный автор с подтверждённым Instagram."
    ),
    "transfer_instagram_review_required": (
        "Instagram требует проверки. Контакт пока нельзя отправить."
    ),
    "transfer_customer_unavailable": "Telegram заказчицы сейчас недоступен.",
    "transfer_history_unavailable": "История передач пока недоступна.",
    "transfer_candidate_required": (
        "Автор должен быть в подтверждённом резерве или предложить свою цену."
    ),
}


async def transfer_activity(db, order_id):
    order = await db.get(OrderModel, order_id)
    if not order or not order.financial_version or order.complimentary:
        return None
    if not await transfers_installed(db):
        return None
    history = await delivery_history(db, order_id)
    manual = await db.run_sync(load_manual_history, [order_id])
    history = merge_manual_history(history, manual)
    states = {
        row.creator_id: (
            "unknown"
            if row.state == "sending"
            and datetime.now(timezone.utc)
            >= utc(row.started_at) + timedelta(minutes=2)
            else row.state
        )
        for row in (
            await db.execute(
                select(
                    TRANSFERS.c.creator_id,
                    TRANSFERS.c.state,
                    TRANSFERS.c.started_at,
                ).where(TRANSFERS.c.order_id == order_id)
            )
        ).all()
    }
    delivered = {row["creator_id"] for row in history}
    candidates = (
        await db.execute(
            select(
                OfferDispatchModel.blogger_id,
                UserModel.username,
                OfferDispatchModel.accepted,
                OfferDispatchModel.desired_price,
            )
            .join(UserModel, UserModel.user_id == OfferDispatchModel.blogger_id)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.in_offer.is_(False),
                (OfferDispatchModel.accepted.is_(True))
                | (OfferDispatchModel.desired_price.is_not(None)),
            )
            .order_by(UserModel.username, OfferDispatchModel.blogger_id)
        )
    ).all()
    return dict(
        count=len(history),
        manual_count=sum(bool(row.get("manual")) for row in history),
        needed=order.bloggers_needed,
        history=history,
        candidates=[
            dict(
                creator_id=row.blogger_id,
                name=row.username,
                source="Резерв" if row.accepted else "Новая цена",
                price=row.desired_price,
                state="sent"
                if row.blogger_id in delivered
                else states.get(row.blogger_id),
            )
            for row in candidates
        ],
        labels=STATES,
        can_send=order.status in {"active", "closed"},
    )


def register_creator_transfers(
    app,
    auth,
    require_action_token,
    config,
    transactions,
    *,
    instagram_offer_check=None,
):
    app.state.creator_transfers_enabled = bool(
        transactions
        and config.financial.core_enabled
        and config.order.customer_workflows_enabled
    )

    @app.post("/admin/orders/{order_id}/creators/{creator_id}/send-to-customer")
    async def admin_send_creator_to_customer(
        request: Request, order_id: UUID, creator_id: UUID
    ):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        await require_action_token(request)
        if (
            transactions is None
            or not config.financial.core_enabled
            or not config.order.customer_workflows_enabled
        ):
            raise HTTPException(503, "Ручная отправка сейчас недоступна.")
        try:
            if (
                instagram_offer_check is not None
                and not await instagram_offer_check.before_contact(
                    order_id, creator_id
                )
            ):
                raise ValueError("transfer_instagram_review_required")
            async with Bot(token=config.bot.bot_token).context() as bot:
                service = CreatorTransferService(
                    SqlCreatorTransfers(),
                    transactions,
                    TelegramNoticeReceipts(bot),
                    SystemClock(),
                )
                state = await service.send(
                    order_id,
                    creator_id,
                    operator=f"admin:{config.admin.admin_username}",
                )
            message = STATES[state]
        except ValueError as exc:
            message = ERRORS.get(str(exc), "Не удалось подготовить отправку.")
        request.session["creator_transfer_result"] = {
            "order_id": str(order_id),
            "message": message,
        }
        return RedirectResponse(
            str(request.url_for("admin_order_detail", order_id=order_id)),
            status_code=303,
        )
