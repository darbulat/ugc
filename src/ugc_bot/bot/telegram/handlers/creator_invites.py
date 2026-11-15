"""A private start link reuses the standard creator registration flow."""

from logging import getLogger
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
)
from ugc_bot.domain.creator_invites import invite_id
from ugc_bot.domain.enums import MessengerType
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.repositories.invite_preview import (
    PREVIEW_CONSENT,
)

logger = getLogger(__name__)
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
        row = await service.open_invite(
            identity, user.user_id if user else None
        )
    except ValueError:
        await message.answer(
            "Приглашение недоступно. Попросите менеджера проверить ссылку.",
            parse_mode=None,
        )
        return
    if (
        row["consented_at"] is not None
        or row.get("consent_source") == PREVIEW_CONSENT
    ):
        await message.answer(
            "Вы уже подтвердили участие в этом заказе.", parse_mode=None
        )
        if user is not None:
            await send_creator_contact(message, service, identity, user.user_id)
        return
    if str(row["status"]) != "active":
        await message.answer("Заказ закрыт. Отклик больше не принимается.")
        return
    text, keyboard = invitation_text(row, payload)
    if row.get("reported_at"):
        text += (
            "\n\nМенеджер уже отметил ваше согласие. "
            "Здесь можно подтвердить участие через бота."
        )
    await message.answer(text, reply_markup=keyboard, parse_mode=None)


ERRORS = {
    "creator_invite_preview_telegram_required": (
        "Добавьте имя пользователя в Telegram и откройте бота заново."
    ),
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
    "creator_invite_use_personal_link": (
        "Подтвердите участие по персональной ссылке от менеджера."
    ),
    "creator_invite_already_interested": (
        "Ваш отклик на этот заказ уже есть. Напишите менеджеру."
    ),
}


async def send_creator_contact(message, service, identity, user_id):
    contact = await service.creator_contact(identity, user_id)
    if contact is None:
        await message.answer(
            "Если нужно обсудить детали, напишите тому, кто пригласил вас.",
            parse_mode=None,
        )
        return
    role, handle = contact
    await message.answer(f"{role} · {handle}", parse_mode=None)


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
        identity = invite_id((callback.data or "")[len(PREFIX) :])
        await creator_invite_service.accept(identity, user.user_id)
    except ValueError as exc:
        await callback.answer(
            ERRORS.get(str(exc), "Приглашение недоступно. Напишите менеджеру."),
            show_alert=True,
        )
        return
    await callback.answer("Участие подтверждено.", show_alert=True)
    if isinstance(message, Message):
        try:
            await send_creator_contact(
                message, creator_invite_service, identity, user.user_id
            )
        except (TelegramAPIError, TimeoutError):
            logger.warning("Creator contact message was not confirmed")
    bot = callback.bot
    if bot is not None:
        if isinstance(message, Message):
            from ugc_bot.application.services.invite_handoff_notices import (
                deliver_invite_notice,
            )

            await deliver_invite_notice(
                creator_invite_service, bot, identity, "customer"
            )
        notice = await creator_invite_service.claim_manager_notice(identity)
        if notice is not None:
            address, order_id, ordinal = notice
            try:
                await bot.send_message(
                    chat_id=address,
                    text=(
                        "Креатор подтвердил участие в заказе "
                        f"{public_order_number(order_id)}, позиция №{ordinal}. "
                        "Откройте «Менеджер → Мои заказы» в приложении."
                    ),
                    parse_mode=None,
                )
            except (TelegramAPIError, TimeoutError) as exc:
                logger.warning(
                    "Manager confirmation notice not confirmed (%s)",
                    type(exc).__name__,
                )


async def _preview_card(event, roles, service, order_id):
    if service is None:
        raise PermissionError("creator_invite_unavailable")
    external_id = str(event.from_user.id)
    user = await roles.get_user(
        external_id=external_id, messenger_type=MessengerType.TELEGRAM
    )
    if user is None:
        raise PermissionError("creator_invite_unavailable")
    principal = AuthenticatedMessengerPrincipal(
        user.user_id, "telegram", external_id
    )
    rows = await service.preview_card(principal, order_id)
    lines = [
        f"Итоги тестового заказа {public_order_number(order_id)}",
        "Проверка приглашений. Без оплаты и рассылки.",
    ]
    for row in rows:
        if row.telegram is None:
            lines.append(f"№{row.ordinal} · Ожидает контакта")
            continue
        source = (
            "Подтверждено в боте"
            if row.consent_source == PREVIEW_CONSENT
            else "Согласие получено в переписке"
        )
        name = f"\n{row.creator_name}" if row.creator_name else ""
        lines.append(
            f"№{row.ordinal} · {source}{name}\n"
            f"Instagram: @{row.instagram}\nTelegram: @{row.telegram}"
        )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Обновить", callback_data=f"ip:{order_id.hex}"
                )
            ],
            [
                InlineKeyboardButton(text=label, callback_data=action)
                for label, action in sharing_buttons(order_id)
            ],
        ]
    )
    return "\n\n".join(lines), markup


@router.message(
    CommandStart(deep_link=True, magic=F.args.regexp(r"^ip_[0-9a-f]{32}$"))
)
async def open_preview_card(
    message: Message,
    command: CommandObject,
    user_role_service,
    creator_invite_service=None,
):
    if message.from_user is None or message.chat.id != message.from_user.id:
        return
    try:
        text, markup = await _preview_card(
            message,
            user_role_service,
            creator_invite_service,
            UUID(hex=(command.args or "")[3:]),
        )
    except (ValueError, PermissionError):
        await message.answer("Тестовый заказ недоступен.")
        return
    await message.answer(text, reply_markup=markup, parse_mode=None)


@router.callback_query(F.data.regexp(r"^ip:[0-9a-f]{32}$"))
async def refresh_preview_card(
    callback: CallbackQuery, user_role_service, creator_invite_service=None
):
    message = callback.message
    if (
        not isinstance(message, Message)
        or message.chat.id != callback.from_user.id
    ):
        await callback.answer()
        return
    try:
        text, markup = await _preview_card(
            callback,
            user_role_service,
            creator_invite_service,
            UUID(hex=(callback.data or "")[3:]),
        )
        await message.edit_text(text, reply_markup=markup, parse_mode=None)
    except (ValueError, PermissionError):
        await callback.answer("Тестовый заказ недоступен.", show_alert=True)
        return
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            raise
    await callback.answer()


@router.message(
    CommandStart(deep_link=True, magic=F.args.regexp(r"^ir_[0-9a-f]{32}$"))
)
async def open_invite_order(
    message: Message,
    command: CommandObject,
    user_role_service,
    creator_invite_service=None,
    order_summary_service=None,
):
    if message.from_user is None or message.chat.id != message.from_user.id:
        return
    order = UUID(hex=(command.args or "")[3:])
    try:
        text, markup = await _preview_card(
            message, user_role_service, creator_invite_service, order
        )
    except (ValueError, PermissionError):
        from ugc_bot.bot.telegram.handlers.order_summary import summary_button

        if order_summary_service is None or creator_invite_service is None:
            return
        external_id = str(message.from_user.id)
        user = await user_role_service.get_user(
            external_id=external_id, messenger_type=MessengerType.TELEGRAM
        )
        if user is None:
            return
        principal = AuthenticatedMessengerPrincipal(
            user.user_id, "telegram", external_id
        )
        try:
            await order_summary_service.view(principal, order)
        except (ValueError, PermissionError):
            await message.answer("Заказ недоступен.")
            return
        button = summary_button(order)
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=button.text, callback_data=button.callback_data
                    )
                ]
            ]
        )
        text = f"Заказ {public_order_number(order)}"
    await message.answer(text, reply_markup=markup, parse_mode=None)


@router.callback_query(F.data.regexp(r"^ic:[0-9a-f]{32}:[01]$"))
async def change_invite_sharing(
    callback: CallbackQuery,
    user_role_service,
    creator_invite_service=None,
):
    message = callback.message
    if (
        not isinstance(message, Message)
        or message.chat.id != callback.from_user.id
    ):
        await callback.answer()
        return
    user = await user_role_service.get_user(
        external_id=str(callback.from_user.id),
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None or creator_invite_service is None:
        await callback.answer("Заказ недоступен.", show_alert=True)
        return
    _, order, action = (callback.data or "").split(":")
    principal = AuthenticatedMessengerPrincipal(
        user.user_id, "telegram", str(callback.from_user.id)
    )
    try:
        await creator_invite_service.client_sharing(
            principal, UUID(hex=order), action == "1"
        )
    except PermissionError:
        await callback.answer("Заказ недоступен.", show_alert=True)
        return
    except ValueError:
        await callback.answer(
            "Укажите @username в Telegram и снова откройте бота.",
            show_alert=True,
        )
        return
    await callback.answer(
        "Креаторам после подтверждения доступен ваш Telegram."
        if action == "1"
        else "Ваш Telegram скрыт.",
        show_alert=True,
    )


def sharing_buttons(order):
    return [
        ("Разрешить мой Telegram", f"ic:{order.hex}:1"),
        ("Скрыть мой Telegram", f"ic:{order.hex}:0"),
    ]


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
