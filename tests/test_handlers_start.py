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
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


class FakeUser:
    """Minimal user stub."""

    def __init__(self, user_id: int, username: str | None, first_name: str) -> None:
        self.id = user_id
        self.username = username
        self.first_name = first_name


class FakeMessage:
    """Minimal message stub for handler tests."""

    def __init__(self, text: str | None, user: FakeUser | None) -> None:
        self.text = text
        self.from_user = user
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response text and markup."""

        self.answers.append((text, reply_markup))


@pytest.mark.asyncio
async def test_start_command_sends_role_keyboard() -> None:
    """Ensure /start sends role keyboard."""

    message = FakeMessage(text=None, user=FakeUser(1, "test", "Alice"))
    await start_command(message)

    assert message.answers
    assert "Choose your role" in message.answers[0][0]
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
async def test_choose_role_persists_role() -> None:
    """Ensure role selection is persisted."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text="Я блогер", user=FakeUser(42, "bob", "Bob"))

    await choose_role(message, service)

    user = service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    assert user.username == "bob"


@pytest.mark.asyncio
async def test_choose_role_without_user() -> None:
    """Ignore messages without sender."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text="Я рекламодатель", user=None)

    await choose_role(message, service)
    assert service.get_user("0", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_choose_role_advertiser_response() -> None:
    """Advertiser role should respond accordingly."""

    repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=repo)
    message = FakeMessage(text="Я рекламодатель", user=FakeUser(99, None, "Ann"))

    await choose_role(message, service)
    assert message.answers
    assert "register as an advertiser" in message.answers[-1][0]
