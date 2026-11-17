"""Send explicitly requested invitation notices once per recipient."""

from uuid import UUID

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import NOTICES
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    creator_directory_status,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


async def _claim(service, identity, kind):
    async with service.transactions.transaction() as session:
        db = _session(session)
        at = service.clock.now()
        order = (
            (
                await db.execute(
                    select(
                        INVITES,
                        OrderModel.advertiser_id,
                        OrderModel.offer_text,
                        OrderModel.creator_offer_card,
                        OrderModel.geography,
                        OrderModel.complimentary,
                    )
                    .join(OrderModel, OrderModel.order_id == INVITES.c.order_id)
                    .where(
                        INVITES.c.id == identity,
                        INVITES.c.expires_at > at,
                        OrderModel.status == "active",
                    )
                    .with_for_update(of=OrderModel)
                )
            )
            .mappings()
            .one_or_none()
        )
        if order is None or order["target_id"] is None:
            return None
        recipient = order["target_id"]
        if kind == "customer":
            direct = await db.scalar(
                select(NOTICES.c.state).where(
                    NOTICES.c.invite_id == identity, NOTICES.c.kind == "creator"
                )
            )
            if not direct or not (
                order["reported_at"] or order["consented_at"]
            ):
                return None
            recipient = order["advertiser_id"]
        address = await db.scalar(
            select(UserModel.telegram_id).where(
                UserModel.user_id == recipient,
                creator_directory_status() == "active",
            )
        )
        if not address or not address.isdecimal() or int(address) <= 0:
            return None
        claimed = await db.scalar(
            insert(NOTICES)
            .values(invite_id=identity, kind=kind, state="sending")
            .on_conflict_do_nothing()
            .returning(NOTICES.c.invite_id)
        )
        return (int(address), order) if claimed else None


async def deliver_invite_notice(
    service, bot, identity: UUID, kind: str
) -> str | None:
    claimed = await _claim(service, identity, kind)
    if claimed is None:
        return None
    address, order = claimed
    if kind == "creator":
        from ugc_bot.bot.telegram.handlers.creator_invites import (
            invitation_text,
        )

        text, markup = invitation_text(order, f"oi_{identity.hex}")
    else:
        from ugc_bot.bot.telegram.handlers.order_summary import summary_button

        button = summary_button(order["order_id"])
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=button.text,
                        callback_data=f"ip:{order['order_id'].hex}"
                        if order["complimentary"]
                        else button.callback_data,
                    )
                ]
            ]
        )
        text = (
            f"В заказе {public_order_number(order['order_id'])} доступен "
            "контакт "
            "креатора. Откройте итоги заказа."
        )
    try:
        await bot.send_message(
            chat_id=address, text=text, reply_markup=markup, parse_mode=None
        )
        state = "sent"
    except (TelegramBadRequest, TelegramForbiddenError):
        state = "failed"
    except Exception:
        state = "unknown"
    async with service.transactions.transaction() as session:
        await _session(session).execute(
            update(NOTICES)
            .where(NOTICES.c.invite_id == identity, NOTICES.c.kind == kind)
            .values(state=state)
        )
    return state


async def dispatch_invite(config, service, identity):
    from aiogram import Bot

    if service is None:
        raise ValueError("invite_handoff_unavailable")
    async with Bot(token=config.bot.bot_token).context() as bot:
        sent = await deliver_invite_notice(service, bot, identity, "creator")
        await deliver_invite_notice(service, bot, identity, "customer")
    if sent is not None:
        return sent
    async with service.transactions.transaction() as session:
        return await _session(session).scalar(
            select(NOTICES.c.state).where(
                NOTICES.c.invite_id == identity, NOTICES.c.kind == "creator"
            )
        )
