"""Telegram application entry, private contact sharing and submission."""

import asyncio
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from aiogram import Bot, Router
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import Update

import ugc_bot.app as bot_app
from tests.helpers.fakes import FakeFSMContext, FakeMessage, FakeUser
from ugc_bot.bot.telegram.handlers.advertiser_registration import (
    AdvertiserRegistrationStates,
)
from ugc_bot.bot.telegram.handlers.manager_application import (
    ManagerForm,
    manager_application_action,
    manager_application_answer,
    open_manager_application,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.manager_application import (
    MIN_WRITTEN_LENGTH,
    missing_application_fields,
    normalize_manager_rate,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)


@pytest.mark.asyncio
async def test_manager_application_uses_private_telegram_profile(config):
    state = FakeFSMContext()
    user = FakeUser(100, "candidate", "Кандидат")
    message = FakeMessage(text="/start manager", user=user)
    message.chat.type = "private"
    uid = object()
    row = dict(
        state="draft",
        decision_note=None,
        instagram=None,
        instagram_verified_at=None,
    )
    service = SimpleNamespace(open=AsyncMock(return_value=row))
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=None),
        set_user=AsyncMock(return_value=SimpleNamespace(user_id=uid)),
    )
    await open_manager_application(message, state, roles, config, service)
    assert roles.set_user.call_args.kwargs["telegram_username"] == "candidate"
    service.open.assert_awaited_once_with(uid)
    intro = message.answers[-1][0]
    assert "ожидаемую ставку" in intro
    assert all(amount not in intro for amount in ("600", "1200", "1 200"))
    assert "продолжить" in message.answers[-1][1].inline_keyboard[0][0].text
    assert (
        message.answers[-1][1].inline_keyboard[1][0].text
        == "Как устроена работа"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("handle", ["kamilbakhteev", "darbulat"])
async def test_active_admin_opens_workspace_without_a_candidate_application(
    config, handle
):
    config.webhook.webhook_base_url = "https://bot.example.test"
    state = FakeFSMContext()
    await state.set_state(ManagerForm.answer)
    message = FakeMessage(text="/manager", user=FakeUser(100, handle, "Admin"))
    message.chat.type = "private"
    roles = SimpleNamespace(
        get_user=AsyncMock(
            return_value=SimpleNamespace(
                user_id=uuid4(),
                telegram=handle,
                admin=True,
                status=UserStatus.ACTIVE,
            )
        ),
        set_user=AsyncMock(),
    )
    applications = SimpleNamespace(open=AsyncMock())

    await open_manager_application(message, state, roles, config, applications)

    assert await state.get_state() is None
    applications.open.assert_not_awaited()
    roles.set_user.assert_not_awaited()
    text, markup = message.answers[-1]
    assert "Кабинет менеджера открыт" in text
    assert [
        item[0].web_app.url.split("?", 1)[1]
        for item in markup.inline_keyboard[:3]
    ] == [
        "view=manager&section=creators",
        "view=manager",
        "view=partner",
    ]
    assert markup.inline_keyboard[3][0].callback_data == "mreview:q:0"


def test_admin_review_queue_exposes_both_pagination_actions():
    from ugc_bot.bot.telegram.manager_review_messages import (
        REVIEW_PAGE_SIZE,
        review_queue_message,
    )

    rows = [
        {"user_id": uuid4(), "name": "", "username": f"Creator {index}"}
        for index in range(REVIEW_PAGE_SIZE + 1)
    ]

    _, markup = review_queue_message(rows, page=1)

    assert len(markup.rows[:-1]) == REVIEW_PAGE_SIZE
    assert markup.rows[0][0].text == "Creator 0"
    assert [button.callback_data for button in markup.rows[-1]] == [
        "mreview:q:0",
        "mreview:q:2",
    ]


@pytest.mark.asyncio
async def test_manager_phone_must_belong_to_telegram_sender(config):
    state = FakeFSMContext()
    await state.set_data({"field": "phone"})
    user = FakeUser(100, "candidate", "Кандидат")
    message = FakeMessage(
        user=user,
        contact=SimpleNamespace(
            user_id=101,
            phone_number="+70000000000",
        ),
    )
    message.chat.type = "private"
    uid = object()
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id=uid))
    )
    service = SimpleNamespace(
        answer=AsyncMock(
            return_value={
                "state": "draft",
                "answers": {
                    "name": "Кандидат",
                    "work_format": "Фрилансер",
                    "rate": "900",
                    "weekly_capacity": "1–10",
                    "location": "Казань",
                    "location_country": "Россия",
                    "phone": "+70000000000",
                },
            }
        ),
    )
    foreign_contact = message.contact
    message.contact = None
    for manual_phone in ("не номер", "+78005550123"):
        message.text = manual_phone
        await manager_application_answer(message, state, roles, config, service)
        service.answer.assert_not_awaited()
        assert await state.get_data() == {"field": "phone"}
        text, keyboard = message.answers[-1]
        assert "анкету менеджера" in text
        assert keyboard.keyboard[0][0].request_contact

    message.contact = foreign_contact
    await manager_application_answer(message, state, roles, config, service)
    service.answer.assert_not_awaited()
    message.contact.user_id = 100
    await manager_application_answer(message, state, roles, config, service)
    service.answer.assert_awaited_once_with(uid, "phone", "+70000000000")
    assert (await state.get_data())["field"] == "instagram"
    assert "Instagram" in message.answers[-1]


@pytest.mark.asyncio
async def test_manager_edits_submits_and_verifies_application(config):
    config.webhook.webhook_base_url = "https://bot.example.test/"
    user = FakeUser(100, "candidate", "Кандидат")
    message = FakeMessage(user=user)
    message.chat.type = "private"
    state = FakeFSMContext()
    row = dict(
        user_id="candidate",
        state="draft",
        decision_note=None,
        instagram="@candidate",
        instagram_verified_at=None,
        answers={"name": "Кандидат"},
    )

    async def answer(_, field, value, *, location_context=None):
        row["answers"][field] = value
        if location_context:
            region, country = location_context
            row["answers"].update(
                location_region=region, location_country=country
            )
        if not missing_application_fields(row["answers"]):
            row["state"] = "submitted"
        return row

    service = SimpleNamespace(
        open=AsyncMock(return_value=row),
        answer=AsyncMock(side_effect=answer),
        instagram_challenge=AsyncMock(return_value="UMCM-ABCDEF123456"),
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id="candidate"))
    )
    callback = SimpleNamespace(
        message=message, from_user=user, answer=AsyncMock()
    )
    geocoder = SimpleNamespace(
        resolve_city_identity=AsyncMock(
            side_effect=[
                None,
                ("Казань", "Татарстан", "Россия"),
                ("Алматы", None, "Казахстан"),
            ]
        )
    )

    async def tap(action):
        callback.data = f"mgr:{action}"
        await manager_application_action(
            callback, state, roles, config, service
        )

    await tap("next")
    assert (await state.get_data())["field"] == "rate"
    assert isinstance(message.answers[-1], str)
    assert message.answers[-1].startswith("<b>Сколько вы хотите получать")
    assert "бриф, подбор и отклики" in message.answers[-1]
    await tap("rate:0")
    assert "rate" not in row["answers"]
    message.text = "900–1500"
    await manager_application_answer(message, state, roles, config, service)
    assert row["answers"]["rate"] == "900–1500"
    assert (await state.get_data())["field"] == "work_format"
    assert [
        buttons[0].text for buttons in message.answers[-1][1].inline_keyboard
    ] == [
        "Фрилансер",
        "Агентство",
        "В команде бренда",
        "Другое",
    ]
    await tap("work_format:3")
    assert (await state.get_data())["field"] == "work_format_details"
    message.text = "Продюсирую проекты с авторами"
    await manager_application_answer(message, state, roles, config, service)
    assert (
        row["answers"]["work_format_details"] == "Продюсирую проекты с авторами"
    )
    assert (await state.get_data())["field"] == "weekly_capacity"
    assert [
        buttons[0].text for buttons in message.answers[-1][1].inline_keyboard
    ] == [
        "0",
        "1–10",
        "11–30",
        "31–100",
        "101+",
    ]
    await tap("weekly_capacity:3")
    assert row["answers"]["weekly_capacity"] == "31–100"
    assert (await state.get_data())["field"] == "location"
    assert "Казань, Москва или Санкт-Петербург" in message.answers[-1]
    message.text = "?"
    await manager_application_answer(
        message, state, roles, config, service, geocoder
    )
    geocoder.resolve_city_identity.assert_not_awaited()
    message.text = "Неизвестный"
    await manager_application_answer(
        message, state, roles, config, service, geocoder
    )
    assert "Город не найден" in message.answers[-1]
    message.text = "казань"
    await manager_application_answer(
        message, state, roles, config, service, geocoder
    )
    assert "Казань, Татарстан, Россия" in message.answers[-1][0]
    old_city = message.answers[-1][1].inline_keyboard[0][0].callback_data
    message.text = "алматы"
    await manager_application_answer(
        message, state, roles, config, service, geocoder
    )
    await tap(old_city.removeprefix("mgr:"))
    assert "location" not in row["answers"]
    city = message.answers[-1][1].inline_keyboard[0][0].callback_data
    await tap(city.removeprefix("mgr:"))
    assert row["answers"]["location"] == "Алматы"
    assert row["answers"]["location_country"] == "Казахстан"
    assert (await state.get_data())["field"] == "phone"
    assert "Поделиться номером" in message.answers[-1][1].keyboard[0][0].text
    await tap("edit")
    assert message.answers[-1][0] == "Что изменить?"
    await tap("field:settlement")
    message.text = "ИП"
    await manager_application_answer(message, state, roles, config, service)
    assert "Выберите один из вариантов" in message.answers[-1]
    await tap("settlement:99")
    assert "settlement" not in row["answers"]
    await tap("settlement:1")
    assert row["answers"]["settlement"] == "ИП"
    await tap("settlement:0")
    assert row["answers"]["settlement"] == "ИП"

    await tap("field:work_format")
    await tap("work_format:1")
    await tap("field:case")
    assert "какие проекты ведёт ваша команда" in message.answers[-1]
    assert "<i>(От 20 символов.)</i>" in message.answers[-1]
    assert "сколько блогеров" in message.answers[-1]
    assert "ссылка на кейс" in message.answers[-1]
    assert "1800" not in message.answers[-1]
    service.answer.side_effect = ValueError(
        f"Напишите от {MIN_WRITTEN_LENGTH} символов."
    )
    message.text = "Коротко"
    await manager_application_answer(message, state, roles, config, service)
    assert f"от {MIN_WRITTEN_LENGTH} символов" in message.answers[-1]
    assert (await state.get_data())["field"] == "case"
    service.answer.side_effect = answer
    row["answers"].update(phone="+70000000000", instagram="candidate")
    message.text = "Я сопровождал десять блогеров для кафе."
    await manager_application_answer(message, state, roles, config, service)
    # An old review message must prompt for the new scenario before submission.
    row["answers"]["coverage"] = "Казань, гастрономия"
    row["answers"]["reliability"] = "Согласую замену."
    await state.set_data({"field": "reliability"})
    message.text = "Старый ответ"
    await manager_application_answer(message, state, roles, config, service)
    assert (await state.get_data())["field"] == "shortfall_plan"
    await tap("submit")
    assert (await state.get_data())["field"] == "shortfall_plan"
    assert row["state"] == "draft"
    assert row["answers"]["coverage"] == "Казань, гастрономия"
    assert "<blockquote>Вы взяли заказ на 30 блогеров." in message.answers[-1]
    assert "UMC подобрала 25." in message.answers[-1]
    assert "почему вы выбрали именно их" in message.answers[-1]
    assert "<i>(От 20 символов." in message.answers[-1]
    message.text = (
        "Уточню у команды сроки и подберу авторов через местные сообщества."
    )
    await manager_application_answer(message, state, roles, config, service)
    code = "UMCM-ABCDEF123456"
    assert len(message.answers) >= 2
    code_text, code_keyboard = message.answers[-2]
    assert code_text == f"<code>{code}</code>"
    assert code_keyboard.inline_keyboard[0][0].copy_text.text == code
    instruction, instruction_keyboard = message.answers[-1]
    assert "<b>Заявка получена.</b>" in instruction
    assert "<i>Код действует 15 минут с момента выдачи.</i>" in instruction
    assert "Бот сам сообщит в Telegram" in instruction
    assert code not in instruction
    direct, status = (row[0] for row in instruction_keyboard.inline_keyboard)
    assert (
        direct.url
        == f"https://ig.me/m/{config.instagram.admin_instagram_username}"
    )
    assert status.callback_data == "mgr:status"
    assert not await state.get_data()
    await tap("submit")
    service.instagram_challenge.assert_awaited_once_with("candidate")
    await state.set_data({"field": "other"})
    await tap("status")
    assert await state.get_data() == {"field": "other"}
    assert "Заявка получена." in message.answers[-1][0]
    assert "Подтвердите Instagram" in message.answers[-1][0]
    retry_button = message.answers[-1][1].inline_keyboard[0][0]
    assert retry_button.callback_data == "mgr:instagram"
    service.instagram_challenge.assert_awaited_once_with("candidate")
    await tap("instagram")
    assert message.answers[-2][0] == f"<code>{code}</code>"
    assert (
        message.answers[-1][1].inline_keyboard[1][0].callback_data
        == "mgr:status"
    )
    row["instagram_verified_at"] = object()
    await tap("status")
    assert "Instagram подтверждён" in message.answers[-1][0]
    assert (
        "Текущий статус заявки доступен в /manager." in message.answers[-1][0]
    )
    await tap("instagram")
    assert "Instagram подтверждён" in message.answers[-1][0]
    assert service.instagram_challenge.await_count == 2
    row.update(state="clarify", decision_note="Уточните <загрузку> & сроки")
    await tap("open")
    assert "Заявка на рассмотрении" in message.answers[-1][0]
    assert "Уточните" not in message.answers[-1][0]
    row["state"] = "approved"
    await tap("status")
    text, markup = message.answers[-1]
    assert "Кабинет менеджера открыт" in text
    assert "Уточните" not in text
    assert [item[0].web_app.url for item in markup.inline_keyboard] == [
        "https://bot.example.test/miniapp/app.html?view=manager&section=creators",
        "https://bot.example.test/miniapp/app.html?view=manager",
        "https://bot.example.test/miniapp/app.html?view=partner",
    ]
    roles.get_user.return_value.telegram = "candidate"
    await open_manager_application(message, state, roles, config, service)
    assert message.answers[-1] == (text, markup)
    config.webhook.webhook_base_url = ""
    await tap("status")
    assert "Mini App временно недоступен" in message.answers[-1]


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("1500", "1500"),
        ("1 500 ₽", "1500"),
        ("950 - 1 500 ₽", "950–1500"),
        ("800—1200", "800–1200"),
        ("Обсудим", None),
        ("2000–1000", None),
        ("0", None),
    ],
)
def test_manager_rate_accepts_only_positive_amount_or_range(value, normalized):
    assert normalize_manager_rate(value) == normalized


@pytest.mark.asyncio
async def test_manager_application_does_not_apply_stale_or_foreign_answers(
    config,
):
    user = FakeUser(100, "candidate", "Кандидат")
    message = FakeMessage(user=user)
    message.chat.type = "private"
    state = FakeFSMContext()
    service = SimpleNamespace(open=AsyncMock())
    roles = SimpleNamespace(get_user=AsyncMock(return_value=None))
    answer = AsyncMock()
    callback = SimpleNamespace(
        message=message, from_user=user, answer=answer, data="mgr:submit"
    )
    await manager_application_action(callback, state, roles, config, service)
    answer.assert_awaited_once_with("Откройте /manager", show_alert=True)
    callback.message = FakeMessage(user=FakeUser(101))
    await manager_application_action(callback, state, roles, config, service)
    answer.assert_awaited_with()
    await manager_application_answer(message, state, roles, config, service)
    roles.get_user.return_value = SimpleNamespace(user_id="candidate")
    await state.set_data({"field": "invalid"})
    await manager_application_answer(message, state, roles, config, service)
    assert not await state.get_data()
    service.open.assert_not_awaited()
    await state.set_data({"field": "location"})
    await manager_application_answer(message, state, roles, config, service)
    assert message.answers[-1] == "Введите ответ на вопрос текстом."


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["menu", "deep_link", "command"])
async def test_dispatcher_keeps_manager_route(
    monkeypatch, config, bot_texts_service, entry
):
    candidate = {
        "id": 777,
        "is_bot": False,
        "first_name": "Test",
        "username": "candidate",
    }
    payload = {"date": 1792800000, "chat": {"id": 777, "type": "private"}}
    update_ids = count(100)
    user = SimpleNamespace(
        user_id=uuid4(),
        username="",
        telegram="candidate",
        country="RU",
        language="ru",
        status=UserStatus.ACTIVE,
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=user),
        set_user=AsyncMock(return_value=user),
        update_telegram=AsyncMock(),
    )
    profile = SimpleNamespace(
        get_advertiser_profile=AsyncMock(return_value=None)
    )
    answers = {}
    row = dict(
        state="draft",
        answers=answers,
        user_id=user.user_id,
        instagram=None,
        instagram_verified_at=None,
    )

    async def save(_, field, value):
        answers[field] = value
        return row

    applications = SimpleNamespace(
        open=AsyncMock(return_value=row), answer=AsyncMock(side_effect=save)
    )
    services = {
        "metrics_collector": MagicMock(),
        "user_role_service": roles,
        "profile_service": profile,
        "bot_texts_service": bot_texts_service,
        "referral_service": SimpleNamespace(parse_referral_code=lambda _: None),
        "manager_applications": applications,
    }
    monkeypatch.setattr(
        bot_app,
        "Container",
        lambda _: SimpleNamespace(build_bot_services=lambda: services),
    )
    # Use real handler order and filters without attaching the shared Routers.
    for name, original in list(vars(bot_app).items()):
        if name.endswith("_router") and isinstance(original, Router):
            fresh = Router()
            for observer, value in original.observers.items():
                fresh.observers[observer].handlers.extend(value.handlers)
            monkeypatch.setattr(bot_app, name, fresh)

    dispatcher = bot_app.build_dispatcher(config)
    async with Bot("123:" + "A" * 35) as bot:
        request = AsyncMock()
        bot.session.make_request = request
        dispatcher["messenger_client"] = TelegramMessengerClient(bot)
        state = dispatcher.fsm.get_context(bot=bot, chat_id=777, user_id=777)

        def last_request(method):
            return next(
                call.args[1]
                for call in reversed(request.await_args_list)
                if isinstance(call.args[1], method)
            )

        async def send(text=None, *, contact=None, callback=None):
            update_id = next(update_ids)
            message = {**payload, "message_id": update_id, "from": candidate}
            if text is not None:
                message["text"] = text
            if contact is not None:
                message["contact"] = {
                    "user_id": contact,
                    "first_name": "Test",
                    "phone_number": "+78005550123",
                }
            if callback is None:
                event = {"message": message}
            else:
                event = {
                    "callback_query": {
                        "id": str(update_id),
                        "from": candidate,
                        "chat_instance": "test",
                        "message": {**message, "message_id": 10},
                        "data": callback,
                    }
                }
            await dispatcher.feed_update(
                bot, Update.model_validate({"update_id": update_id, **event})
            )

        # The same account has previously opened business onboarding.
        await send("/start")
        await send(callback="role:advertiser")
        await send(callback="adv:start")
        assert (
            await state.get_state() == AdvertiserRegistrationStates.name.state
        )
        profile.get_advertiser_profile.reset_mock()

        if entry == "menu":
            await send("/start")
            opening = asyncio.Event()
            opened = asyncio.Event()

            async def open_draft(_):
                opening.set()
                await opened.wait()
                return row

            applications.open.side_effect = open_draft
            async with asyncio.TaskGroup() as updates:
                updates.create_task(send(callback="mgr:open"))
                await opening.wait()
                outdated = updates.create_task(send(callback="role:advertiser"))
                await asyncio.sleep(0)
                opened.set()
                assert not outdated.done()
            applications.open.side_effect = None
        else:
            await send("/start manager" if entry == "deep_link" else "/manager")
        assert await state.get_state() == ManagerForm.welcome.state
        assert "Работа менеджера в UMC" in last_request(SendMessage).text
        await send("/start")
        assert await state.get_state() == ManagerForm.welcome.state

        await send(callback="role:advertiser")
        await send(callback="adv:start")
        assert await state.get_state() == ManagerForm.welcome.state
        assert last_request(AnswerCallbackQuery).show_alert is True

        await send(callback="mgr:next")
        await send("Тестовый менеджер")
        assert answers == {"name": "Тестовый менеджер"}

        # Reject a typed number and a different sender's contact at the
        # manager phone prompt, then continue after the valid contact.
        answers.update(
            rate="900",
            work_format="Фрилансер",
            weekly_capacity="1–10",
            location="Казань",
            location_country="Россия",
        )
        await send(callback="mgr:next")
        assert (await state.get_data())["field"] == "phone"
        await send("/start")
        await send(callback="role:advertiser")
        await send("123")
        await send(contact=778)
        assert (await state.get_data())["field"] == "phone"
        assert "phone" not in answers
        await send(contact=777)
        assert answers["phone"] == "+78005550123"
        assert (await state.get_data())["field"] == "instagram"
        assert "Instagram" in last_request(SendMessage).text
        profile.get_advertiser_profile.assert_not_awaited()

        # Deliberate switching from the role menu still works.
        await send("/role")
        assert await state.get_state() is None
        markup = last_request(SendMessage).reply_markup
        assert any(
            button.callback_data == "mgr:open"
            for buttons in markup.inline_keyboard
            for button in buttons
        )
        await send(callback="role:advertiser")
        await send(callback="adv:start")
        assert (
            await state.get_state() == AdvertiserRegistrationStates.name.state
        )
    await dispatcher.fsm.close()
