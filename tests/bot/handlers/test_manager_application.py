"""Telegram application entry, private contact sharing and submission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.helpers.fakes import FakeFSMContext, FakeMessage, FakeUser
from ugc_bot.bot.telegram.handlers.manager_application import (
    manager_application_action,
    manager_application_answer,
    open_manager_application,
)
from ugc_bot.domain.manager_application import FIELDS


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
    answers = dict.fromkeys(FIELDS, "Ответ")
    service = SimpleNamespace(
        answer=AsyncMock(),
        open=AsyncMock(
            return_value={
                "state": "draft",
                "answers": answers,
            }
        ),
    )
    await manager_application_answer(message, state, roles, config, service)
    service.answer.assert_not_awaited()
    message.contact.user_id = 100
    await manager_application_answer(message, state, roles, config, service)
    service.answer.assert_awaited_once_with(uid, "phone", "+70000000000")
    assert (
        "Отправить заявку" in message.answers[-1][1].inline_keyboard[0][0].text
    )


@pytest.mark.asyncio
async def test_manager_edits_submits_and_verifies_application(config):
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

    async def answer(_, field, value):
        row["answers"][field] = value

    async def submit(_):
        row["state"] = "submitted"

    service = SimpleNamespace(
        open=AsyncMock(return_value=row),
        answer=AsyncMock(side_effect=answer),
        submit=AsyncMock(side_effect=submit),
        instagram_challenge=AsyncMock(return_value="MGR-123456"),
    )
    roles = SimpleNamespace(
        get_user=AsyncMock(return_value=SimpleNamespace(user_id="candidate"))
    )
    callback = SimpleNamespace(
        message=message, from_user=user, answer=AsyncMock()
    )

    async def tap(action):
        callback.data = f"mgr:{action}"
        await manager_application_action(
            callback, state, roles, config, service
        )

    await tap("next")
    assert (await state.get_data())["field"] == "rate"
    assert message.answers[-1][1].inline_keyboard[0][0].text == "Обсудим"
    await tap("rate:0")
    assert row["answers"]["rate"] == "Обсудим"
    await tap("field:rate")
    message.text = "900–1500"
    await manager_application_answer(message, state, roles, config, service)
    assert row["answers"]["rate"] == "900–1500"
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
    message.text = "Россия, Казань"
    await manager_application_answer(message, state, roles, config, service)
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

    await tap("field:coverage")
    assert message.answers[-1][1].inline_keyboard[0][0].text == "Пропустить"
    await tap("coverage:0")
    assert row["answers"]["coverage"] == "Не указано"
    await tap("field:coverage")
    message.text = "Казань, гастрономия"
    await manager_application_answer(message, state, roles, config, service)
    assert row["answers"]["coverage"] == "Казань, гастрономия"

    await tap("field:case")
    service.answer.side_effect = ValueError("too long")
    message.text = "x" * 501
    await manager_application_answer(message, state, roles, config, service)
    assert "Проверьте формат" in message.answers[-1]
    row["answers"].update(
        {field: "Ответ" for field in FIELDS if field not in row["answers"]}
    )
    # An old review message can still be submitted after the release.
    del row["answers"]["weekly_capacity"]
    service.answer.side_effect = answer
    await tap("submit")
    assert (await state.get_data())["field"] == "weekly_capacity"
    service.submit.assert_not_awaited()
    assert row["answers"]["coverage"] == "Казань, гастрономия"
    await tap("weekly_capacity:0")
    assert "Авторов в неделю · 0" in message.answers[-1][0]
    service.submit.side_effect = submit
    await tap("next")
    assert "Проверьте заявку" in message.answers[-1][0]
    await tap("submit")
    assert "Заявка на рассмотрении." in message.answers[-1][0]
    assert (
        message.answers[-1][1].inline_keyboard[0][0].text
        == "Подтвердить Instagram"
    )
    del row["answers"]["weekly_capacity"]
    await tap("submit")
    service.submit.assert_awaited_once()
    await tap("next")
    assert "Заявка на рассмотрении." in message.answers[-1][0]
    await tap("instagram")
    assert "MGR-123456" in message.answers[-1]
    assert "/manager" in message.answers[-1]
    row["instagram_verified_at"] = object()
    service.instagram_challenge.return_value = None
    await tap("instagram")
    assert "Instagram подтверждён" in message.answers[-1][0]
    row.update(state="clarify", decision_note="Уточните загрузку")
    await tap("open")
    assert "Уточните загрузку" in message.answers[-1][0]
    row["state"] = "approved"
    await tap("open")
    assert "/app" in message.answers[-1]


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
