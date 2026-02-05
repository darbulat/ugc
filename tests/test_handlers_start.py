"""Tests for start and role handlers."""

import pytest

from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
    RecordingFsmDraftService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.advertiser_registration import (
    choose_advertiser_role,
)
from ugc_bot.bot.handlers.blogger_registration import (
    CREATOR_CHOOSE_ACTION_TEXT,
    CREATOR_INTRO_NOT_REGISTERED,
    choose_creator_role,
)
from ugc_bot.bot.handlers.keyboards import (
    advertiser_menu_keyboard,
    creator_filled_profile_keyboard,
    creator_start_keyboard,
)
from ugc_bot.bot.handlers.start import (
    CHANGE_ROLE_BUTTON_TEXT,
    START_TEXT,
    _role_keyboard,
    change_role_button,
    start_command,
    support_button,
)
from ugc_bot.domain.enums import MessengerType


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
async def test_start_command_without_from_user_returns_early(user_repo) -> None:
    """Start with no from_user does not send message."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=None)
    await start_command(message, user_role_service=service)
    assert not message.answers


@pytest.mark.asyncio
async def test_change_role_button_shows_start_screen() -> None:
    """Change role button shows start text and role keyboard."""

    message = FakeMessage(
        text=CHANGE_ROLE_BUTTON_TEXT, user=FakeUser(1, "u", "User")
    )
    state = FakeFSMContext(state=None)
    await change_role_button(message, state=state)

    assert message.answers
    assert START_TEXT in message.answers[0][0]
    assert message.answers[0][1] is not None
    assert message.answers[0][1].keyboard == _role_keyboard().keyboard


@pytest.mark.asyncio
async def test_choose_role_creator_persists(user_repo, blogger_repo) -> None:
    """Creator role persisted; no profile shows create profile."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Я креатор", user=FakeUser(42, "bob", "Bob"))
    state = FakeFSMContext(state=None)
    await choose_creator_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
    )

    user = await service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    assert user.username == ""
    assert message.answers
    assert CREATOR_INTRO_NOT_REGISTERED in message.answers[-1][0]
    assert message.answers[-1][1].keyboard == creator_start_keyboard().keyboard


@pytest.mark.asyncio
async def test_choose_role_creator_with_filled_profile_shows_menu(
    user_repo, blogger_repo
) -> None:
    """Creator with filled blogger profile: show Edit/My profile/My orders."""

    from tests.helpers.factories import create_test_blogger_profile
    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Я креатор", user=FakeUser(42, "bob", "Bob"))
    state = FakeFSMContext(state=None)

    await service.set_user(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        role_chosen=False,
    )
    user = await service.get_user("42", MessengerType.TELEGRAM)
    assert user is not None
    await create_test_blogger_profile(blogger_repo, user.user_id)

    await choose_creator_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
    )

    assert message.answers
    assert message.answers[-1][0] == CREATOR_CHOOSE_ACTION_TEXT
    assert (
        message.answers[-1][1].keyboard
        == creator_filled_profile_keyboard().keyboard
    )


@pytest.mark.asyncio
async def test_choose_role_advertiser_with_filled_profile_shows_menu(
    user_repo, blogger_repo, advertiser_repo
) -> None:
    """Advertiser with filled profile: show 'Выберите действие:' and menu."""

    from tests.helpers.factories import create_test_advertiser_profile
    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(
        text="Мне нужны UGC‑креаторы", user=FakeUser(99, "adv", "Advertiser")
    )
    state = FakeFSMContext(state=None)

    await service.set_user(
        external_id="99",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        role_chosen=False,
    )
    user = await service.get_user("99", MessengerType.TELEGRAM)
    assert user is not None
    await create_test_advertiser_profile(advertiser_repo, user.user_id)

    await choose_advertiser_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
    )

    assert message.answers
    assert message.answers[-1][0] == "Выберите действие:"
    assert (
        message.answers[-1][1].keyboard == advertiser_menu_keyboard().keyboard
    )


@pytest.mark.asyncio
async def test_choose_role_without_user(user_repo, blogger_repo) -> None:
    """Ignore messages without sender."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Мне нужны UGC‑креаторы", user=None)
    state = FakeFSMContext(state=None)
    await choose_advertiser_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
    )
    assert await service.get_user("0", MessengerType.TELEGRAM) is None


@pytest.mark.asyncio
async def test_choose_role_advertiser_response(user_repo, blogger_repo) -> None:
    """Advertiser role should respond accordingly."""

    from tests.helpers.services import build_profile_service

    service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text="Мне нужны UGC‑креаторы", user=FakeUser(99, None, "Ann")
    )
    state = FakeFSMContext(state=None)
    await choose_advertiser_role(
        message,
        user_role_service=service,
        profile_service=profile_service,
        state=state,
    )
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
async def test_support_button_without_from_user_returns_early(
    user_repo,
) -> None:
    """Support button with no from_user does not send message."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text="Поддержка", user=None)
    state = FakeFSMContext(state=None)
    draft_service = FakeFsmDraftService()

    await support_button(
        message,
        user_role_service=service,
        state=state,
        fsm_draft_service=draft_service,
    )
    assert not message.answers


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
    """Support button saves draft when user in draftable flow and has data."""

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
