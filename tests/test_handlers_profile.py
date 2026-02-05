"""Tests for profile handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from tests.helpers.factories import create_test_user
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
)
from ugc_bot.application.services.order_service import MAX_ORDER_PRICE
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_INSTAGRAM_BUTTON_TEXT,
    MY_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
)
from ugc_bot.bot.handlers.profile import (
    EditProfileStates,
    edit_profile_choose_field,
    edit_profile_choose_type,
    edit_profile_enter_value,
    edit_profile_start,
    show_profile,
)
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import AudienceGender, MessengerType, WorkFormat


class FakeProfileService:
    """Stub profile service."""

    def __init__(
        self,
        user: User,
        has_blogger: bool,
        has_advertiser: bool,
        blogger_confirmed: bool = True,
        advertiser_city: str | None = None,
        advertiser_company_activity: str | None = None,
        advertiser_site_link: str | None = None,
    ) -> None:
        self._user = user
        self._has_blogger = has_blogger
        self._has_advertiser = has_advertiser
        self._blogger_confirmed = blogger_confirmed
        self._advertiser_city = advertiser_city
        self._advertiser_company_activity = advertiser_company_activity
        self._advertiser_site_link = advertiser_site_link

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
            phone="contact",
            brand="Brand",
            city=self._advertiser_city,
            company_activity=self._advertiser_company_activity,
            site_link=self._advertiser_site_link,
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

    async def get_profile_by_instagram_url(
        self, url: str
    ) -> BloggerProfile | None:
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
        self.set_user_calls.append(
            (external_id, messenger_type.value, username)
        )


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
    await show_profile(message, service, FakeFSMContext())
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
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )

    await show_profile(message, service, FakeFSMContext())

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
    await show_profile(message, MissingProfileService(), FakeFSMContext())

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
    await show_profile(message, PartialProfileService(), FakeFSMContext())

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
        user=user,
        has_blogger=True,
        has_advertiser=False,
        blogger_confirmed=False,
    )

    await show_profile(message, service, FakeFSMContext())

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
        user=user,
        has_blogger=True,
        has_advertiser=False,
        blogger_confirmed=True,
    )

    await show_profile(message, service, FakeFSMContext())

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
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )

    await show_profile(message, service, FakeFSMContext())

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    assert keyboard.keyboard is not None
    assert any(
        btn.text == MY_PROFILE_BUTTON_TEXT
        for row in keyboard.keyboard
        for btn in row
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
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=False
    )
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
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
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
    message = FakeMessage(text="Имя", user=FakeUser(36))
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
    assert "новое имя" in message.answers[0][0].lower()
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
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=False
    )
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
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "город" in text.lower()


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
    message = FakeMessage(
        text="https://instagram.com/newuser", user=FakeUser(17)
    )
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
async def test_edit_profile_enter_value_audience_gender_success(
    user_repo,
) -> None:
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
    assert (
        reg_service.update_calls[0][1].get("audience_gender")
        == AudienceGender.ALL
    )


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
        reg_service.update_calls[0][1].get("work_format")
        == WorkFormat.ADS_IN_ACCOUNT
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
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "символ" in text.lower()


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
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "тематику" in text


@pytest.mark.asyncio
async def test_edit_profile_enter_value_topics_too_many(user_repo) -> None:
    """More than 10 topics gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083b"),
        external_id="41",
        username="user",
    )
    topics = ",".join(f"topic{i}" for i in range(11))
    message = FakeMessage(text=topics, user=FakeUser(41))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "topics",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "41",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "10" in text or "тематик" in text
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_gender_invalid(
    user_repo,
) -> None:
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
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "город" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_geo_too_many(
    user_repo,
) -> None:
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
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "не более 3" in text


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
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "Цена должна" in text or "больше 0" in text


@pytest.mark.asyncio
async def test_edit_profile_enter_value_price_exceeds_max(user_repo) -> None:
    """Price exceeding MAX_ORDER_PRICE gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083a"),
        external_id="40",
        username="user",
    )
    overflow = str(int(MAX_ORDER_PRICE) + 1)
    message = FakeMessage(text=overflow, user=FakeUser(40))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "price",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "40",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "превышает" in text or str(int(MAX_ORDER_PRICE)) in text
    assert not reg_service.update_calls


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


@pytest.mark.asyncio
async def test_show_profile_advertiser_with_optional_fields(user_repo) -> None:
    """Show advertiser profile with city, company_activity, site_link."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000836"),
        external_id="38",
        username="adv",
    )
    message = FakeMessage(user=FakeUser(38))
    service = FakeProfileService(
        user=user,
        has_blogger=False,
        has_advertiser=True,
        advertiser_city="Moscow",
        advertiser_company_activity="Retail",
        advertiser_site_link="https://brand.com",
    )
    await show_profile(message, service, FakeFSMContext())
    ans = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Город: Moscow" in ans
    assert "Деятельность: Retail" in ans
    assert "Сайт: https://brand.com" in ans


@pytest.mark.asyncio
async def test_edit_profile_start_from_user_none(user_repo) -> None:
    """edit_profile_start returns when from_user is None."""
    message = FakeMessage(text="Редактировать профиль", user=None)
    state = FakeFSMContext()
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000837"),
        external_id="39",
        username="u",
    )
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    await edit_profile_start(
        message, state, service, fsm_draft_service=FakeFsmDraftService()
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_edit_profile_start_both_profiles_shows_type_choice(
    user_repo,
) -> None:
    """When user has both blogger and advertiser, show profile type choice."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000838"),
        external_id="40",
        username="u",
    )
    message = FakeMessage(text="Редактировать профиль", user=FakeUser(40))
    state = FakeFSMContext()
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )
    await edit_profile_start(
        message, state, service, fsm_draft_service=FakeFsmDraftService()
    )
    assert "Выберите профиль для редактирования" in message.answers[0][0]
    assert state.state == EditProfileStates.choosing_profile_type


@pytest.mark.asyncio
async def test_edit_profile_start_advertiser_only(user_repo) -> None:
    """When user has only advertiser, go directly to field selection."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000839"),
        external_id="41",
        username="u",
    )
    message = FakeMessage(text="Редактировать профиль", user=FakeUser(41))
    state = FakeFSMContext()
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    await edit_profile_start(
        message, state, service, fsm_draft_service=FakeFsmDraftService()
    )
    assert "Выберите раздел" in message.answers[0][0]
    assert state._data.get("edit_profile_type") == "advertiser"
    assert state.state == EditProfileStates.choosing_field


@pytest.mark.asyncio
async def test_edit_profile_choose_type_blogger(user_repo) -> None:
    """edit_profile_choose_type selects blogger profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083a"),
        external_id="42",
        username="u",
    )
    message = FakeMessage(
        text="Редактировать профиль блогера", user=FakeUser(42)
    )
    state = FakeFSMContext()
    state.state = EditProfileStates.choosing_profile_type
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "42"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )
    await edit_profile_choose_type(message, state, service)
    assert state._data.get("edit_profile_type") == "blogger"
    assert "Выберите раздел" in message.answers[0][0]


@pytest.mark.asyncio
async def test_edit_profile_choose_type_advertiser(user_repo) -> None:
    """edit_profile_choose_type selects advertiser profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083b"),
        external_id="43",
        username="u",
    )
    message = FakeMessage(
        text="Редактировать профиль рекламодателя", user=FakeUser(43)
    )
    state = FakeFSMContext()
    state.state = EditProfileStates.choosing_profile_type
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "43"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )
    await edit_profile_choose_type(message, state, service)
    assert state._data.get("edit_profile_type") == "advertiser"
    assert "Выберите раздел" in message.answers[0][0]


@pytest.mark.asyncio
async def test_edit_profile_choose_type_invalid(user_repo) -> None:
    """edit_profile_choose_type rejects invalid choice."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083c"),
        external_id="44",
        username="u",
    )
    message = FakeMessage(text="Другое", user=FakeUser(44))
    state = FakeFSMContext()
    state.state = EditProfileStates.choosing_profile_type
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "44"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )
    await edit_profile_choose_type(message, state, service)
    ans = message.answers[0]
    assert "Выберите один из вариантов" in (
        ans if isinstance(ans, str) else ans[0]
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_type_my_profile_returns(user_repo) -> None:
    """edit_profile_choose_type with MY_PROFILE clears and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083d"),
        external_id="45",
        username="u",
    )
    message = FakeMessage(text=MY_PROFILE_BUTTON_TEXT, user=FakeUser(45))
    state = FakeFSMContext()
    state.state = EditProfileStates.choosing_profile_type
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "45"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )
    await edit_profile_choose_type(message, state, service)
    assert state.cleared
    assert "👤 Ваш профиль" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_field_advertiser_phone(user_repo) -> None:
    """edit_profile_choose_field for advertiser shows phone prompt."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083e"),
        external_id="46",
        username="u",
    )
    message = FakeMessage(text="Телефон", user=FakeUser(46))
    state = FakeFSMContext()
    state._data = {
        "edit_user_id": user.user_id,
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message, state, service, reg_service, role_service
    )
    assert "телефона" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "phone"


@pytest.mark.asyncio
async def test_edit_profile_choose_field_advertiser_brand(user_repo) -> None:
    """edit_profile_choose_field for advertiser shows brand prompt."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083f"),
        external_id="47",
        username="u",
    )
    message = FakeMessage(text="Бренд", user=FakeUser(47))
    state = FakeFSMContext()
    state._data = {
        "edit_user_id": user.user_id,
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message, state, service, reg_service, role_service
    )
    assert "бренда" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "brand"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_name_success(
    user_repo,
) -> None:
    """Edit advertiser name updates user and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000840"),
        external_id="48",
        username="u",
    )
    message = FakeMessage(text="NewName", user=FakeUser(48))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "name",
        "edit_user_id": user.user_id,
        "edit_external_id": "48",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    reg_service = FakeBloggerRegistrationService()
    adv_service = FakeAdvertiserRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_enter_value(
        message, state, service, reg_service, adv_service, role_service
    )
    assert state.cleared
    assert role_service.set_user_calls[0][2] == "NewName"
    assert "Профиль обновлён" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_name_empty(
    user_repo,
) -> None:
    """Edit advertiser name empty gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000841"),
        external_id="49",
        username="u",
    )
    message = FakeMessage(text="", user=FakeUser(49))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "name",
        "edit_user_id": user.user_id,
        "edit_external_id": "49",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "символ" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_success(
    user_repo,
) -> None:
    """Edit advertiser phone updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000842"),
        external_id="50",
        username="u",
    )
    message = FakeMessage(text="+79001234567", user=FakeUser(50))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "phone",
        "edit_user_id": user.user_id,
        "edit_external_id": "50",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService(
        update_returns=AdvertiserProfile(
            user_id=user.user_id, phone="+79001234567", brand="B"
        )
    )
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert adv_service.update_calls[0][1].get("phone") == "+79001234567"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_empty(
    user_repo,
) -> None:
    """Edit advertiser phone empty gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000843"),
        external_id="51",
        username="u",
    )
    message = FakeMessage(text="", user=FakeUser(51))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "phone",
        "edit_user_id": user.user_id,
        "edit_external_id": "51",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "телефон" in text.lower() or "цифр" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_brand_empty(
    user_repo,
) -> None:
    """Edit advertiser brand empty gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000844"),
        external_id="52",
        username="u",
    )
    message = FakeMessage(text="", user=FakeUser(52))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "brand",
        "edit_user_id": user.user_id,
        "edit_external_id": "52",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "символ" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_site_link(user_repo) -> None:
    """Edit advertiser site_link updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000845"),
        external_id="53",
        username="u",
    )
    message = FakeMessage(text="https://site.com", user=FakeUser(53))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "site_link",
        "edit_user_id": user.user_id,
        "edit_external_id": "53",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService(
        update_returns=AdvertiserProfile(
            user_id=user.user_id,
            phone="+7",
            brand="B",
            site_link="https://site.com",
        )
    )
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert adv_service.update_calls[0][1].get("site_link") == "https://site.com"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_invalid(
    user_repo,
) -> None:
    """Edit advertiser phone with invalid format gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084a"),
        external_id="60",
        username="u",
    )
    message = FakeMessage(text="+7900", user=FakeUser(60))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "phone",
        "edit_user_id": user.user_id,
        "edit_external_id": "60",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "цифр" in text or "корректный" in text.lower()
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_site_link_invalid(
    user_repo,
) -> None:
    """Edit advertiser site_link with invalid URL gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084b"),
        external_id="61",
        username="u",
    )
    message = FakeMessage(text="not-a-url", user=FakeUser(61))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "site_link",
        "edit_user_id": user.user_id,
        "edit_external_id": "61",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "ссылк" in text.lower() or "http" in text.lower()
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_missing(user_repo) -> None:
    """Edit when advertiser profile is gone replies profile not found."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000846"),
        external_id="54",
        username="u",
    )
    message = FakeMessage(text="+7", user=FakeUser(54))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "phone",
        "edit_user_id": user.user_id,
        "edit_external_id": "54",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=False
    )
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert "Профиль рекламодателя не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_update_none(
    user_repo,
) -> None:
    """When advertiser update returns None user gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000847"),
        external_id="55",
        username="u",
    )
    message = FakeMessage(text="+79001234567", user=FakeUser(55))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "phone",
        "edit_user_id": user.user_id,
        "edit_external_id": "55",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService(update_returns=None)
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert "Не удалось обновить" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_barter_no(user_repo) -> None:
    """Enter barter No updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000848"),
        external_id="56",
        username="u",
    )
    message = FakeMessage(text="Нет", user=FakeUser(56))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "barter",
        "edit_user_id": user.user_id,
        "edit_external_id": "56",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert reg_service.update_calls[0][1].get("barter") is False


@pytest.mark.asyncio
async def test_edit_profile_enter_value_work_format_ugc_only(user_repo) -> None:
    """Enter work format UGC only updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000849"),
        external_id="57",
        username="u",
    )
    message = FakeMessage(
        text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT, user=FakeUser(57)
    )
    state = FakeFSMContext()
    state._data = {
        "editing_field": "work_format",
        "edit_user_id": user.user_id,
        "edit_external_id": "57",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        reg_service,
        FakeAdvertiserRegistrationService(),
        FakeUserRoleService(),
    )
    assert (
        reg_service.update_calls[0][1].get("work_format") == WorkFormat.UGC_ONLY
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_unknown_field(
    user_repo,
) -> None:
    """Advertiser unknown field clears state and replies unknown."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084a"),
        external_id="58",
        username="u",
    )
    message = FakeMessage(text="value", user=FakeUser(58))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "unknown",
        "edit_user_id": user.user_id,
        "edit_external_id": "58",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        service,
        FakeBloggerRegistrationService(),
        adv_service,
        FakeUserRoleService(),
    )
    assert state.cleared
    assert "Неизвестное поле" in message.answers[0]
