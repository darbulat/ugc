"""Tests for profile handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_INSTAGRAM_BUTTON_TEXT,
    MY_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
)
from ugc_bot.bot.handlers.profile import (
    edit_profile_choose_field,
    edit_profile_enter_value,
    edit_profile_start,
    show_profile,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, WorkFormat
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
)
from tests.helpers.factories import create_test_user


class FakeProfileService:
    """Stub profile service."""

    def __init__(
        self,
        user: User,
        has_blogger: bool,
        has_advertiser: bool,
        blogger_confirmed: bool = True,
    ) -> None:
        self._user = user
        self._has_blogger = has_blogger
        self._has_advertiser = has_advertiser
        self._blogger_confirmed = blogger_confirmed

    async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
        return self._user

    async def get_blogger_profile(self, user_id):  # type: ignore[no-untyped-def]
        if not self._has_blogger:
            return None
        return BloggerProfile(
            user_id=user_id,
            instagram_url="https://instagram.com/test",
            confirmed=self._blogger_confirmed,
            city="Moscow",
            topics={"selected": ["tech"]},
            audience_gender=AudienceGender.ALL,
            audience_age_min=18,
            audience_age_max=35,
            audience_geo="Moscow",
            price=1000.0,
            barter=False,
            work_format=WorkFormat.UGC_ONLY,
            updated_at=datetime.now(timezone.utc),
        )

    async def get_advertiser_profile(self, user_id):  # type: ignore[no-untyped-def]
        if not self._has_advertiser:
            return None
        return AdvertiserProfile(
            user_id=user_id,
            name="Test",
            phone="contact",
            brand="Brand",
        )


class FakeBloggerRegistrationService:
    """Stub for blogger registration service in edit flow."""

    def __init__(
        self,
        update_returns: BloggerProfile | None = None,
        get_by_instagram: BloggerProfile | None = None,
    ) -> None:
        self.update_returns = update_returns
        self.get_by_instagram = get_by_instagram
        self.update_calls: list[tuple[UUID, dict]] = []

    async def update_blogger_profile(
        self, user_id: UUID, **kwargs: object
    ) -> BloggerProfile | None:
        self.update_calls.append((user_id, kwargs))
        return self.update_returns

    async def get_profile_by_instagram_url(self, url: str) -> BloggerProfile | None:
        return self.get_by_instagram


class FakeUserRoleService:
    """Stub for user role service in edit flow."""

    def __init__(self) -> None:
        self.set_user_calls: list[tuple[str, str, str]] = []

    async def set_user(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
    ) -> None:
        self.set_user_calls.append((external_id, messenger_type.value, username))


class FakeAdvertiserRegistrationService:
    """Stub for advertiser registration service in edit flow."""

    def __init__(self, update_returns: AdvertiserProfile | None = None) -> None:
        self.update_returns = update_returns
        self.update_calls: list[tuple[UUID, dict]] = []

    async def update_advertiser_profile(
        self, user_id: UUID, **kwargs: object
    ) -> AdvertiserProfile | None:
        self.update_calls.append((user_id, dict(kwargs)))
        return self.update_returns


class _FakeProfileServiceUserMissing:
    """Profile service that returns no user."""

    async def get_user_by_external(
        self, external_id: str, messenger_type: object
    ) -> None:
        return None

    async def get_blogger_profile(self, user_id: object) -> None:
        return None

    async def get_advertiser_profile(self, user_id: object) -> None:
        return None


def _make_blogger_profile(user_id: UUID) -> BloggerProfile:
    return BloggerProfile(
        user_id=user_id,
        instagram_url="https://instagram.com/test",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_show_profile_from_user_none() -> None:
    """Show profile does nothing when from_user is None."""
    message = FakeMessage(user=None)
    service = _FakeProfileServiceUserMissing()
    await show_profile(message, service)
    assert not message.answers


@pytest.mark.asyncio
async def test_show_profile_both_roles(user_repo) -> None:
    """Show both roles in profile output."""

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000810"),
        external_id="1",
        username="user",
    )
    message = FakeMessage(user=FakeUser(1))
    service = FakeProfileService(user=user, has_blogger=True, has_advertiser=True)

    await show_profile(message, service)

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Роли: Блогер, Рекламодатель" in answer_text


@pytest.mark.asyncio
async def test_show_profile_missing_user() -> None:
    """Notify when user is missing."""

    class MissingProfileService:
        async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage(user=FakeUser(1))
    await show_profile(message, MissingProfileService())

    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_missing_profiles(user_repo) -> None:
    """Show hints when role profiles are missing."""

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000811"),
        external_id="2",
        username="user",
    )

    class PartialProfileService:
        async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return user

        async def get_blogger_profile(self, user_id):  # type: ignore[no-untyped-def]
            return None

        async def get_advertiser_profile(self, user_id):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage(user=FakeUser(2))
    await show_profile(message, PartialProfileService())

    assert message.answers
    assert "Профиль блогера" in message.answers[0]
    assert "Профиль рекламодателя" in message.answers[0]
    assert "Не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_blogger_keyboard_not_confirmed(user_repo) -> None:
    """Show verification button for unconfirmed blogger."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000812"),
        external_id="3",
        username="blogger",
    )
    message = FakeMessage(user=FakeUser(3))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False, blogger_confirmed=False
    )

    await show_profile(message, service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    # blogger_profile_view_keyboard: Edit profile, Confirm Instagram, My profile
    assert len(keyboard.keyboard) == 3
    assert keyboard.keyboard[0][0].text == "Редактировать профиль"
    assert keyboard.keyboard[1][0].text == CONFIRM_INSTAGRAM_BUTTON_TEXT
    assert keyboard.keyboard[2][0].text == MY_PROFILE_BUTTON_TEXT


@pytest.mark.asyncio
async def test_show_profile_blogger_keyboard_confirmed(user_repo) -> None:
    """Hide verification button for confirmed blogger."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000813"),
        external_id="4",
        username="blogger",
    )
    message = FakeMessage(user=FakeUser(4))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False, blogger_confirmed=True
    )

    await show_profile(message, service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    # blogger_profile_view_keyboard when confirmed: Edit profile, My profile
    assert len(keyboard.keyboard) == 2
    assert keyboard.keyboard[0][0].text == "Редактировать профиль"
    assert keyboard.keyboard[1][0].text == MY_PROFILE_BUTTON_TEXT


@pytest.mark.asyncio
async def test_show_profile_advertiser_keyboard(user_repo) -> None:
    """Show advertiser keyboard for advertiser."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000814"),
        external_id="5",
        username="advertiser",
    )
    message = FakeMessage(user=FakeUser(5))
    service = FakeProfileService(user=user, has_blogger=False, has_advertiser=True)

    await show_profile(message, service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    assert any(
        btn.text == MY_PROFILE_BUTTON_TEXT for row in keyboard.keyboard for btn in row
    )


# --- Edit profile flow ---


@pytest.mark.asyncio
async def test_edit_profile_start_user_missing(user_repo) -> None:
    """Edit profile start notifies when user is missing."""
    message = FakeMessage(text="Редактировать профиль", user=FakeUser(1))
    state = FakeFSMContext()
    service = _FakeProfileServiceUserMissing()
    await edit_profile_start(
        message, state, service, fsm_draft_service=FakeFsmDraftService()
    )
    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_start_blogger_missing(user_repo) -> None:
    """Edit profile start notifies when blogger profile is missing."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000815"),
        external_id="6",
        username="user",
    )
    message = FakeMessage(text="Редактировать профиль", user=FakeUser(6))
    state = FakeFSMContext()
    service = FakeProfileService(user=user, has_blogger=False, has_advertiser=False)
    await edit_profile_start(
        message, state, service, fsm_draft_service=FakeFsmDraftService()
    )
    assert message.answers
    assert "Профиль не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_start_success(user_repo) -> None:
    """Edit profile start shows field selection."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000816"),
        external_id="7",
        username="user",
    )
    message = FakeMessage(text="Редактировать профиль", user=FakeUser(7))
    state = FakeFSMContext()
    service = FakeProfileService(user=user, has_blogger=True, has_advertiser=False)
    await edit_profile_start(
        message, state, service, fsm_draft_service=FakeFsmDraftService()
    )
    assert message.answers
    assert "Выберите раздел" in message.answers[0][0]
    assert state.state is not None


@pytest.mark.asyncio
async def test_edit_profile_choose_field_my_profile(user_repo) -> None:
    """Choosing 'Мой профиль' clears state and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000817"),
        external_id="8",
        username="user",
    )
    message = FakeMessage(text=MY_PROFILE_BUTTON_TEXT, user=FakeUser(8))
    state = FakeFSMContext()
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message, state, profile_service, reg_service, role_service
    )
    assert state.cleared is True
    assert message.answers
    assert "👤 Ваш профиль" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_field_invalid(user_repo) -> None:
    """Choosing invalid text asks to use keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000818"),
        external_id="9",
        username="user",
    )
    message = FakeMessage(text="Invalid", user=FakeUser(9))
    state = FakeFSMContext()
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message, state, profile_service, reg_service, role_service
    )
    assert message.answers
    assert "Выберите один из разделов" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_choose_field_nickname(user_repo) -> None:
    """Choosing Имя/ник prompts with support keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000834"),
        external_id="36",
        username="user",
    )
    message = FakeMessage(text="Имя/ник", user=FakeUser(36))
    state = FakeFSMContext()
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message, state, profile_service, reg_service, role_service
    )
    assert message.answers
    assert "имя или ник" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "nickname"


@pytest.mark.asyncio
async def test_edit_profile_choose_field_city(user_repo) -> None:
    """Choosing City prompts for new value."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000819"),
        external_id="10",
        username="user",
    )
    message = FakeMessage(text="Город", user=FakeUser(10))
    state = FakeFSMContext()
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message, state, profile_service, reg_service, role_service
    )
    assert message.answers
    assert "город" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "city"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_missing_state(user_repo) -> None:
    """Enter value with missing state data replies session expired."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081a"),
        external_id="11",
        username="user",
    )
    message = FakeMessage(text="Kazan", user=FakeUser(11))
    state = FakeFSMContext()
    state._data = {}
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Сессия истекла" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_missing(user_repo) -> None:
    """Enter value when blogger profile is gone replies profile not found."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081b"),
        external_id="12",
        username="user",
    )
    message = FakeMessage(text="Kazan", user=FakeUser(12))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": user.user_id,
        "edit_external_id": "12",
    }
    service = FakeProfileService(user=user, has_blogger=False, has_advertiser=False)
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_city_empty(user_repo) -> None:
    """Enter empty city gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081c"),
        external_id="13",
        username="user",
    )
    message = FakeMessage(text="", user=FakeUser(13))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": user.user_id,
        "edit_external_id": "13",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Город не может быть пустым" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_city_success(user_repo) -> None:
    """Enter valid city updates profile and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081d"),
        external_id="14",
        username="user",
    )
    message = FakeMessage(text="Kazan", user=FakeUser(14))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "14",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert state.cleared is True
    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Профиль обновлён" in text
    assert reg_service.update_calls
    assert reg_service.update_calls[0][1].get("city") == "Kazan"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_nickname_success(user_repo) -> None:
    """Enter valid nickname updates user and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081e"),
        external_id="15",
        username="user",
    )
    message = FakeMessage(text="NewNick", user=FakeUser(15))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "nickname",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "15",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert state.cleared is True
    assert role_service.set_user_calls
    assert role_service.set_user_calls[0][2] == "NewNick"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_duplicate(user_repo) -> None:
    """Enter Instagram URL already used by another user gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081f"),
        external_id="16",
        username="user",
    )
    other_id = UUID("00000000-0000-0000-0000-000000000820")
    message = FakeMessage(text="https://instagram.com/taken", user=FakeUser(16))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "instagram_url",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "16",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    existing = BloggerProfile(
        user_id=other_id,
        instagram_url="https://instagram.com/taken",
        confirmed=False,
        city="Moscow",
        topics={},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    reg_service = FakeBloggerRegistrationService(get_by_instagram=existing)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "уже зарегистрирован" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_success(user_repo) -> None:
    """Enter valid Instagram URL updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000821"),
        external_id="17",
        username="user",
    )
    message = FakeMessage(text="https://instagram.com/newuser", user=FakeUser(17))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "instagram_url",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "17",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert state.cleared is True
    assert (
        reg_service.update_calls[0][1].get("instagram_url")
        == "https://instagram.com/newuser"
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_gender_success(user_repo) -> None:
    """Enter valid audience gender updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000822"),
        external_id="18",
        username="user",
    )
    message = FakeMessage(text="👥 Примерно поровну", user=FakeUser(18))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_gender",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "18",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert reg_service.update_calls[0][1].get("audience_gender") == AudienceGender.ALL


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_age_success(user_repo) -> None:
    """Enter valid audience age updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000823"),
        external_id="19",
        username="user",
    )
    message = FakeMessage(text="25–34", user=FakeUser(19))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_age",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "19",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert reg_service.update_calls[0][1].get("audience_age_min") == 25
    assert reg_service.update_calls[0][1].get("audience_age_max") == 34


@pytest.mark.asyncio
async def test_edit_profile_enter_value_barter_success(user_repo) -> None:
    """Enter barter Yes updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000824"),
        external_id="20",
        username="user",
    )
    message = FakeMessage(text="Да", user=FakeUser(20))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "barter",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "20",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert reg_service.update_calls[0][1].get("barter") is True


@pytest.mark.asyncio
async def test_edit_profile_enter_value_work_format_success(user_repo) -> None:
    """Enter work format updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000825"),
        external_id="21",
        username="user",
    )
    message = FakeMessage(text=WORK_FORMAT_ADS_BUTTON_TEXT, user=FakeUser(21))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "work_format",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "21",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert (
        reg_service.update_calls[0][1].get("work_format") == WorkFormat.ADS_IN_ACCOUNT
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_nickname_empty(user_repo) -> None:
    """Empty nickname gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000827"),
        external_id="23",
        username="user",
    )
    message = FakeMessage(text="", user=FakeUser(23))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "nickname",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "23",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Имя не может быть пустым" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_bad_format(user_repo) -> None:
    """Instagram URL without instagram.com/ gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000828"),
        external_id="24",
        username="user",
    )
    message = FakeMessage(text="https://example.com/foo", user=FakeUser(24))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "instagram_url",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "24",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Неверный формат ссылки" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_regex_fail(user_repo) -> None:
    """Instagram URL with invalid format (regex) gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000829"),
        external_id="25",
        username="user",
    )
    message = FakeMessage(text="https://instagram.com/", user=FakeUser(25))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "instagram_url",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "25",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Неверный формат ссылки Instagram" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_topics_empty(user_repo) -> None:
    """Empty topics get validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082a"),
        external_id="26",
        username="user",
    )
    message = FakeMessage(text="  ,  ,  ", user=FakeUser(26))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "topics",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "26",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "хотя бы одну тематику" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_gender_invalid(user_repo) -> None:
    """Invalid audience gender text gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082b"),
        external_id="27",
        username="user",
    )
    message = FakeMessage(text="Другое", user=FakeUser(27))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_gender",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "27",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Выберите одну из кнопок" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_age_invalid(user_repo) -> None:
    """Invalid audience age text gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082c"),
        external_id="28",
        username="user",
    )
    message = FakeMessage(text="30-40", user=FakeUser(28))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_age",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "28",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "кнопок возраста" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_geo_empty(user_repo) -> None:
    """Empty audience geo gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082d"),
        external_id="29",
        username="user",
    )
    message = FakeMessage(text="", user=FakeUser(29))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_geo",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "29",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "хотя бы один город" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_geo_too_many(user_repo) -> None:
    """More than 3 cities in audience geo gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082e"),
        external_id="30",
        username="user",
    )
    message = FakeMessage(text="Moscow, SPB, Kazan, Omsk", user=FakeUser(30))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_geo",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "30",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "не более 3 городов" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_price_invalid(user_repo) -> None:
    """Non-numeric price gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082f"),
        external_id="31",
        username="user",
    )
    message = FakeMessage(text="abc", user=FakeUser(31))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "price",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "31",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Введите число" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_price_zero(user_repo) -> None:
    """Zero price gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000830"),
        external_id="32",
        username="user",
    )
    message = FakeMessage(text="0", user=FakeUser(32))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "price",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "32",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Цена должна быть больше 0" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_barter_invalid(user_repo) -> None:
    """Invalid barter text gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000831"),
        external_id="33",
        username="user",
    )
    message = FakeMessage(text="Может быть", user=FakeUser(33))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "barter",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "33",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Выберите Да или Нет" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_work_format_invalid(user_repo) -> None:
    """Invalid work format text gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000832"),
        external_id="34",
        username="user",
    )
    message = FakeMessage(text="Другое", user=FakeUser(34))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "work_format",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "34",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    assert "Выберите одну из кнопок" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_topics_success(user_repo) -> None:
    """Valid topics update profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000833"),
        external_id="35",
        username="user",
    )
    message = FakeMessage(text="beauty, fitness", user=FakeUser(35))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "topics",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "35",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert reg_service.update_calls[0][1].get("topics") == {
        "selected": ["beauty", "fitness"]
    }


@pytest.mark.asyncio
async def test_edit_profile_enter_value_unknown_field(user_repo) -> None:
    """Unknown editing field clears state and replies unknown field."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000835"),
        external_id="37",
        username="user",
    )
    message = FakeMessage(text="value", user=FakeUser(37))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "unknown_field",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "37",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert state.cleared is True
    assert message.answers
    assert "Неизвестное поле" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_update_returns_none(user_repo) -> None:
    """When update_blogger_profile returns None user gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000826"),
        external_id="22",
        username="user",
    )
    message = FakeMessage(text="SPB", user=FakeUser(22))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "22",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService(update_returns=None)
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        role_service,
    )
    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Не удалось обновить" in text
