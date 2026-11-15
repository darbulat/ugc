"""The application lives in the bot chat and resumes from the last answer."""

from html import escape
from secrets import token_hex
from urllib.parse import quote

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from ugc_bot.domain.enums import MessengerType
from ugc_bot.domain.manager_application import (
    FIELD_CHOICES,
    FIELDS,
    INTRO,
    WRITTEN_FIELDS,
    application_fields,
    missing_application_fields,
)

router = Router()
PREFIX = "mgr:"
LABELS = {
    "name": "Имя",
    "rate": "Ожидаемая ставка",
    "work_format": "Формат работы",
    "work_format_details": "Другой формат работы",
    "weekly_capacity": "Авторов в неделю",
    "location": "Город",
    "phone": "Телефон",
    "instagram": "Instagram",
    "case": "Кейс",
    "settlement": "Расчёт",
    "shortfall_plan": "Если не хватает блогеров",
}
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
    answer = State()


def button(text, action):
    return InlineKeyboardButton(text=text, callback_data=PREFIX + action)


def keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show(message, row):
    status = {
        "submitted": "<b>Заявка на рассмотрении.</b>",
        "clarify": "<b>Команда попросила уточнить заявку.</b>",
        "approved": (
            "<b>Вы в списке менеджеров.</b>\n\nНазначенные заказы доступны "
            "в разделе «Менеджер» Mini App. Откройте приложение через /app."
        ),
        "declined": (
            "<b>Заявка отклонена.</b>\n\n"
            "Можно обновить ответы и подать её повторно."
        ),
    }.get(row["state"], f"<b>Работа менеджера в UMC</b>\n\n{escape(INTRO)}")
    if row["decision_note"]:
        status += f"\n\n<blockquote>{escape(row['decision_note'])}</blockquote>"
    if row["state"] == "approved":
        await message.answer(status, parse_mode="HTML")
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
    elif row["state"] == "submitted":
        status += "\n\nInstagram ожидает подтверждения."
    if row["state"] == "submitted":
        actions.append([button("Проверить статус", "status")])
    if row["state"] == "draft" and not row.get("answers"):
        actions.append(
            [
                InlineKeyboardButton(
                    text="Как устроена работа",
                    url="https://usemycontent.ru/partner",
                )
            ]
        )
    await message.answer(
        status,
        reply_markup=keyboard(actions) if actions else None,
        parse_mode="HTML",
    )


@router.message(CommandStart(deep_link=True, magic=F.args == "manager"))
@router.message(Command("manager"))
async def open_manager_application(
    message, state, user_role_service, config, manager_applications=None
):
    if message.chat.type != "private" or manager_applications is None:
        return
    await state.clear()
    user = await _user(user_role_service, message.from_user.id)
    if user is None or (
        message.from_user.username
        and user.telegram != message.from_user.username
    ):
        user = await user_role_service.set_user(
            external_id=str(message.from_user.id),
            messenger_type=MessengerType.TELEGRAM,
            username=user.username if user else "",
            telegram_username=message.from_user.username,
        )
    await show(message, await manager_applications.open(user.user_id))


async def _user(roles, external_id):
    return await roles.get_user(
        external_id=str(external_id), messenger_type=MessengerType.TELEGRAM
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


async def ask(message, state, row, field=None):
    if row["state"] in {"submitted", "approved"}:
        await state.clear()
        await show(message, row)
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
        await show(message, row)
        return
    target = config.instagram.admin_instagram_username.strip().lstrip("@")
    if not target:
        await show(message, row)
        await message.answer("Проверка Instagram временно недоступна.")
        return
    code = await service.instagram_challenge(row["user_id"])
    if not code:
        await show(message, await service.open(row["user_id"]))
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
        "<b>Заявка на рассмотрении.</b>\n\n"
        if row["state"] == "submitted"
        else ""
    )
    await message.answer(
        status + "<b>Подтвердите Instagram</b>\n\n"
        "1. Скопируйте код из сообщения выше.\n"
        f"2. Откройте Direct <b>@{escape(target)}</b> и отправьте код "
        "с аккаунта, указанного в анкете.\n"
        "3. Вернитесь сюда и нажмите «Проверить статус».\n\n"
        "<i>Код действует 15 минут с момента выдачи.</i>",
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
    await ask(message, state, row)


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
    if action in {"open", "status"}:
        if action == "open":
            await state.clear()
        await show(message, row)
    elif action in {"next", "submit"}:
        await ask(message, state, row)
    elif action == "edit" and row["state"] not in {"submitted", "approved"}:
        await message.answer(
            "Что изменить?",
            reply_markup=keyboard(
                [[button(LABELS[key], "field:" + key)] for key in fields]
            ),
        )
    elif field == "field" and index in fields:
        await ask(message, state, row, field=index)
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
        await ask(message, state, await manager_applications.open(user.user_id))
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
