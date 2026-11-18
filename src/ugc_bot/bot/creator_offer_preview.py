"""Private admin previews depend only on user/order reads and card transport."""

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from ugc_bot.application.creator_offer_cards import NEUTRAL_COVER, OfferCard
from ugc_bot.application.creator_offer_preview import (
    PREVIEW_ACTIONS,
    PREVIEW_CALLBACK_PREFIX,
    render_offer_preview,
)
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    OfferCardTransport,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus

ACCESS_DENIED = "Предпросмотр доступен только администратору в личном чате."
NOT_READY = "Карточка недоступна. Проверьте ID и заполнение заказа в админке."


@dataclass
class CreatorOfferPreview:
    orders: OrderRepository
    users: UserRoleService
    messenger: MessengerClient
    locale: str = "ru"

    async def _allowed(self, user: IncomingUser, chat_id: str) -> bool:
        if (
            user.messenger_type != MessengerType.TELEGRAM
            or not user.external_id.isdecimal()
            or int(user.external_id) <= 0
            or chat_id != user.external_id
        ):
            return False
        actor = await self.users.get_user(
            external_id=user.external_id,
            messenger_type=user.messenger_type,
        )
        return bool(actor and actor.admin and actor.status == UserStatus.ACTIVE)

    async def _load(
        self, raw_id: str, action: str
    ) -> tuple[Order, OfferCard] | None:
        try:
            order_id = UUID(raw_id)
        except ValueError:
            return None
        order = await self.orders.get_by_id(order_id)
        if (
            order is None
            or order.status == OrderStatus.DELETED
            or not order.creator_offer_card
        ):
            return None
        try:
            card = render_offer_preview(order, self.locale, action)
        except ValueError:
            return None
        return order, card

    async def send(self, incoming: IncomingMessage, raw_id: str) -> str | None:
        if not await self._allowed(incoming.user, incoming.chat_id):
            await self.messenger.send_text(
                chat_id=incoming.chat_id, text=ACCESS_DENIED
            )
            return None
        loaded = await self._load(raw_id, "open")
        if loaded is None:
            await self.messenger.send_text(
                chat_id=incoming.chat_id, text=NOT_READY
            )
            return None
        order, card = loaded
        approved = (order.creator_offer_card or {}).get("photo") == "approved"
        cover = (
            order.product_photo_file_id if approved else None
        ) or NEUTRAL_COVER
        return await cast(OfferCardTransport, self.messenger).send_offer_card(
            incoming.chat_id, card, cover
        )

    async def handle(self, incoming: IncomingCallback) -> None:
        if not await self._allowed(incoming.user, incoming.chat_id):
            await self.messenger.answer_callback(
                callback_id=incoming.callback_id, text=ACCESS_DENIED
            )
            return
        data = incoming.data or ""
        action, _, raw_id = data.removeprefix(
            PREVIEW_CALLBACK_PREFIX
        ).partition(":")
        if (
            not data.startswith(PREVIEW_CALLBACK_PREFIX)
            or action not in PREVIEW_ACTIONS
            or not incoming.message_id
        ):
            await self.messenger.answer_callback(
                callback_id=incoming.callback_id, text=NOT_READY
            )
            return
        loaded = await self._load(raw_id, action)
        if loaded is None:
            await self.messenger.answer_callback(
                callback_id=incoming.callback_id, text=NOT_READY
            )
            return
        _, card = loaded
        await self.messenger.answer_callback(callback_id=incoming.callback_id)
        await cast(OfferCardTransport, self.messenger).edit_offer_card(
            incoming.chat_id, incoming.message_id, card
        )
