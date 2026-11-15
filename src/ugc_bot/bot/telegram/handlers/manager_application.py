"""The application lives in the bot chat and resumes from the last answer."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
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
    application_fields,
)

router = Router()
PREFIX = "mgr:"
CONSENT = (
    "Отправляя заявку, вы соглашаетесь на обработку анкеты для отбора "
    "и готовы фиксировать сроки, результаты и согласованные расходы в UMC."
)
LABELS = {
    "name": "Имя",
    "rate": "Ожидаемая ставка",
    "work_format": "Формат работы",
    "work_format_details": "Другой формат работы",
    "weekly_capacity": "Авторов в неделю",
    "location": "Страна и город",
    "phone": "Телефон",
    "instagram": "Instagram",
    "case": "Кейс",
    "settlement": "Расчёт",
    "reliability": "Действия при срыве",
}
BUTTON_CHOICES = {
    **FIELD_CHOICES,
    "rate": ("Обсудим",),
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
        "submitted": "Заявка на рассмотрении.",
        "clarify": "Команда попросила уточнить заявку.",
        "approved": (
            "Вы в списке менеджеров. Назначенные заказы доступны "
            "в разделе «Менеджер» Mini App. Откройте приложение через /app."
        ),
        "declined": (
            "Заявка отклонена. Можно обновить ответы и подать её повторно."
        ),
    }.get(row["state"], INTRO)
    if row["decision_note"]:
        status += "\n\n" + row["decision_note"]
    if row["state"] == "approved":
        await message.answer(status, parse_mode=None)
        return
    actions = []
    if row["state"] != "submitted":
        actions.append([button("Заполнить или продолжить", "next")])
    if row["instagram"] and not row["instagram_verified_at"]:
        actions.append([button("Подтвердить Instagram", "instagram")])
    if row["instagram_verified_at"]:
        status += "\n\nInstagram подтверждён."
    actions.append(
        [
            InlineKeyboardButton(
                text="Как устроена работа",
                url="https://usemycontent.ru/partner",
            )
        ]
    )
    await message.answer(
        status, reply_markup=keyboard(actions), parse_mode=None
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


async def ask(message, state, row, field=None, config=None):
    if row["state"] in {"submitted", "approved"}:
        await state.clear()
        await show(message, row)
        return
    answers = row["answers"]
    fields = application_fields(answers)
    field = field or next((key for key in fields if key not in answers), None)
    if field:
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
        prompt = FIELDS[field][0]
        if field == "case" and answers.get("work_format") in {
            "Агентство",
            "В команде бренда",
        }:
            prompt += " Можете добавить, какие проекты ведёт ваша команда."
        await message.answer(prompt, reply_markup=markup, parse_mode=None)
        return
    await state.clear()
    rows = [[button("Отправить заявку", "submit"), button("Изменить", "edit")]]
    privacy = config.docs.docs_privacy_url
    if privacy.startswith("https://"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="Политика конфиденциальности", url=privacy
                )
            ]
        )
    lines = [f"{LABELS[field]} · {answers[field]}" for field in fields]
    await message.answer(
        "\n\n".join(["Проверьте заявку", "\n".join(lines), CONSENT]),
        reply_markup=keyboard(rows),
        parse_mode=None,
    )


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
        await state.clear()
        await show(message, row)
    elif action == "next":
        await ask(message, state, row, config=config)
    elif action == "edit" and row["state"] not in {"submitted", "approved"}:
        await message.answer(
            "Что изменить?",
            reply_markup=keyboard(
                [[button(LABELS[key], "field:" + key)] for key in fields]
            ),
        )
    elif field == "field" and index in fields:
        await ask(message, state, row, field=index, config=config)
    elif separator and field in BUTTON_CHOICES:
        if (await state.get_data()).get("field") != field:
            return
        options = BUTTON_CHOICES[field]
        if index not in {str(i) for i in range(len(options))}:
            return
        value = "Не указано" if field == "coverage" else options[int(index)]
        await service.answer(user_id, field, value)
        await ask(message, state, await service.open(user_id), config=config)
    elif action == "submit":
        if any(key not in row["answers"] for key in fields):
            await ask(message, state, row, config=config)
            return
        await service.submit(user_id)
        await state.clear()
        await show(message, await service.open(user_id))
    elif action == "instagram":
        code = await service.instagram_challenge(user_id)
        if not code:
            await show(message, await service.open(user_id))
            return
        target = config.instagram.admin_instagram_username.strip().lstrip("@")
        if not target:
            await message.answer("Проверка Instagram временно недоступна.")
            return
        await message.answer(
            f"Отправьте код {code} в Direct аккаунту @{target} "
            "с Instagram, указанного в анкете. Код действует 15 минут. "
            "Проверьте статус в /manager.",
            parse_mode=None,
        )


@router.message(
    ManagerForm.answer, F.contact | (F.text & ~F.text.startswith("/"))
)
async def manager_application_answer(
    message, state, user_role_service, config, manager_applications=None
):
    if message.chat.type != "private" or manager_applications is None:
        return
    user = await _user(user_role_service, message.from_user.id)
    if user is None:
        return
    field = (await state.get_data()).get("field")
    if field not in FIELDS:
        await state.clear()
        return
    if field == "phone":
        contact = message.contact
        if not contact or contact.user_id != message.from_user.id:
            await message.answer(
                "Нажмите «Поделиться номером», "
                "чтобы продолжить анкету менеджера.",
                reply_markup=PHONE_KEYBOARD,
            )
            return
        value = contact.phone_number
    elif field in FIELD_CHOICES:
        await message.answer("Выберите один из вариантов кнопкой.")
        return
    elif not message.text:
        await message.answer("Введите ответ на вопрос текстом.")
        return
    else:
        value = message.text
    try:
        await manager_applications.answer(user.user_id, field, value)
    except ValueError:
        await message.answer(
            "Проверьте формат и длину ответа. " + FIELDS[field][0]
        )
        return
    if field == "phone":
        await message.answer(
            "Номер сохранён.", reply_markup=ReplyKeyboardRemove()
        )
    await ask(
        message,
        state,
        await manager_applications.open(user.user_id),
        config=config,
    )
