"""A private start link reuses the standard creator registration flow."""

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.domain.creator_invites import invite_id
from ugc_bot.domain.enums import MessengerType
from ugc_bot.domain.order_display import public_order_number

router = Router()
PREFIX = "oi:"


def invitation_text(row, payload):
    text = f"Приглашение в заказ {public_order_number(row['order_id'])}\n\n"
    text += (row["offer_text"] or "Условия уточнит менеджер.")[:2000]
    if row["geography"]:
        text += f"\n\nГеография: {row['geography'][:200]}"
    text += (
        f"\n\nInstagram для этого приглашения: @{row['instagram']}. "
        "Чтобы участвовать, подтвердите профиль и разрешите показать "
        "заказчику ваше имя, Instagram и контакты из анкеты."
    )
    button = InlineKeyboardButton(
        text="Участвую и разрешаю передать контакт",
        callback_data=f"{PREFIX}{payload}",
    )
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


async def show_invite(message, user_role_service, service, payload):
    user = await user_role_service.get_user(
        external_id=str(message.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    try:
        identity = invite_id(payload)
        row = await service.preview(identity, user.user_id if user else None)
    except ValueError:
        await message.answer(
            "Приглашение недоступно. Попросите менеджера проверить ссылку.",
            parse_mode=None,
        )
        return
    if row["consented_at"] is not None:
        await message.answer(
            "Вы уже подтвердили участие в этом заказе.", parse_mode=None
        )
        return
    text, keyboard = invitation_text(row, payload)
    await message.answer(text, reply_markup=keyboard, parse_mode=None)


ERRORS = {
    "selection_verified_creator_required": (
        "Сначала выберите «Креатор», заполните анкету и подтвердите Instagram. "
        "Затем вернитесь к этой кнопке."
    ),
    "creator_invite_instagram_mismatch": (
        "Подтвердите Instagram, указанный в приглашении."
    ),
    "creator_invite_position_unavailable": (
        "Позиция уже занята. Напишите менеджеру."
    ),
    "creator_invite_already_interested": (
        "Ваш отклик на этот заказ уже есть. Напишите менеджеру."
    ),
}


@router.callback_query(lambda c: bool(c.data and c.data.startswith(PREFIX)))
async def accept_creator_invite(
    callback: CallbackQuery, user_role_service, creator_invite_service=None
):
    message = callback.message
    if (
        not message
        or message.chat.id != callback.from_user.id
        or creator_invite_service is None
    ):
        await callback.answer("Приглашение недоступно.", show_alert=True)
        return
    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer(
            ERRORS["selection_verified_creator_required"], show_alert=True
        )
        return
    try:
        await creator_invite_service.accept(
            invite_id((callback.data or "")[len(PREFIX) :]), user.user_id
        )
    except ValueError as exc:
        await callback.answer(
            ERRORS.get(str(exc), "Приглашение недоступно. Напишите менеджеру."),
            show_alert=True,
        )
        return
    await callback.answer("Участие подтверждено.", show_alert=True)


class CardContactTransport:
    """A customer tap displays the contact in the existing private card."""

    def __init__(self, messenger, chat_id, message_id, header, keyboard):
        self.messenger = messenger
        self.chat_id = chat_id
        self.message_id = message_id
        self.header = header
        self.keyboard = keyboard

    async def send(self, attempt):
        if attempt.channel != "telegram" or str(attempt.address) != str(
            self.chat_id
        ):
            raise DeliveryFailure("card_address_changed", uncertain=False)
        try:
            await self.messenger.edit_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=self.header + "\n\n" + attempt.text,
                keyboard=self.keyboard,
            )
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
        return DeliveryReceipt(
            "telegram", f"order-card:{self.chat_id}:{attempt.interest_id}"
        )
