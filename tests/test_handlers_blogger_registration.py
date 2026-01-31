"""Tests for blogger registration handlers."""

from datetime import datetime, timezone

import pytest

from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.blogger_registration import (
    BloggerRegistrationStates,
    _start_registration_flow,
    blogger_draft_choice,
    handle_agreements,
    handle_age,
    handle_gender,
    handle_geo,
    handle_instagram,
    handle_name,
    handle_price,
    handle_topics,
)
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    DRAFT_RESTORED_TEXT,
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
)
from ugc_bot.domain.entities import FsmDraft
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserStatus, WorkFormat
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
    RecordingFsmDraftService,
)
from tests.helpers.factories import create_test_user


@pytest.mark.asyncio
async def test_start_registration_requires_user(user_repo) -> None:
    """Require existing user before registration."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service, FakeFsmDraftService())

    assert message.answers
    assert "Пользователь не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_start_registration_sets_state(user_repo) -> None:
    """Start registration for blogger role."""

    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="7",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
    )
    message = FakeMessage(text=None, user=FakeUser(7, "alice", "Alice"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service, FakeFsmDraftService())

    assert state._data["external_id"] == "7"
    assert state.state is not None


@pytest.mark.asyncio
async def test_start_registration_blocked_user(user_repo) -> None:
    """Reject registration for blocked user."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000710"),
        external_id="8",
        username="blocked",
        status=UserStatus.BLOCKED,
    )
    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(8, "blocked", "Blocked"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service, FakeFsmDraftService())

    assert message.answers
    assert "Заблокированные" in message.answers[0]


@pytest.mark.asyncio
async def test_start_registration_paused_user(user_repo) -> None:
    """Reject registration for paused user."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000711"),
        external_id="9",
        username="paused",
        status=UserStatus.PAUSE,
    )
    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(9, "paused", "Paused"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service, FakeFsmDraftService())

    assert message.answers
    assert "паузе" in message.answers[0]


@pytest.mark.asyncio
async def test_instagram_validation_in_handler(user_repo, blogger_repo) -> None:
    """Validate Instagram URL in handler."""

    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    message = FakeMessage(text="bad_url", user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert message.answers
    assert "Неверный формат" in message.answers[0]


@pytest.mark.asyncio
async def test_instagram_success_in_handler(user_repo, blogger_repo) -> None:
    """Accept valid Instagram URL."""

    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    message = FakeMessage(
        text="https://instagram.com/test_user",
        user=FakeUser(1, "user", "User"),
    )
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert state._data["instagram_url"].endswith("test_user")


@pytest.mark.asyncio
async def test_gender_invalid() -> None:
    """Reject invalid gender."""

    message = FakeMessage(text="unknown", user=None)
    state = FakeFSMContext()

    await handle_gender(message, state)

    assert message.answers
    assert "Выберите" in message.answers[0]


@pytest.mark.asyncio
async def test_age_invalid() -> None:
    """Reject invalid age format."""

    message = FakeMessage(text="18", user=None)
    state = FakeFSMContext()

    await handle_age(message, state)

    assert message.answers
    assert "кнопок возраста" in message.answers[0]


@pytest.mark.asyncio
async def test_price_invalid() -> None:
    """Reject invalid price."""

    message = FakeMessage(text="abc", user=None)
    state = FakeFSMContext()

    await handle_price(message, state)

    assert message.answers
    assert "Введите число" in message.answers[0]


@pytest.mark.asyncio
async def test_name_and_topics_flow() -> None:
    """Store nickname and topics."""

    state = FakeFSMContext()
    name_message = FakeMessage(text="Alice", user=FakeUser(1, "user", "User"))
    await handle_name(name_message, state)
    assert state._data["nickname"] == "Alice"

    topics_message = FakeMessage(text="fitness, travel", user=None)
    await handle_topics(topics_message, state)
    assert state._data["topics"]["selected"] == ["fitness", "travel"]


@pytest.mark.asyncio
async def test_name_and_topics_invalid() -> None:
    """Handle invalid name and topics input."""

    state = FakeFSMContext()
    name_message = FakeMessage(text=" ", user=None)
    await handle_name(name_message, state)
    assert "Ник не может" in name_message.answers[0]

    topics_message = FakeMessage(text=" ", user=None)
    await handle_topics(topics_message, state)
    assert "тематику" in topics_message.answers[0]


@pytest.mark.asyncio
async def test_gender_age_geo_price_flow() -> None:
    """Store gender, age, geo, price."""

    state = FakeFSMContext()

    gender_message = FakeMessage(text="👥 Примерно поровну", user=None)
    await handle_gender(gender_message, state)
    assert state._data["audience_gender"] == AudienceGender.ALL

    age_message = FakeMessage(text="18–24", user=None)
    await handle_age(age_message, state)
    assert state._data["audience_age_min"] == 18
    assert state._data["audience_age_max"] == 24

    geo_message = FakeMessage(text="Moscow", user=None)
    await handle_geo(geo_message, state)
    assert state._data["audience_geo"] == "Moscow"

    price_message = FakeMessage(text="1500", user=None)
    await handle_price(price_message, state)
    assert state._data["price"] == 1500.0


@pytest.mark.asyncio
async def test_geo_empty_and_price_negative() -> None:
    """Handle invalid geo and price inputs."""

    state = FakeFSMContext()
    geo_message = FakeMessage(text=" ", user=None)
    await handle_geo(geo_message, state)
    assert "город" in geo_message.answers[0]

    price_message = FakeMessage(text="-5", user=None)
    await handle_price(price_message, state)
    assert "Цена должна" in price_message.answers[0]


@pytest.mark.asyncio
async def test_handle_agreements_creates_profile(user_repo, blogger_repo) -> None:
    """Agreement step persists blogger profile."""

    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    user = await user_role_service.set_user(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
    )

    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(42, "bob", "Bob")
    )
    state = FakeFSMContext()
    await state.update_data(
        user_id=user.user_id,
        external_id="42",
        nickname="bob",
        instagram_url="https://instagram.com/test_user",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
    )

    await handle_agreements(
        message,
        state,
        registration_service,
        user_role_service,
    )

    assert message.answers
    ans = message.answers[0]
    assert "Профиль создан" in (ans if isinstance(ans, str) else ans[0])
    assert await blogger_repo.get_by_user_id(user.user_id) is not None


@pytest.mark.asyncio
async def test_handle_agreements_requires_consent(user_repo, blogger_repo) -> None:
    """Require explicit consent."""

    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    message = FakeMessage(text="нет", user=FakeUser(1, "bob", "Bob"))
    state = FakeFSMContext()

    await handle_agreements(
        message,
        state,
        registration_service,
        user_role_service,
    )

    assert message.answers
    assert "Подтвердить согласие" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_instagram_duplicate_url(user_repo, blogger_repo) -> None:
    """Reject duplicate Instagram URL."""
    from datetime import datetime, timezone
    from uuid import UUID
    from ugc_bot.domain.entities import BloggerProfile

    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    # Create existing profile with Instagram URL
    existing_user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000100"),
        external_id="100",
        username="existing",
    )
    existing_profile = BloggerProfile(
        user_id=existing_user.user_id,
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    await blogger_repo.save(existing_profile)

    # Try to register with same Instagram URL
    message = FakeMessage(
        text="https://instagram.com/test_user", user=FakeUser(101, "new", "New")
    )
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert message.answers
    assert "уже зарегистрирован" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_agreements_shows_verification_button(
    user_repo, blogger_repo
) -> None:
    """Show verification button after registration for unconfirmed profile."""
    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    user = await user_role_service.set_user(
        external_id="43",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
    )

    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(43, "alice", "Alice")
    )
    state = FakeFSMContext()
    await state.update_data(
        user_id=user.user_id,
        external_id="43",
        nickname="alice",
        instagram_url="https://instagram.com/test_user",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
    )

    await handle_agreements(
        message,
        state,
        registration_service,
        user_role_service,
    )

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    # After registration: Confirm Instagram + My profile
    assert len(keyboard.keyboard) == 2
    assert keyboard.keyboard[0][0].text == "Подтвердить Instagram"
    assert keyboard.keyboard[1][0].text == "Мой профиль"


@pytest.mark.asyncio
async def test_start_registration_shows_draft_question_when_draft_exists(
    user_repo,
) -> None:
    """When draft exists, show draft question and set choosing_draft_restore."""

    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="7",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
    )
    draft = FsmDraft(
        user_id=user.user_id,
        flow_type="blogger_registration",
        state_key="BloggerRegistrationStates:city",
        data={"user_id": user.user_id, "external_id": "7", "nickname": "alice"},
        updated_at=datetime.now(timezone.utc),
    )
    draft_service = RecordingFsmDraftService(draft_to_return=draft)
    message = FakeMessage(text=None, user=FakeUser(7, "alice", "Alice"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service, draft_service)

    assert DRAFT_QUESTION_TEXT in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert state.state == BloggerRegistrationStates.choosing_draft_restore


@pytest.mark.asyncio
async def test_blogger_draft_choice_continue_restores(user_repo) -> None:
    """RESUME_DRAFT_BUTTON restores state and sends restored + prompt."""

    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="8",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
    )
    draft = FsmDraft(
        user_id=user.user_id,
        flow_type="blogger_registration",
        state_key="BloggerRegistrationStates:city",
        data={"user_id": user.user_id, "external_id": "8", "nickname": "bob"},
        updated_at=datetime.now(timezone.utc),
    )
    draft_service = RecordingFsmDraftService(draft_to_return=draft)
    message = FakeMessage(text=RESUME_DRAFT_BUTTON_TEXT, user=FakeUser(8, "bob", "Bob"))
    state = FakeFSMContext()
    state._data = {"user_id": user.user_id}
    state.state = BloggerRegistrationStates.choosing_draft_restore

    await blogger_draft_choice(message, state, service, draft_service)

    assert state.state == "BloggerRegistrationStates:city"
    assert state._data.get("nickname") == "bob"
    assert len(draft_service.delete_calls) == 1
    text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert DRAFT_RESTORED_TEXT in text
    assert "город" in text.lower()


@pytest.mark.asyncio
async def test_blogger_draft_choice_start_over_deletes_and_starts(user_repo) -> None:
    """START_OVER_BUTTON deletes draft and shows first step."""

    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="9",
        messenger_type=MessengerType.TELEGRAM,
        username="carol",
    )
    draft_service = RecordingFsmDraftService(draft_to_return=None)
    message = FakeMessage(
        text=START_OVER_BUTTON_TEXT, user=FakeUser(9, "carol", "Carol")
    )
    state = FakeFSMContext()
    state._data = {"user_id": user.user_id}
    state.state = BloggerRegistrationStates.choosing_draft_restore

    await blogger_draft_choice(message, state, service, draft_service)

    assert state.state == BloggerRegistrationStates.name
    assert len(draft_service.delete_calls) == 1
    text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "имя или ник" in text.lower()
