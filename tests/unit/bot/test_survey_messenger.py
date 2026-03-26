"""Tests for messenger-choice survey handlers."""

import pytest

from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
)
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.survey_messenger import (
    SurveyMessengerStates,
    on_survey_max,
    on_survey_other,
    on_survey_other_text,
    on_survey_own_app,
    on_survey_telegram,
)
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryNpsRepository,
    InMemoryUserRepository,
)


async def _make_user(
    external_id: str = "42",
) -> tuple[UserRoleService, InMemoryNpsRepository, NpsService]:
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username="tester",
    )
    nps_repo = InMemoryNpsRepository()
    nps_service = NpsService(nps_repo=nps_repo)
    return service, nps_repo, nps_service


@pytest.mark.asyncio
async def test_survey_telegram_saves_nps_and_answers(event_adapter) -> None:
    """Pressing 'остаёмся в Telegram' saves NPS(score=0, comment='telegram')."""
    user_service, nps_repo, nps_service = await _make_user("1")
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(1, "t", "T"))
    callback = FakeCallback(
        data="survey:msg:tg", user=FakeUser(1, "t", "T"), message=message
    )

    await on_survey_telegram(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    user = await user_service.get_user("1", MessengerType.TELEGRAM)
    assert user is not None
    saved = nps_repo.scores.get(user.user_id)
    assert saved == [(0, "telegram")]
    assert len(message.edit_reply_markup_calls) == 1
    assert len(callback.answers) == 1


@pytest.mark.asyncio
async def test_survey_max_saves_nps_and_answers(event_adapter) -> None:
    """Pressing 'переходим в MAX' saves NPS(score=0, comment='MAX')."""
    user_service, nps_repo, nps_service = await _make_user("2")
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(2, "t", "T"))
    callback = FakeCallback(
        data="survey:msg:max", user=FakeUser(2, "t", "T"), message=message
    )

    await on_survey_max(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    user = await user_service.get_user("2", MessengerType.TELEGRAM)
    assert user is not None
    saved = nps_repo.scores.get(user.user_id)
    assert saved == [(0, "MAX")]
    assert len(message.edit_reply_markup_calls) == 1
    assert len(callback.answers) == 1


@pytest.mark.asyncio
async def test_survey_other_sets_fsm_and_prompts(event_adapter) -> None:
    """Pressing 'другой вариант' sets FSM state and asks for text."""
    user_service, _nps_repo, _nps_service = await _make_user("3")
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(3, "t", "T"))
    callback = FakeCallback(
        data="survey:msg:other", user=FakeUser(3, "t", "T"), message=message
    )
    state = FakeFSMContext()

    await on_survey_other(
        callback,
        state=state,
        user_role_service=user_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    # FSM state set
    assert state.state == SurveyMessengerStates.waiting_other_text
    fsm_data = await state.get_data()
    user = await user_service.get_user("3", MessengerType.TELEGRAM)
    assert user is not None
    assert fsm_data.get("survey_user_id") == str(user.user_id)
    # Keyboard removed
    assert len(message.edit_reply_markup_calls) == 1
    # Prompt sent
    assert len(message.answers) == 1


@pytest.mark.asyncio
async def test_survey_other_text_saves_nps_and_clears_state() -> None:
    """Typing a custom messenger saves NPS with that text and clears FSM."""
    user_service, nps_repo, nps_service = await _make_user("4")
    user = await user_service.get_user("4", MessengerType.TELEGRAM)
    assert user is not None

    state = FakeFSMContext(state=str(SurveyMessengerStates.waiting_other_text))
    await state.update_data(survey_user_id=str(user.user_id))

    message = FakeMessage(text="WhatsApp", user=FakeUser(4, "t", "T"))

    await on_survey_other_text(message, state=state, nps_service=nps_service)

    saved = nps_repo.scores.get(user.user_id)
    assert saved == [(0, "WhatsApp")]
    assert state.cleared


@pytest.mark.asyncio
async def test_survey_other_text_strips_whitespace() -> None:
    """Whitespace-only text is stored as None."""
    user_service, nps_repo, nps_service = await _make_user("5")
    user = await user_service.get_user("5", MessengerType.TELEGRAM)
    assert user is not None

    state = FakeFSMContext()
    await state.update_data(survey_user_id=str(user.user_id))

    message = FakeMessage(text="   ", user=FakeUser(5, "t", "T"))

    await on_survey_other_text(message, state=state, nps_service=nps_service)

    saved = nps_repo.scores.get(user.user_id)
    assert saved == [(0, None)]


@pytest.mark.asyncio
async def test_survey_telegram_user_not_found_still_answers(
    event_adapter,
) -> None:
    """Unknown user still gets callback answered without error."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    nps_repo = InMemoryNpsRepository()
    nps_service = NpsService(nps_repo=nps_repo)
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(99, "ghost", "Ghost"))
    callback = FakeCallback(
        data="survey:msg:tg",
        user=FakeUser(99, "ghost", "Ghost"),
        message=message,
    )

    await on_survey_telegram(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(nps_repo.scores) == 0
    assert len(callback.answers) == 1


@pytest.mark.asyncio
async def test_survey_other_text_no_user_id_clears_state() -> None:
    """Missing survey_user_id in FSM data clears state gracefully."""
    _user_repo = InMemoryUserRepository()
    nps_repo = InMemoryNpsRepository()
    nps_service = NpsService(nps_repo=nps_repo)
    state = FakeFSMContext()
    # No survey_user_id in data

    message = FakeMessage(text="Signal", user=FakeUser(7, "t", "T"))

    await on_survey_other_text(message, state=state, nps_service=nps_service)

    assert len(nps_repo.scores) == 0
    assert state.cleared


@pytest.mark.asyncio
async def test_survey_max_user_not_found_still_answers(event_adapter) -> None:
    """Unknown user on MAX button answers callback without saving NPS."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    nps_repo = InMemoryNpsRepository()
    nps_service = NpsService(nps_repo=nps_repo)
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(99, "ghost", "Ghost"))
    callback = FakeCallback(
        data="survey:msg:max",
        user=FakeUser(99, "ghost", "Ghost"),
        message=message,
    )

    await on_survey_max(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(nps_repo.scores) == 0
    assert len(callback.answers) == 1


@pytest.mark.asyncio
async def test_survey_other_user_not_found_still_answers(
    event_adapter,
) -> None:
    """Unknown user on 'other' button answers callback without FSM changes."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(99, "ghost", "Ghost"))
    callback = FakeCallback(
        data="survey:msg:other",
        user=FakeUser(99, "ghost", "Ghost"),
        message=message,
    )
    state = FakeFSMContext()

    await on_survey_other(
        callback,
        state=state,
        user_role_service=user_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert state.state is None
    assert len(callback.answers) == 1


@pytest.mark.asyncio
async def test_get_user_returns_none_for_empty_external_id(
    event_adapter,
) -> None:
    """Callback with no from_user yields no NPS save."""
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    nps_repo = InMemoryNpsRepository()
    nps_service = NpsService(nps_repo=nps_repo)
    client = FakeMessengerClient()
    # FakeCallback with user=None triggers external_id=""
    message = FakeMessage(user=None)
    callback = FakeCallback(data="survey:msg:tg", user=None, message=message)

    await on_survey_telegram(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(nps_repo.scores) == 0


@pytest.mark.asyncio
async def test_survey_own_app_saves_nps_and_answers(event_adapter) -> None:
    """Pressing 'своё приложение' saves NPS(score=0, comment='own_app')."""
    user_service, nps_repo, nps_service = await _make_user("10")
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(10, "t", "T"))
    callback = FakeCallback(
        data="survey:msg:own_app", user=FakeUser(10, "t", "T"), message=message
    )

    await on_survey_own_app(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    user = await user_service.get_user("10", MessengerType.TELEGRAM)
    assert user is not None
    saved = nps_repo.scores.get(user.user_id)
    assert saved == [(0, "own_app")]
    assert len(message.edit_reply_markup_calls) == 1
    assert len(callback.answers) == 1


@pytest.mark.asyncio
async def test_survey_own_app_user_not_found_still_answers(
    event_adapter,
) -> None:
    user_repo = InMemoryUserRepository()
    user_service = UserRoleService(user_repo=user_repo)
    nps_repo = InMemoryNpsRepository()
    nps_service = NpsService(nps_repo=nps_repo)
    client = FakeMessengerClient()
    message = FakeMessage(user=FakeUser(99, "ghost", "Ghost"))
    callback = FakeCallback(
        data="survey:msg:own_app",
        user=FakeUser(99, "ghost", "Ghost"),
        message=message,
    )

    await on_survey_own_app(
        callback,
        user_role_service=user_service,
        nps_service=nps_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(nps_repo.scores) == 0
    assert len(callback.answers) == 1
