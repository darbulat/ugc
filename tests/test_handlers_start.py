"""Tests for start and role handlers."""

import pytest

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import (
    START_TEXT,
    _role_keyboard,
    choose_role,
    role_command,
    start_command,
    support_button,
)
from ugc_bot.domain.enums import MessengerType
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
    RecordingFsmDraftService,
)


@pytest.mark.asyncio
async def test_start_command_sends_role_keyboard(user_repo) -> None:
    """Ensure /start sends role keyboard and start text."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "test", "Alice"))
    await start_command(message, user_role_service=service)

    assert message.answers
    assert "UMC — сервис для UGC" in message.answers[0][0]
    assert "Бизнесу — подбор креаторов" in message.answers[0][0]
    keyboard = message.answers[0][1]
    assert keyboard is not None
    assert keyboard.keyboard == _role_keyboard().keyboard


@pytest.mark.asyncio
async def test_role_command_shows_keyboard() -> None:
    """Ensure /role returns role keyboard."""

    message = FakeMessage(text=None, user=FakeUser(1, "test", "Alice"))
    await role_command(message)

    assert message.answers
    assert START_TEXT in message.answers[0][0] or "UMC" in message.answers[0][0]
    keyboard = message.answers[0][1]
    assert keyboard is not None
    assert keyboard.keyboard == _role_keyboard().keyboard


@pytest.mark.asyncio
async def test_choose_role_creator_persists(user_repo) -> None:
    """Ensure creator role selection is persisted."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Я креатор", user=FakeUser(42, "bob", "Bob"))

    await choose_role(message, service)

    user = await service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    assert user.username == "bob"


@pytest.mark.asyncio
async def test_choose_role_without_user(user_repo) -> None:
    """Ignore messages without sender."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Мне нужны UGC‑креаторы", user=None)

    await choose_role(message, service)
    assert await service.get_user("0", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_choose_role_advertiser_response(user_repo) -> None:
    """Advertiser role should respond accordingly."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Мне нужны UGC‑креаторы", user=FakeUser(99, None, "Ann"))

    await choose_role(message, service)
    assert message.answers
    assert "Вы выбрали роль" in message.answers[-1][0]
    assert "Давайте создадим профиль" in message.answers[-1][0]


@pytest.mark.asyncio
async def test_support_button_sends_support_text(user_repo) -> None:
    """Support button sends support text and main menu."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Поддержка", user=FakeUser(1, "u", "User"))
    state = FakeFSMContext(state=None)
    draft_service = FakeFsmDraftService()

    await support_button(
        message,
        user_role_service=service,
        state=state,
        fsm_draft_service=draft_service,
    )

    assert message.answers
    assert "Служба поддержки" in message.answers[0][0]
    assert "@usemycontent" in message.answers[0][0]
    assert message.answers[0][1] is not None


@pytest.mark.asyncio
async def test_support_button_clears_fsm_state(user_repo) -> None:
    """Support button clears FSM state when in a flow."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Поддержка", user=FakeUser(2, "u", "User"))
    state = FakeFSMContext(state="BloggerRegistrationStates:instagram")
    draft_service = FakeFsmDraftService()

    await support_button(
        message,
        user_role_service=service,
        state=state,
        fsm_draft_service=draft_service,
    )

    assert state.cleared is True
    assert "Служба поддержки" in message.answers[0][0]


@pytest.mark.asyncio
async def test_support_button_saves_draft_when_in_flow(user_repo) -> None:
    """Support button saves draft when user is in a draftable flow and has data."""

    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
    )
    message = FakeMessage(text="Поддержка", user=FakeUser(2, "u", "User"))
    state = FakeFSMContext(state="BloggerRegistrationStates:instagram")
    state._data = {"user_id": user.user_id, "external_id": "2"}
    draft_service = RecordingFsmDraftService()

    await support_button(
        message,
        user_role_service=service,
        state=state,
        fsm_draft_service=draft_service,
    )

    assert state.cleared is True
    assert len(draft_service.save_calls) == 1
    saved_user_id, flow_type, state_key, data = draft_service.save_calls[0]
    assert saved_user_id == user.user_id
    assert flow_type == "blogger_registration"
    assert state_key == "BloggerRegistrationStates:instagram"
    assert data.get("user_id") == user.user_id
