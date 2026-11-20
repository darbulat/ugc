"""Deliver a creator's counteroffer to the named Telegram administrator."""

from dataclasses import dataclass
from decimal import Decimal
from re import fullmatch
from urllib.parse import urlsplit
from uuid import UUID

from aiogram import Bot
from sqlalchemy import select

from ugc_bot.application.services.business_order_card import order_card_url
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.offer_intake import intake_open, reserve_notice
from ugc_bot.infrastructure.db.models import OrderModel, UserModel
from ugc_bot.infrastructure.db.order_selection import picked_order_count
from ugc_bot.infrastructure.db.repositories.admin_recipients import (
    active_admin_telegram_address,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
)

_STATUS = {
    OrderStatus.ACTIVE: "Активный",
    OrderStatus.CLOSED: "Закрыт",
    OrderStatus.NEW: "Новый",
    OrderStatus.PENDING_MODERATION: "На модерации",
}


@dataclass(frozen=True, slots=True)
class _CounterofferMessage:
    address: str
    text: str
    action_url: str
    action_label: str = "Открыть заказ"
    channel: str = "telegram"
    address_kind: str = "chat_id"


def _money(value: str) -> str:
    return (
        f"{Decimal(value):,.2f}".replace(",", " ")
        .replace(".", ",")
        .removesuffix(",00")
    )


@dataclass(slots=True)
class CounterofferAdminDelivery:
    config: AppConfig

    async def __call__(self, event: OutboxEvent, session: object) -> None:
        order_id = UUID(event.aggregate_id)
        creator_id = UUID(event.payload["creator_id"])
        db = _session(session)
        order = (
            await db.execute(
                select(
                    OrderModel.offer_text,
                    OrderModel.status,
                    OrderModel.offer_reserve_until,
                    OrderModel.dispatch_stopped,
                    OrderModel.bloggers_needed,
                    picked_order_count().label("picked"),
                    UserModel.username,
                    UserModel.telegram,
                )
                .select_from(OrderModel)
                .outerjoin(UserModel, UserModel.user_id == creator_id)
                .where(
                    OrderModel.order_id == order_id,
                    OrderModel.status != OrderStatus.DELETED,
                )
            )
        ).one_or_none()
        if order is None:
            return
        address = await active_admin_telegram_address(db, "kamilbakhteev")
        if not address or not fullmatch(r"[1-9][0-9]{0,15}", address):
            raise ValueError("counteroffer_admin_telegram_unavailable")
        base = order_card_url(
            self.config.admin.admin_base_url.strip().rstrip("/")
        )
        if not base or urlsplit(base).scheme != "https":
            raise ValueError("counteroffer_admin_url_unavailable")
        if not urlsplit(base).path:
            base += "/admin"

        currency = event.payload["currency"]
        symbol = "₽" if currency == "RUB" else currency
        title = " ".join(order.offer_text.split())[:140] or "Заказ"
        name = " ".join((order.username or "").split())[:120] or "Креатор"
        handle = (order.telegram or "").strip().lstrip("@")
        if fullmatch(r"[A-Za-z0-9_]{1,32}", handle) and name != f"@{handle}":
            name += f" · @{handle}"
        text = (
            f"Новая цена от креатора\n{title}\n{name}\n"
            f"Просит {_money(event.payload['amount'])} {symbol} "
            f"(в оффере {_money(event.payload['offer_price'])} {symbol})\n"
            f"Занято {order.picked} из {order.bloggers_needed} · "
            f"Осталось {max(order.bloggers_needed - order.picked, 0)}\n"
            f"{_STATUS[order.status]}"
        )
        if order.offer_reserve_until is not None:
            text += "\n" + (
                reserve_notice(order.offer_reserve_until)
                if intake_open(
                    order.status,
                    order.dispatch_stopped,
                    order.offer_reserve_until,
                )
                else "Набор завершён"
            )
        async with Bot(token=self.config.bot.bot_token).context() as bot:
            await TelegramNoticeReceipts(bot, use_web_app=False).send(
                _CounterofferMessage(address, text, f"{base}/orders/{order_id}")
            )
