"""Tests for start and role handlers."""

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import (
    _role_keyboard,
    choose_role,
    role_command,
    start_command,
)
from ugc_bot.domain.enums import MessengerType
from tests.helpers.fakes import FakeMessage, FakeUser


@pytest.mark.asyncio
async def test_start_command_sends_role_keyboard() -> None:
    """Ensure /start sends role keyboard."""

    message = FakeMessage(text=None, user=FakeUser(1, "test", "Alice"))
    await start_command(message)

    assert message.answers
    assert "🎉 Добро пожаловать в UMC!" in message.answers[0][0]
    assert (
        "Мы помогаем рекламодателям быстро находить подходящих блогеров"
        in message.answers[0][0]
    )
    assert "Выберите подходящий вариант ниже:" in message.answers[0][0]
    keyboard = message.answers[0][1]
    assert keyboard is not None
    assert keyboard.keyboard == _role_keyboard().keyboard


@pytest.mark.asyncio
async def test_role_command_shows_keyboard() -> None:
    """Ensure /role returns role keyboard."""

    message = FakeMessage(text=None, user=FakeUser(1, "test", "Alice"))
    await role_command(message)

    assert message.answers
    keyboard = message.answers[0][1]
    assert keyboard is not None
    assert keyboard.keyboard == _role_keyboard().keyboard


@pytest.mark.asyncio
async def test_choose_role_persists_role(user_repo) -> None:
    """Ensure role selection is persisted."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Я блогер", user=FakeUser(42, "bob", "Bob"))

    await choose_role(message, service)

    user = await service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    assert user.username == "bob"


@pytest.mark.asyncio
async def test_choose_role_without_user(user_repo) -> None:
    """Ignore messages without sender."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Хочу заказать рекламу", user=None)

    await choose_role(message, service)
    assert await service.get_user("0", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_choose_role_advertiser_response(user_repo) -> None:
    """Advertiser role should respond accordingly."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Хочу заказать рекламу", user=FakeUser(99, None, "Ann"))

    await choose_role(message, service)
    assert message.answers
    assert "register as an advertiser" in message.answers[-1][0]
