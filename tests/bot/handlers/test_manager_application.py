"""Telegram application entry, private contact sharing and submission."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests.helpers.fakes import FakeFSMContext, FakeMessage, FakeUser
from ugc_bot.bot.telegram.handlers.manager_application import (
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
    assert "600 ₽ менеджеру" in message.answers[-1][0]
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
