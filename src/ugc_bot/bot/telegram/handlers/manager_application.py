"""The application lives in the bot chat and resumes from the last answer."""

import logging
from html import escape
from secrets import token_hex
from urllib.parse import quote
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ADV_AGREE,
    CALLBACK_ADV_START,
    CALLBACK_COUNTRY_PREFIX,
    CALLBACK_CREATOR_CREATE,
    CALLBACK_ROLE_ADVERTISER,
    CALLBACK_ROLE_CREATOR,
)
from ugc_bot.bot.telegram.manager_review_messages import (
    REVIEW_PAGE_SIZE,
    REVIEW_PREFIX,
    manager_workspace_keyboard,
    review_message,
    review_queue_cursor,
    review_queue_message,
)
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.domain.manager_application import (
    FIELD_CHOICES,
    FIELDS,
    INTRO,
    MANAGER_FIELD_LABELS,
    MANAGER_PROGRAM_URL,
    WRITTEN_FIELDS,
    application_fields,
    missing_application_fields,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    build_keyboard_markup,
)

router = Router()
logger = logging.getLogger(__name__)
PREFIX = "mgr:"
BUTTON_CHOICES = {
    **FIELD_CHOICES,
    "coverage": ("Пропустить",),
}
PHONE_KEYBOARD = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Поделиться номером", request_contact=True)]
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


class ManagerForm(StatesGroup):
    welcome = State()
    answer = State()


active_manager_form = StateFilter(ManagerForm.welcome, ManagerForm.answer)


def button(text, action):
    return InlineKeyboardButton(text=text, callback_data=PREFIX + action)


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_workspace(message, config, title, *, can_review=False):
    workspace = manager_workspace_keyboard(config)
    body = (
        "В базе появятся креаторы, пришедшие по вашей личной ссылке."
        if workspace.rows
        else "Mini App временно недоступен. Повторите /manager позже."
    )
    markup = build_keyboard_markup(workspace)
    if can_review:
        markup.inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="Заявки менеджеров",
                    callback_data=f"{REVIEW_PREFIX}q",
                )
            ]
        )
    await message.answer(
        f"<b>{title}</b>\n\n{body}",
        reply_markup=markup if markup.inline_keyboard else None,
        parse_mode="HTML",
    )


async def show(message, row, config):
    status = {
        "submitted": (
            "<b>Заявка на рассмотрении.</b>"
            if row["instagram_verified_at"]
            else "<b>Заявка получена.</b>"
        ),
        "clarify": "<b>Заявка на рассмотрении.</b>",
        "declined": (
            "<b>Заявка отклонена.</b>\n\n"
            "Можно обновить ответы и подать её повторно."
        ),
    }.get(row["state"], f"<b>Работа менеджера в UMC</b>\n\n{escape(INTRO)}")
    if row["state"] == "approved":
        await show_workspace(
            message, config, "Заявка одобрена. Кабинет менеджера открыт."
        )
        return
    actions = []
    if row["state"] != "submitted":
        actions.append([button("Заполнить или продолжить", "next")])
    if row["state"] in {"clarify", "declined"}:
        actions.append([button("Изменить ответы", "edit")])
    if row["instagram"] and not row["instagram_verified_at"]:
        actions.append([button("Подтвердить Instagram", "instagram")])
    if row["instagram_verified_at"]:
        status += "\n\n<b>Instagram подтверждён.</b>"
        if row["state"] in {"submitted", "clarify"}:
            status += " Текущий статус заявки доступен в /manager."
    elif row["state"] == "submitted":
        status += (
            "\n\nПодтвердите Instagram, чтобы команда могла рассмотреть анкету."
        )
    if row["state"] == "submitted":
        actions.append([button("Проверить статус", "status")])
    if row["state"] == "draft" and not row.get("answers"):
        actions.append(
            [
                InlineKeyboardButton(
                    text="Как устроена работа",
                    url=MANAGER_PROGRAM_URL,
                )
            ]
        )
    await message.answer(
        status,
        reply_markup=keyboard(actions) if actions else None,
        parse_mode="HTML",
    )


@router.message(Command("manager"))
async def open_manager_application(
    message, state, user_role_service, config, manager_applications=None
):
    if message.chat.type != "private":
        return
    user = await _user(user_role_service, message.from_user.id)
    if (
        manager_applications is not None
        and not _active_admin(user)
        and (
            user is None
            or (
                message.from_user.username
                and user.telegram != message.from_user.username
            )
        )
    ):
        user = await user_role_service.set_user(
            external_id=str(message.from_user.id),
            messenger_type=MessengerType.TELEGRAM,
            username=user.username if user else "",
            telegram_username=message.from_user.username,
        )
    if user is not None:
        await show_manager_entry(
            message, state, user, config, manager_applications
        )


def _active_admin(user):
    return (
        user is not None
        and getattr(user, "admin", False)
        and user.status == UserStatus.ACTIVE
    )


async def show_manager_entry(
    message, state, user, config, manager_applications
):
    if _active_admin(user):
        await state.clear()
        await show_workspace(
            message,
            config,
            "Кабинет менеджера открыт.",
            can_review=manager_applications is not None,
        )
    elif manager_applications is not None:
        await show_application(
            message,
            state,
            await manager_applications.open(user.user_id),
            config,
        )
    else:
        return False
    return True


async def show_application(message, state, row, config):
    await state.clear()
    if row["state"] in {"draft", "clarify", "declined"}:
        await state.set_state(ManagerForm.welcome)
    await show(message, row, config)


@router.message(active_manager_form, CommandStart(magic=~F.args))
async def resume_manager_application(
    message, state, user_role_service, config, manager_applications=None
):
    if message.chat.type != "private" or manager_applications is None:
        return
    user = await _user(user_role_service, message.from_user.id)
    if user is None:
        await state.clear()
        await message.answer(
            "Чтобы открыть анкету менеджера, отправьте /manager."
        )
        return
    row = await manager_applications.open(user.user_id)
    if await state.get_state() == ManagerForm.answer.state:
        field = (await state.get_data()).get("field")
        fields = application_fields(row["answers"])
        await ask(
            message,
            state,
            row,
            config,
            field=field if field in fields else None,
        )
    else:
        await show_application(message, state, row, config)


@router.callback_query(
    active_manager_form,
    F.data.in_(
        {
            CALLBACK_ROLE_ADVERTISER,
            CALLBACK_ADV_START,
            CALLBACK_ADV_AGREE,
            CALLBACK_ROLE_CREATOR,
            CALLBACK_CREATOR_CREATE,
        }
    )
    | F.data.startswith(CALLBACK_COUNTRY_PREFIX),
)
async def keep_manager_application_on_callback(callback):
    logger.info("Ignored another onboarding button during manager onboarding")
    await callback.answer(
        "Открыта анкета менеджера. Чтобы сменить роль, отправьте /role.",
        show_alert=True,
    )


async def _user(roles, external_id):
    return await roles.get_user(
        external_id=str(external_id), messenger_type=MessengerType.TELEGRAM
    )


@router.callback_query(F.data.startswith(REVIEW_PREFIX))
async def review_manager_in_telegram(
    callback,
    user_role_service,
    config,
    messenger_client,
    manager_applications=None,
):
    message = callback.message
    if (
        message is None
        or message.chat.type != "private"
        or message.chat.id != callback.from_user.id
        or manager_applications is None
    ):
        await callback.answer()
        return
    actor = await _user(user_role_service, callback.from_user.id)
    if actor is None or not actor.admin or actor.status != UserStatus.ACTIVE:
        await callback.answer(
            "Действие доступно администраторам.", show_alert=True
        )
        return
    action, _, payload = callback.data.removeprefix(REVIEW_PREFIX).partition(
        ":"
    )
    if action == "q":
        try:
            after = review_queue_cursor(payload)
        except (ValueError, OverflowError):
            await callback.answer(
                "Откройте список заявок заново.", show_alert=True
            )
            return
        rows = await manager_applications.review_queue(
            after=after, limit=REVIEW_PAGE_SIZE + 1
        )
        text, markup = review_queue_message(rows, after=after)
        await callback.answer()
        await messenger_client.send_text(
            chat_id=str(message.chat.id), text=text, keyboard=markup
        )
        return
    identity, _, version = payload.partition(":")
    try:
        user_id = UUID(hex=identity)
        expected = int(version) if action == "a" else None
    except ValueError:
        await callback.answer(
            "Ссылка на анкету недействительна.", show_alert=True
        )
        return
    if expected is not None:
        try:
            await manager_applications.approve_in_telegram(
                user_id, actor.user_id, expected
            )
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return
    elif action != "v":
        await callback.answer()
        return
    row = await manager_applications.review_card(user_id)
    if row is None:
        await callback.answer("Анкета не найдена.", show_alert=True)
        return
    await callback.answer("Менеджер принят." if action == "a" else None)
    text, markup = review_message(config, row, full=True)
    await messenger_client.send_text(
        chat_id=str(message.chat.id),
        text=text,
        keyboard=markup,
        parse_mode="HTML",
    )


def question_text(field, work_format=None):
    heading, *paragraphs = map(escape, FIELDS[field][0].split("\n\n"))
    if field == "case" and work_format in {"Агентство", "В команде бренда"}:
        paragraphs[0] += " Можете добавить, какие проекты ведёт ваша команда."
    if field == "shortfall_plan":
        paragraphs[0] = f"<blockquote>{paragraphs[0]}</blockquote>"
    if field in WRITTEN_FIELDS:
        paragraphs[-1] = f"<i>{paragraphs[-1]}</i>"
    return "\n\n".join([f"<b>{heading}</b>", *paragraphs])


async def ask(message, state, row, config, field=None):
    if row["state"] in {"submitted", "approved"}:
        await state.clear()
        await show(message, row, config)
        return
    answers = row["answers"]
    fields = application_fields(answers)
    field = field or next(iter(missing_application_fields(answers)), fields[-1])
    await state.set_state(ManagerForm.answer)
    await state.set_data({"field": field})
    markup = None
    if field == "phone":
        markup = PHONE_KEYBOARD
    elif field in BUTTON_CHOICES:
        markup = keyboard(
            [
                [button(label, f"{field}:{i}")]
                for i, label in enumerate(BUTTON_CHOICES[field])
            ]
        )
    await message.answer(
        question_text(field, answers.get("work_format")),
        reply_markup=markup,
        parse_mode="HTML",
    )


async def send_instagram_challenge(message, service, row, config):
    if row["instagram_verified_at"]:
        await show(message, row, config)
        return
    target = config.instagram.admin_instagram_username.strip().lstrip("@")
    if not target:
        await show(message, row, config)
        await message.answer("Проверка Instagram временно недоступна.")
        return
    code = await service.instagram_challenge(row["user_id"])
    if not code:
        await show(message, await service.open(row["user_id"]), config)
        return
    await message.answer(
        f"<code>{escape(code)}</code>",
        reply_markup=keyboard(
            [
                [
                    InlineKeyboardButton(
                        text="Скопировать код",
                        copy_text=CopyTextButton(text=code),
                    )
                ]
            ]
        ),
        parse_mode="HTML",
    )
    status = (
        "<b>Заявка получена.</b>\n\n" if row["state"] == "submitted" else ""
    )
    await message.answer(
        status + "<b>Подтвердите Instagram</b>\n\n"
        "1. Скопируйте код из сообщения выше.\n"
        f"2. Откройте Direct <b>@{escape(target)}</b> и отправьте код "
        "с аккаунта, указанного в анкете.\n"
        "3. Бот сам сообщит в Telegram, когда Instagram будет подтверждён.\n\n"
        "<i>Код действует 24 часа. При повторном открытии проверки "
        "код остаётся прежним.</i>",
        reply_markup=keyboard(
            [
                [
                    InlineKeyboardButton(
                        text="Открыть Direct",
                        url=f"https://ig.me/m/{quote(target, safe='')}",
                    )
                ],
                [button("Проверить статус", "status")],
            ]
        ),
        parse_mode="HTML",
    )


async def after_answer(message, state, service, row, config):
    if row["state"] == "submitted" and not row["instagram_verified_at"]:
        await state.clear()
        await send_instagram_challenge(message, service, row, config)
        return
    await ask(message, state, row, config)


async def find_city(message, state, query, blogger_registration_service):
    lookup = token_hex(6)
    await state.update_data(city_lookup=lookup, city_candidate=None)
    if len(query) > FIELDS["location"][1] or not any(
        char.isalpha() for char in query
    ):
        await message.answer(question_text("location"), parse_mode="HTML")
        return
    location = (
        await blogger_registration_service.resolve_city_identity(query)
        if blogger_registration_service is not None
        else None
    )
    if (await state.get_data()).get("city_lookup") != lookup:
        return
    if location is None:
        await message.answer(
            "Город не найден. Проверьте название. Если есть тёзки, "
            "добавьте область через запятую."
        )
        return
    await state.update_data(city_candidate=list(location))
    label = ", ".join(dict.fromkeys(part for part in location if part))
    await message.answer(
        f"<b>{escape(label)}</b>\n\nЭто ваш город? "
        "Чтобы выбрать другой, напишите его название.",
        reply_markup=keyboard(
            [[button("Да, выбрать город", f"city:{lookup}")]]
        ),
        parse_mode="HTML",
    )


async def select_city(message, state, service, row, config, index):
    data = await state.get_data()
    if data.get("field") != "location" or data.get("city_lookup") != index:
        return
    location = data.get("city_candidate")
    if not location:
        return
    city, region, country = location
    row = await service.answer(
        row["user_id"], "location", city, location_context=(region, country)
    )
    await after_answer(message, state, service, row, config)


@router.callback_query(F.data.startswith(PREFIX))
async def manager_application_action(
    callback, state, user_role_service, config, manager_applications=None
):
    message = callback.message
    if (
        not message
        or message.chat.id != callback.from_user.id
        or manager_applications is None
    ):
        await callback.answer()
        return
    user = await _user(user_role_service, callback.from_user.id)
    if user is None:
        await callback.answer("Откройте /manager", show_alert=True)
        return
    service = manager_applications
    row = await service.open(user.user_id)
    action = callback.data.removeprefix(PREFIX)
    await callback.answer()
    try:
        await _action(action, message, state, service, row, config)
    except ValueError as exc:
        await message.answer(str(exc), parse_mode=None)


async def _action(  # noqa: C901
    action, message, state, service, row, config
):
    user_id = row["user_id"]
    field, separator, index = action.partition(":")
    fields = application_fields(row["answers"])
    if action == "open":
        await show_application(message, state, row, config)
    elif action == "status":
        await show(message, row, config)
    elif action in {"next", "submit"}:
        await ask(message, state, row, config)
    elif action == "edit" and row["state"] not in {"submitted", "approved"}:
        await message.answer(
            "Что изменить?",
            reply_markup=keyboard(
                [
                    [button(MANAGER_FIELD_LABELS[key], "field:" + key)]
                    for key in fields
                ]
            ),
        )
    elif field == "field" and index in fields:
        await ask(message, state, row, config, field=index)
    elif field == "city":
        await select_city(message, state, service, row, config, index)
    elif separator and field in BUTTON_CHOICES:
        if (await state.get_data()).get("field") != field:
            return
        options = BUTTON_CHOICES[field]
        if index not in {str(i) for i in range(len(options))}:
            return
        value = "Не указано" if field == "coverage" else options[int(index)]
        row = await service.answer(user_id, field, value)
        await after_answer(message, state, service, row, config)
    elif action == "instagram":
        await send_instagram_challenge(message, service, row, config)


def answer_text(message, field):
    if field == "phone":
        contact = message.contact
        if not contact or contact.user_id != message.from_user.id:
            raise ValueError(
                "Нажмите «Поделиться номером», "
                "чтобы продолжить анкету менеджера."
            )
        return contact.phone_number
    if field in FIELD_CHOICES:
        raise ValueError("Выберите один из вариантов кнопкой.")
    if not message.text:
        raise ValueError("Введите ответ на вопрос текстом.")
    return message.text


@router.message(
    ManagerForm.answer, F.contact | (F.text & ~F.text.startswith("/"))
)
async def manager_application_answer(
    message,
    state,
    user_role_service,
    config,
    manager_applications=None,
    blogger_registration_service=None,
):
    if message.chat.type != "private" or manager_applications is None:
        return
    user = await _user(user_role_service, message.from_user.id)
    if user is None:
        return
    field = (await state.get_data()).get("field")
    if field in {"reliability", "coverage"}:
        await ask(
            message,
            state,
            await manager_applications.open(user.user_id),
            config,
        )
        return
    if field not in FIELDS:
        await state.clear()
        return
    try:
        value = answer_text(message, field)
    except ValueError as exc:
        markup = PHONE_KEYBOARD if field == "phone" else None
        await message.answer(str(exc), reply_markup=markup)
        return
    if field == "location":
        await find_city(
            message, state, value.strip(), blogger_registration_service
        )
        return
    try:
        row = await manager_applications.answer(user.user_id, field, value)
    except ValueError as exc:
        await message.answer(
            f"<i>{escape(str(exc))}</i>\n\n{question_text(field)}",
            reply_markup=PHONE_KEYBOARD if field == "phone" else None,
            parse_mode="HTML",
        )
        return
    if field == "phone":
        await message.answer(
            "Номер сохранён.", reply_markup=ReplyKeyboardRemove()
        )
    await after_answer(message, state, manager_applications, row, config)
