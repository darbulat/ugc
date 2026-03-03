"""Tests for profile handler."""

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
    FakeWebAppData,
)
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_PROFILE_AGREE,
    CALLBACK_PROFILE_AUDIENCE_F,
    CALLBACK_PROFILE_EDIT,
    CALLBACK_PROFILE_EDIT_FIELD_PREFIX,
    CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
    CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
    CALLBACK_PROFILE_MY_PROFILE,
    CALLBACK_PROFILE_REGION_PREFIX,
)
from ugc_bot.bot.handlers.profile import (
    _ADVERTISER_AGREEMENTS_STATE,
    _BLOGGER_AGREEMENTS_STATE,
    EditProfileStates,
    edit_profile_choose_field,
    edit_profile_choose_type,
    edit_profile_enter_value,
    edit_profile_start,
    handle_city_web_app_data_profile,
    handle_profile_agree_callback,
    handle_profile_edit_callback,
    handle_profile_edit_choice_callback,
    handle_profile_edit_field_callback,
    handle_profile_edit_type_callback,
    handle_profile_my_profile_callback,
    handle_profile_region_callback,
    show_profile,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile, BloggerProfile, User
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    WorkFormat,
)
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)

_TEXTS_RU = DEFAULT_TEXTS["ru"]


@pytest.fixture
def config() -> AppConfig:
    """Config for profile tests (same as _profile_test_config())."""
    return _profile_test_config()


def _profile_test_config() -> AppConfig:
    """Minimal config for profile handler tests."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "sqlite:///",
            "ADMIN_USERNAME": "a",
            "ADMIN_PASSWORD": "p",
            "ADMIN_SECRET": "s",
            "KAFKA_ENABLED": "false",
            "FEEDBACK_ENABLED": "false",
            "ROLE_REMINDER_ENABLED": "false",
            "REDIS_URL": "redis://",
            "USE_REDIS_STORAGE": "false",
            "DOCS_OFFER_URL": "",
            "DOCS_PRIVACY_URL": "",
            "DOCS_CONSENT_URL": "",
        }
    )


class FakeProfileService:
    """Stub profile service."""

    def __init__(
        self,
        user: User,
        has_blogger: bool,
        has_advertiser: bool,
        blogger_confirmed: bool = True,
        blogger_gender: BloggerGender | None = None,
        advertiser_city: str | None = None,
        advertiser_company_activity: str | None = None,
        advertiser_site_link: str | None = None,
    ) -> None:
        self._user = user
        self._has_blogger = has_blogger
        self._has_advertiser = has_advertiser
        self._blogger_confirmed = blogger_confirmed
        self._blogger_gender = blogger_gender
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
            blogger_gender=self._blogger_gender,
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

    def __init__(self, get_user_by_id_returns: User | None = None) -> None:
        self.set_user_calls: list[tuple[str, str, str]] = []
        self._get_user_by_id_returns = get_user_by_id_returns

    async def set_user(
        self,
        external_id: str,
        messenger_type: MessengerType,
        username: str,
    ) -> None:
        self.set_user_calls.append(
            (external_id, messenger_type.value, username)
        )

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        """Return configured value for tests (e.g. None to cover error path)."""
        return self._get_user_by_id_returns


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
        blogger_gender=None,
    )


@pytest.mark.asyncio
async def test_show_profile_from_user_none(config, bot_texts_service) -> None:
    """Show profile does nothing when from_user is None."""
    message = FakeMessage(user=None)
    service = _FakeProfileServiceUserMissing()
    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_show_profile_both_roles(
    user_repo, config, bot_texts_service
) -> None:
    """Show both roles in profile output."""

    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000810"),
        external_id="1",
        username="user",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(user=FakeUser(1))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )

    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    answer_text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Роли: Блогер, Рекламодатель" in answer_text


@pytest.mark.asyncio
async def test_show_profile_missing_user(config, bot_texts_service) -> None:
    """Notify when user is missing."""

    class MissingProfileService:
        async def get_user_by_external(self, external_id, messenger_type):  # type: ignore[no-untyped-def]
            return None

    message = FakeMessage(user=FakeUser(1))
    await show_profile(
        message,
        MissingProfileService(),
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_shows_agreement_when_not_confirmed(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """When user has profile but no agreement, show agreement and set state."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000809"),
        external_id="9",
        username="u",
        agreement_confirmed_at=None,
    )
    message = FakeMessage(user=FakeUser(9))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    state = FakeFSMContext()
    await show_profile(
        message,
        service,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    first = (
        message.answers[0][0]
        if isinstance(message.answers[0], tuple)
        else message.answers[0]
    )
    assert "согласи" in first.lower()
    assert state.state == _BLOGGER_AGREEMENTS_STATE


@pytest.mark.asyncio
async def test_show_profile_missing_profiles(
    user_repo, config, bot_texts_service
) -> None:
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
    await show_profile(
        message,
        PartialProfileService(),
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.answers
    assert "Профиль блогера" in message.answers[0]
    assert "Профиль рекламодателя" in message.answers[0]
    assert "Не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_blogger_keyboard_not_confirmed(
    user_repo, config, bot_texts_service
) -> None:
    """Show verification button for unconfirmed blogger."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000812"),
        external_id="3",
        username="blogger",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(user=FakeUser(3))
    service = FakeProfileService(
        user=user,
        has_blogger=True,
        has_advertiser=False,
        blogger_confirmed=False,
    )

    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    rows = (
        getattr(keyboard, "inline_keyboard", None)
        or getattr(keyboard, "rows", None)
        or getattr(keyboard, "keyboard", None)
    )
    assert rows is not None
    # blogger_profile_view_keyboard: Edit profile, Confirm Instagram, My profile
    assert len(rows) == 3
    assert rows[0][0].text == "Редактировать профиль"
    assert rows[1][0].text == _TEXTS_RU["btn_confirm_instagram"]
    assert rows[2][0].text == _TEXTS_RU["btn_my_profile"]


@pytest.mark.asyncio
async def test_show_profile_blogger_keyboard_confirmed(
    user_repo, config, bot_texts_service
) -> None:
    """Hide verification button for confirmed blogger."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000813"),
        external_id="4",
        username="blogger",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(user=FakeUser(4))
    service = FakeProfileService(
        user=user,
        has_blogger=True,
        has_advertiser=False,
        blogger_confirmed=True,
    )

    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    rows = (
        getattr(keyboard, "inline_keyboard", None)
        or getattr(keyboard, "rows", None)
        or getattr(keyboard, "keyboard", None)
    )
    assert rows is not None
    # blogger_profile_view_keyboard when confirmed: Edit profile, My profile
    assert len(rows) == 2
    assert rows[0][0].text == "Редактировать профиль"
    assert rows[1][0].text == _TEXTS_RU["btn_my_profile"]


@pytest.mark.asyncio
async def test_show_profile_advertiser_keyboard(
    user_repo, config, bot_texts_service
) -> None:
    """Show advertiser keyboard for advertiser."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000814"),
        external_id="5",
        username="advertiser",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(user=FakeUser(5))
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )

    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    rows = (
        getattr(keyboard, "inline_keyboard", None)
        or getattr(keyboard, "rows", None)
        or getattr(keyboard, "keyboard", None)
    )
    assert rows is not None
    assert any(
        btn.text == _TEXTS_RU["btn_my_profile"] for row in rows for btn in row
    )


@pytest.mark.asyncio
async def test_profile_agree_callback_blogger_confirms_and_shows_profile(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Profile agree callback confirms blogger agreement and shows profile."""
    user = await create_test_user(
        user_repo,
        external_id="60",
        username="blogger_cb",
        agreement_confirmed_at=None,
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=False
    )
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    blogger_reg_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    adv_reg_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_BLOGGER_AGREEMENTS_STATE)
    await state.update_data(user_id=user.user_id)
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AGREE,
        user=FakeUser(60, "blogger_cb", "User"),
        message=FakeMessage(user=FakeUser(60, "blogger_cb", "User")),
    )

    await handle_profile_agree_callback(
        callback,
        state,
        profile_service=profile_service,
        user_role_service=user_role_service,
        blogger_registration_service=blogger_reg_service,
        advertiser_registration_service=adv_reg_service,
        config=config,
        bot_texts_service=bot_texts_service,
        currency_symbol="₽",
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) >= 1
    assert any(
        "instagram" in s["text"].lower() or "профиль" in s["text"].lower()
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_profile_agree_callback_wrong_state_only_answers(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When state is not agreements, callback only answers."""
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    adv_reg = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.choosing_field.state)
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AGREE,
        user=FakeUser(61, "u", "U"),
        message=FakeMessage(user=FakeUser(61, "u", "U")),
    )

    await handle_profile_agree_callback(
        callback,
        state,
        profile_service=profile_service,
        user_role_service=user_role_service,
        blogger_registration_service=blogger_reg,
        advertiser_registration_service=adv_reg,
        config=config,
        bot_texts_service=bot_texts_service,
        currency_symbol="₽",
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.answered_callbacks) == 1
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_profile_agree_callback_no_user_id_sends_expired(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When user_id missing in state, send session expired and clear."""
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    adv_reg = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_BLOGGER_AGREEMENTS_STATE)
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AGREE,
        user=FakeUser(62, "u", "U"),
        message=FakeMessage(user=FakeUser(62, "u", "U")),
    )

    await handle_profile_agree_callback(
        callback,
        state,
        profile_service=profile_service,
        user_role_service=user_role_service,
        blogger_registration_service=blogger_reg,
        advertiser_registration_service=adv_reg,
        config=config,
        bot_texts_service=bot_texts_service,
        currency_symbol="₽",
        messenger_client=client,
        event_adapter=adapter,
    )

    assert any("Сессия истекла" in s["text"] for s in client.sent_text)
    assert state.cleared


@pytest.mark.asyncio
async def test_profile_agree_callback_advertiser_confirms_and_shows_profile(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Profile agree callback for advertiser confirms and shows profile."""
    from tests.helpers.factories import create_test_advertiser_profile

    user = await create_test_user(
        user_repo,
        external_id="63",
        username="adv_cb",
        agreement_confirmed_at=None,
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    adv_reg = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_ADVERTISER_AGREEMENTS_STATE)
    await state.update_data(user_id=user.user_id)
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AGREE,
        user=FakeUser(63, "adv_cb", "User"),
        message=FakeMessage(user=FakeUser(63, "adv_cb", "User")),
    )

    await handle_profile_agree_callback(
        callback,
        state,
        profile_service=profile_service,
        user_role_service=user_role_service,
        blogger_registration_service=blogger_reg,
        advertiser_registration_service=adv_reg,
        config=config,
        bot_texts_service=bot_texts_service,
        currency_symbol="₽",
        messenger_client=client,
        event_adapter=adapter,
    )

    assert len(client.sent_text) >= 1
    assert any(
        "Создать заказ" in s["text"] or "профиль" in s["text"].lower()
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_handle_profile_edit_callback_user_not_found(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit callback when user not in DB sends 'Профиль не найден'."""
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT,
        user=FakeUser(999),
        message=FakeMessage(user=FakeUser(999)),
    )
    await handle_profile_edit_callback(
        callback,
        FakeFSMContext(),
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Профиль не найден" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_callback_no_profiles(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit callback when user has no blogger/advertiser profile."""
    await create_test_user(user_repo, external_id="70", username="noprofile")
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT,
        user=FakeUser(70),
        message=FakeMessage(user=FakeUser(70)),
    )
    await handle_profile_edit_callback(
        callback,
        FakeFSMContext(),
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Профиль не заполнен" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_callback_both_profiles(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit callback when user has both profiles shows type choice."""
    user = await create_test_user(user_repo, external_id="71", username="both")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT,
        user=FakeUser(71),
        message=FakeMessage(user=FakeUser(71)),
    )
    state = FakeFSMContext()
    await handle_profile_edit_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "Выберите профиль для редактирования" in s["text"]
        for s in client.sent_text
    )
    assert state.state == EditProfileStates.choosing_profile_type.state


@pytest.mark.asyncio
async def test_handle_profile_edit_callback_blogger_only(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit callback with only blogger profile shows field list."""
    user = await create_test_user(user_repo, external_id="72", username="blog")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT,
        user=FakeUser(72),
        message=FakeMessage(user=FakeUser(72)),
    )
    state = FakeFSMContext()
    await handle_profile_edit_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "Выберите раздел для редактирования" in s["text"]
        for s in client.sent_text
    )
    assert state._data.get("edit_profile_type") == "blogger"


@pytest.mark.asyncio
async def test_handle_profile_my_profile_callback_shows_agreement(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """My profile callback when agreement not confirmed sends agreement."""
    user = await create_test_user(
        user_repo,
        external_id="73",
        username="mp",
        agreement_confirmed_at=None,
    )
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MY_PROFILE,
        user=FakeUser(73),
        message=FakeMessage(user=FakeUser(73)),
    )
    state = FakeFSMContext()
    await handle_profile_my_profile_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("согласи" in s["text"].lower() for s in client.sent_text)
    assert state.state == _BLOGGER_AGREEMENTS_STATE


@pytest.mark.asyncio
async def test_handle_profile_edit_type_callback_blogger(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit type callback blogger shows blogger field list."""
    user = await create_test_user(user_repo, external_id="74", username="et")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="74",
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT_TYPE_BLOGGER,
        user=FakeUser(74),
        message=FakeMessage(user=FakeUser(74)),
    )
    await handle_profile_edit_type_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        profile_service=profile_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "Выберите раздел для редактирования" in s["text"]
        for s in client.sent_text
    )
    assert state._data.get("edit_profile_type") == "blogger"


@pytest.mark.asyncio
async def test_handle_profile_edit_type_callback_advertiser(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit type callback advertiser shows advertiser field list."""
    user = await create_test_user(
        user_repo, external_id="75", username="et_adv"
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="75",
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT_TYPE_ADVERTISER,
        user=FakeUser(75),
        message=FakeMessage(user=FakeUser(75)),
    )
    await handle_profile_edit_type_callback(
        callback,
        state,
        config=config,
        bot_texts_service=bot_texts_service,
        profile_service=profile_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "Выберите раздел для редактирования" in s["text"]
        for s in client.sent_text
    )
    assert state._data.get("edit_profile_type") == "advertiser"


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_nickname(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for nickname sends name prompt."""
    user = await create_test_user(user_repo, external_id="76", username="ef")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="76",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}nickname",
        user=FakeUser(76),
        message=FakeMessage(user=FakeUser(76)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("новое имя" in s["text"].lower() for s in client.sent_text)
    assert state._data.get("editing_field") == "nickname"


@pytest.mark.asyncio
async def test_handle_profile_edit_choice_callback_audience_gender(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit choice callback for audience_gender updates and shows profile."""
    user = await create_test_user(
        user_repo, external_id="77", username="choice"
    )
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="77",
        edit_profile_type="blogger",
        editing_field="audience_gender",
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AUDIENCE_F,
        user=FakeUser(77),
        message=FakeMessage(user=FakeUser(77)),
    )
    await handle_profile_edit_choice_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "обновлён" in s["text"] or "профиль" in s["text"].lower()
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_handle_profile_edit_choice_callback_blogger_gone_clears_state(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When get_blogger_profile returns None, state is cleared and no update."""
    user = await create_test_user(
        user_repo, external_id="77b", username="choice"
    )
    profile_service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=False
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=str(user.user_id),
        edit_external_id="77b",
        edit_profile_type="blogger",
        editing_field="audience_gender",
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AUDIENCE_F,
        user=FakeUser(77),
        message=FakeMessage(user=FakeUser(77)),
    )
    await handle_profile_edit_choice_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert state.cleared


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_city_non_canonical_sends_picker(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Editing city with non-canonical name sends picker hint."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084a"),
        external_id="50",
        username="user",
    )
    message = FakeMessage(text="МаленькийГород", user=FakeUser(50))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "50",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "город" in text.lower() or "выберите" in text.lower()


# --- Edit profile flow ---


@pytest.mark.asyncio
async def test_edit_profile_start_user_missing(
    user_repo, config, bot_texts_service
) -> None:
    """Edit profile start notifies when user is missing."""
    message = FakeMessage(text="Редактировать профиль", user=FakeUser(1))
    state = FakeFSMContext()
    service = _FakeProfileServiceUserMissing()
    await edit_profile_start(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_start_blogger_missing(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    assert "Профиль не заполнен" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_start_success(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    assert "Выберите раздел" in message.answers[0][0]
    assert state.state is not None


@pytest.mark.asyncio
async def test_edit_profile_choose_field_my_profile(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing 'Мой профиль' clears state and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000817"),
        external_id="8",
        username="user",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(text=_TEXTS_RU["btn_my_profile"], user=FakeUser(8))
    state = FakeFSMContext()
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert state.cleared is True
    assert message.answers
    assert "👤 Ваш профиль" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_field_invalid(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert message.answers
    first = (
        message.answers[0][0]
        if isinstance(message.answers[0], tuple)
        else message.answers[0]
    )
    assert "Выберите один из разделов" in first


@pytest.mark.asyncio
async def test_edit_profile_choose_field_nickname(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert message.answers
    assert "новое имя" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "nickname"


@pytest.mark.asyncio
async def test_edit_profile_choose_field_city(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert message.answers
    assert "город" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "city"


@pytest.mark.asyncio
async def test_edit_profile_choose_field_blogger_gender(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing Пол prompts for blogger gender with keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000820"),
        external_id="11",
        username="user",
    )
    message = FakeMessage(text="Пол", user=FakeUser(11))
    state = FakeFSMContext()
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    role_service = FakeUserRoleService()
    await edit_profile_choose_field(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert message.answers
    assert "пол" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "blogger_gender"
    assert message.reply_markups
    keyboard = message.reply_markups[0]
    rows = (
        getattr(keyboard, "inline_keyboard", None)
        or getattr(keyboard, "rows", None)
        or getattr(keyboard, "keyboard", None)
    )
    assert rows is not None
    assert any(b.text == "Мужской" for row in rows for b in row)
    assert any(b.text == "Женский" for row in rows for b in row)


@pytest.mark.asyncio
async def test_edit_profile_enter_value_missing_state(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Сессия истекла" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_missing(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Профиль не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_city_empty(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "город" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_city_success(
    user_repo, config, bot_texts_service
) -> None:
    """Enter valid city (from dictionary) updates profile and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081d"),
        external_id="14",
        username="user",
    )
    message = FakeMessage(text="Казань", user=FakeUser(14))
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert state.cleared is True
    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Профиль обновлён" in text
    assert reg_service.update_calls
    assert reg_service.update_calls[0][1].get("city") == "казань"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_city_multi_region_shows_region_keyboard(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Enter city in multiple regions shows region picker, state kept."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000081e"),
        external_id="14",
        username="user",
    )
    message = FakeMessage(text="Железногорск", user=FakeUser(14))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "14",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert state.cleared is False
    assert state._data.get("pending_city_edit") == "железногорск"
    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "регион" in text.lower()
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_nickname_success(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert state.cleared is True
    assert role_service.set_user_calls
    assert role_service.set_user_calls[0][2] == "NewNick"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_duplicate(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "уже зарегистрирован" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_success(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert state.cleared is True
    assert (
        reg_service.update_calls[0][1].get("instagram_url")
        == "https://instagram.com/newuser"
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_normalized_with_query(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Instagram URL with query string is normalized when saving profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000831"),
        external_id="31",
        username="user",
    )
    message = FakeMessage(
        text="https://www.instagram.com/edited_user?igsh=abc&utm_source=qr",
        user=FakeUser(31),
    )
    state = FakeFSMContext()
    state._data = {
        "editing_field": "instagram_url",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "31",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert state.cleared is True
    assert (
        reg_service.update_calls[0][1].get("instagram_url")
        == "https://instagram.com/edited_user"
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_gender_success(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert (
        reg_service.update_calls[0][1].get("audience_gender")
        == AudienceGender.ALL
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_gender_success(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Enter valid blogger gender (Male) updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000824"),
        external_id="21",
        username="user",
    )
    message = FakeMessage(text="Мужской", user=FakeUser(21))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "blogger_gender",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert (
        reg_service.update_calls[0][1].get("blogger_gender")
        == BloggerGender.MALE
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_gender_invalid(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Enter invalid blogger gender asks to use buttons."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000825"),
        external_id="22",
        username="user",
    )
    message = FakeMessage(text="Другое", user=FakeUser(22))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "blogger_gender",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "22",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert not reg_service.update_calls
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "кнопок" in text or "Мужской" in text


@pytest.mark.asyncio
async def test_edit_profile_enter_value_birth_date_success(
    user_repo, config, bot_texts_service
) -> None:
    """Enter valid birth date updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082a"),
        external_id="26",
        username="user",
    )
    message = FakeMessage(text="15.05.1995", user=FakeUser(26))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "birth_date",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "26",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert reg_service.update_calls
    assert reg_service.update_calls[0][1].get("birth_date") == date(1995, 5, 15)


@pytest.mark.asyncio
async def test_edit_profile_enter_value_birth_date_invalid(
    user_repo, config, bot_texts_service
) -> None:
    """Enter invalid birth date gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000082b"),
        external_id="27",
        username="user",
    )
    message = FakeMessage(text="32.13.2000", user=FakeUser(27))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "birth_date",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert not reg_service.update_calls
    assert message.answers


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_age_success(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert reg_service.update_calls[0][1].get("audience_age_min") == 25
    assert reg_service.update_calls[0][1].get("audience_age_max") == 34


@pytest.mark.asyncio
async def test_edit_profile_enter_value_barter_success(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert reg_service.update_calls[0][1].get("barter") is True


@pytest.mark.asyncio
async def test_edit_profile_enter_value_work_format_success(
    user_repo, config, bot_texts_service
) -> None:
    """Enter work format updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000825"),
        external_id="21",
        username="user",
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_work_format_ads"], user=FakeUser(21)
    )
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert (
        reg_service.update_calls[0][1].get("work_format")
        == WorkFormat.ADS_IN_ACCOUNT
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_nickname_empty(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "символ" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_bad_format(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Неверный формат ссылки" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_instagram_regex_fail(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Неверный формат ссылки Instagram" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_topics_empty(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "тематику" in text


@pytest.mark.asyncio
async def test_edit_profile_enter_value_topics_too_many(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "10" in text or "тематик" in text
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_gender_invalid(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Выберите одну из кнопок" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_age_invalid(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "кнопок возраста" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_geo_empty(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "город" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_audience_geo_too_many(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "не более 3" in text


@pytest.mark.asyncio
async def test_edit_profile_enter_value_price_invalid(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Введите число" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_price_zero(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "Цена должна" in text or "больше 0" in text


@pytest.mark.asyncio
async def test_edit_profile_enter_value_price_exceeds_max(
    user_repo, config, bot_texts_service
) -> None:
    """Price exceeding max order price gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083a"),
        external_id="40",
        username="user",
    )
    overflow = str(int(10_000.0) + 1)
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "превышает" in text or "10000" in text
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_barter_invalid(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Выберите Да или Нет" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_work_format_invalid(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    assert "Выберите одну из кнопок" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_topics_success(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert reg_service.update_calls[0][1].get("topics") == {
        "selected": ["beauty", "fitness"]
    }


@pytest.mark.asyncio
async def test_edit_profile_enter_value_unknown_field(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert state.cleared is True
    assert message.answers
    assert "Неизвестное поле" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_update_returns_none(
    user_repo, config, bot_texts_service
) -> None:
    """When update_blogger_profile returns None user gets error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000826"),
        external_id="22",
        username="user",
    )
    message = FakeMessage(text="Казань", user=FakeUser(22))
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=role_service,
        max_order_price=10_000.0,
    )
    assert message.answers
    first = message.answers[0]
    text = first[0] if isinstance(first, tuple) else first
    assert "Не удалось обновить" in text


@pytest.mark.asyncio
async def test_show_profile_advertiser_with_optional_fields(
    user_repo, config, bot_texts_service
) -> None:
    """Show advertiser profile with city, company_activity, site_link."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000836"),
        external_id="38",
        username="adv",
        agreement_confirmed_at=datetime.now(timezone.utc),
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
    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )
    ans = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Город: Moscow" in ans
    assert "Деятельность: Retail" in ans
    assert "Сайт: https://brand.com" in ans


@pytest.mark.asyncio
async def test_edit_profile_start_from_user_none(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert not message.answers


@pytest.mark.asyncio
async def test_edit_profile_start_both_profiles_shows_type_choice(
    user_repo,
    config,
    bot_texts_service,
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert "Выберите профиль для редактирования" in message.answers[0][0]
    assert state.state == EditProfileStates.choosing_profile_type


@pytest.mark.asyncio
async def test_edit_profile_start_advertiser_only(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert "Выберите раздел" in message.answers[0][0]
    assert state._data.get("edit_profile_type") == "advertiser"
    assert state.state == EditProfileStates.choosing_field


@pytest.mark.asyncio
async def test_edit_profile_choose_type_blogger(
    user_repo, config, bot_texts_service
) -> None:
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
    await edit_profile_choose_type(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert state._data.get("edit_profile_type") == "blogger"
    assert "Выберите раздел" in message.answers[0][0]


@pytest.mark.asyncio
async def test_edit_profile_choose_type_advertiser(
    user_repo, config, bot_texts_service
) -> None:
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
    await edit_profile_choose_type(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert state._data.get("edit_profile_type") == "advertiser"
    assert "Выберите раздел" in message.answers[0][0]


@pytest.mark.asyncio
async def test_edit_profile_choose_type_invalid(
    user_repo, config, bot_texts_service
) -> None:
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
    await edit_profile_choose_type(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    ans = message.answers[0]
    assert "Выберите один из вариантов" in (
        ans if isinstance(ans, str) else ans[0]
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_type_my_profile_returns(
    user_repo, config, bot_texts_service
) -> None:
    """edit_profile_choose_type with MY_PROFILE clears and shows profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000083d"),
        external_id="45",
        username="u",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(text=_TEXTS_RU["btn_my_profile"], user=FakeUser(45))
    state = FakeFSMContext()
    state.state = EditProfileStates.choosing_profile_type
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "45"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=True
    )
    await edit_profile_choose_type(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert state.cleared
    assert "👤 Ваш профиль" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_field_advertiser_phone(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert "телефона" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "phone"


@pytest.mark.asyncio
async def test_edit_profile_choose_field_advertiser_brand(
    user_repo, config, bot_texts_service
) -> None:
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=role_service,
    )
    assert "бренда" in message.answers[0][0].lower()
    assert state._data.get("editing_field") == "brand"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_name_success(
    user_repo,
    config,
    bot_texts_service,
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
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=adv_service,
        user_role_service=role_service,
        max_order_price=10_000.0,
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
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "символ" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_success(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert adv_service.update_calls[0][1].get("phone") == "+79001234567"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_empty(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "телефон" in text.lower() or "цифр" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_brand_empty(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "символ" in text.lower()


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_brand_too_long(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Edit advertiser brand over max length gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000858"),
        external_id="73",
        username="u",
    )
    message = FakeMessage(text="A" * 201, user=FakeUser(73))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "brand",
        "edit_user_id": user.user_id,
        "edit_external_id": "73",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "Максимум" in text and "символ" in text.lower()
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_site_link(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert adv_service.update_calls[0][1].get("site_link") == "https://site.com"


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_invalid(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "цифр" in text or "корректный" in text.lower()
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_site_link_invalid(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "ссылк" in text.lower() or "http" in text.lower()
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_missing(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert "Профиль рекламодателя не найден" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_update_none(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert "Не удалось обновить" in message.answers[0]


@pytest.mark.asyncio
async def test_edit_profile_enter_value_barter_no(
    user_repo, config, bot_texts_service
) -> None:
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert reg_service.update_calls[0][1].get("barter") is False


@pytest.mark.asyncio
async def test_edit_profile_enter_value_work_format_ugc_only(
    user_repo, config, bot_texts_service
) -> None:
    """Enter work format UGC only updates profile."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000849"),
        external_id="57",
        username="u",
    )
    message = FakeMessage(
        text=_TEXTS_RU["btn_work_format_ugc_only"], user=FakeUser(57)
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert (
        reg_service.update_calls[0][1].get("work_format") == WorkFormat.UGC_ONLY
    )


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_unknown_field(
    user_repo,
    config,
    bot_texts_service,
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert state.cleared
    assert "Неизвестное поле" in message.answers[0]


@pytest.mark.asyncio
async def test_show_profile_blogger_with_gender_display(
    user_repo, config, bot_texts_service
) -> None:
    """Show profile displays blogger gender when set."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084c"),
        external_id="62",
        username="blogger",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(user=FakeUser(62))
    service = FakeProfileService(
        user=user,
        has_blogger=True,
        has_advertiser=False,
        blogger_gender=BloggerGender.MALE,
    )
    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )
    ans = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Пол: Мужской" in ans


@pytest.mark.asyncio
async def test_show_profile_from_user_id_falsy_returns_early(
    user_repo, config, bot_texts_service
) -> None:
    """show_profile returns early when from_user.id is empty (no answer)."""
    from tests.helpers.fakes import FakeMessengerClient
    from ugc_bot.application.messenger.context import MessageContext
    from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser

    incoming = IncomingMessage(
        chat_id="1",
        user=IncomingUser(
            external_id="",
            messenger_type=MessengerType.TELEGRAM,
            username=None,
        ),
        text=None,
    )
    client = FakeMessengerClient()
    message_ctx = MessageContext(incoming, client)
    service = _FakeProfileServiceUserMissing()
    await show_profile(
        message_ctx,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_edit_profile_choose_field_audience_gender(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing Пол аудитории shows audience gender keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084e"),
        external_id="63",
        username="u",
    )
    message = FakeMessage(text="Пол аудитории", user=FakeUser(63))
    state = FakeFSMContext()
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "63"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    await edit_profile_choose_field(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
    )
    assert state._data.get("editing_field") == "audience_gender"
    assert message.reply_markups
    kbd = message.reply_markups[0]
    rows = (
        getattr(kbd, "inline_keyboard", None)
        or getattr(kbd, "rows", None)
        or getattr(kbd, "keyboard", None)
    )
    assert any("женщины" in (b.text or "") for row in rows for b in row)


@pytest.mark.asyncio
async def test_edit_profile_choose_field_audience_age(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing Возраст аудитории shows age keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000084f"),
        external_id="64",
        username="u",
    )
    message = FakeMessage(text="Возраст аудитории", user=FakeUser(64))
    state = FakeFSMContext()
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "64"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    await edit_profile_choose_field(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
    )
    assert state._data.get("editing_field") == "audience_age"
    kbd = message.reply_markups[0]
    rows = (
        getattr(kbd, "inline_keyboard", None)
        or getattr(kbd, "rows", None)
        or getattr(kbd, "keyboard", [])
    )
    assert any("18" in (b.text or "") for row in rows for b in row)


@pytest.mark.asyncio
async def test_edit_profile_choose_field_barter(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing Бартер shows Да/Нет keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000850"),
        external_id="65",
        username="u",
    )
    message = FakeMessage(text="Бартер", user=FakeUser(65))
    state = FakeFSMContext()
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "65"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    await edit_profile_choose_field(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
    )
    assert state._data.get("editing_field") == "barter"
    assert message.reply_markups


@pytest.mark.asyncio
async def test_edit_profile_choose_field_work_format(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing Формат работы shows work format keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000851"),
        external_id="66",
        username="u",
    )
    message = FakeMessage(text="Формат работы", user=FakeUser(66))
    state = FakeFSMContext()
    state._data = {"edit_user_id": user.user_id, "edit_external_id": "66"}
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    await edit_profile_choose_field(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
    )
    assert state._data.get("editing_field") == "work_format"
    kbd = message.reply_markups[0]
    rows = (
        getattr(kbd, "inline_keyboard", None)
        or getattr(kbd, "rows", None)
        or getattr(kbd, "keyboard", [])
    )
    assert any(
        _TEXTS_RU["btn_work_format_ads"] in (b.text or "")
        for row in rows
        for b in row
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_field_advertiser_city(
    user_repo, config, bot_texts_service
) -> None:
    """Choosing Город for advertiser shows default prompt."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000852"),
        external_id="67",
        username="u",
    )
    message = FakeMessage(text="Город", user=FakeUser(67))
    state = FakeFSMContext()
    state._data = {
        "edit_user_id": user.user_id,
        "edit_external_id": "67",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    await edit_profile_choose_field(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
    )
    assert state._data.get("editing_field") == "city"
    assert message.answers
    assert (
        "новое значение" in message.answers[0][0].lower()
        or "город" in message.answers[0][0].lower()
    )


@pytest.mark.asyncio
async def test_edit_profile_choose_field_advertiser_company_activity(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Choosing Деятельность компании for advertiser shows prompt."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000853"),
        external_id="68",
        username="u",
    )
    message = FakeMessage(text="Деятельность компании", user=FakeUser(68))
    state = FakeFSMContext()
    state._data = {
        "edit_user_id": user.user_id,
        "edit_external_id": "68",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    await edit_profile_choose_field(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        user_role_service=FakeUserRoleService(),
    )
    assert state._data.get("editing_field") == "company_activity"
    assert message.answers


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_city_validation_error(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Edit advertiser city with invalid value gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000854"),
        external_id="69",
        username="u",
    )
    message = FakeMessage(text="X" * 201, user=FakeUser(69))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": user.user_id,
        "edit_external_id": "69",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_site_link_empty_clears(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Edit advertiser site_link with empty string clears link."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000855"),
        external_id="70",
        username="u",
    )
    message = FakeMessage(text="", user=FakeUser(70))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "site_link",
        "edit_user_id": user.user_id,
        "edit_external_id": "70",
        "edit_profile_type": "advertiser",
    }
    service = FakeProfileService(
        user=user, has_blogger=False, has_advertiser=True
    )
    adv_service = FakeAdvertiserRegistrationService(
        update_returns=AdvertiserProfile(
            user_id=user.user_id, phone="+7", brand="B", site_link=None
        )
    )
    await edit_profile_enter_value(
        message,
        state,
        service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert adv_service.update_calls
    assert adv_service.update_calls[0][1].get("site_link") is None


@pytest.mark.asyncio
async def test_handle_profile_edit_callback_no_user_returns_early(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit callback with no user returns without sending."""
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT,
        user=None,
        message=FakeMessage(user=None),
    )
    await handle_profile_edit_callback(
        callback,
        FakeFSMContext(),
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_handle_profile_my_profile_callback_no_user_returns_early(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """My profile callback with no user returns without sending."""
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MY_PROFILE,
        user=None,
        message=FakeMessage(user=None),
    )
    await handle_profile_my_profile_callback(
        callback,
        FakeFSMContext(),
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_handle_profile_my_profile_callback_user_not_found(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """My profile callback when user not in DB sends profile not found."""
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_MY_PROFILE,
        user=FakeUser(99999),
        message=FakeMessage(user=FakeUser(99999)),
    )
    await handle_profile_my_profile_callback(
        callback,
        FakeFSMContext(),
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Профиль не найден" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_unknown_field_returns(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback with unknown field_key returns without sending."""
    user = await create_test_user(user_repo, external_id="80", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="80",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}unknown_key",
        user=FakeUser(80),
        message=FakeMessage(user=FakeUser(80)),
    )
    initial_sent = len(client.sent_text)
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert len(client.sent_text) == initial_sent


@pytest.mark.asyncio
async def test_handle_profile_edit_choice_callback_advertiser_type_returns(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit choice with profile_type advertiser returns (blogger-only)."""
    user = await create_test_user(user_repo, external_id="81", username="u")
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="81",
        edit_profile_type="advertiser",
        editing_field="city",
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AUDIENCE_F,
        user=FakeUser(81),
        message=FakeMessage(user=FakeUser(81)),
    )
    initial_sent = len(client.sent_text)
    await handle_profile_edit_choice_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=BloggerRegistrationService(
            user_repo=user_repo, blogger_repo=blogger_repo
        ),
        user_role_service=UserRoleService(user_repo=user_repo),
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert len(client.sent_text) == initial_sent


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_phone_validation_error(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Edit advertiser phone with invalid value gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000856"),
        external_id="71",
        username="u",
    )
    message = FakeMessage(text="invalid", user=FakeUser(71))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "phone",
        "edit_user_id": user.user_id,
        "edit_external_id": "71",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_advertiser_company_activity_val_error(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Advertiser company_activity too long gets validation error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000857"),
        external_id="72",
        username="u",
    )
    message = FakeMessage(text="X" * 501, user=FakeUser(72))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "company_activity",
        "edit_user_id": user.user_id,
        "edit_external_id": "72",
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
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=FakeBloggerRegistrationService(),
        advertiser_registration_service=adv_service,
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    assert not adv_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_city_non_canonical(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Blogger city not in dictionary sends picker hint."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000859"),
        external_id="74",
        username="u",
    )
    message = FakeMessage(text="UnknownCity123", user=FakeUser(74))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "city",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "74",
        "edit_profile_type": "blogger",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "Выберите город из списка" in text or "Выбрать город" in text
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_audience_geo_more_than_three(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Blogger audience_geo with more than 3 cities sends error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000085a"),
        external_id="75",
        username="u",
    )
    message = FakeMessage(
        text="Москва, Казань, СПб, Сочи",
        user=FakeUser(75),
    )
    state = FakeFSMContext()
    state._data = {
        "editing_field": "audience_geo",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "75",
        "edit_profile_type": "blogger",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "не более 3" in text
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_edit_profile_enter_value_blogger_price_not_a_number(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Blogger price with non-numeric text sends error."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000085b"),
        external_id="76",
        username="u",
    )
    message = FakeMessage(text="abc", user=FakeUser(76))
    state = FakeFSMContext()
    state._data = {
        "editing_field": "price",
        "edit_user_id": str(user.user_id),
        "edit_external_id": "76",
        "edit_profile_type": "blogger",
    }
    profile_service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    reg_service = FakeBloggerRegistrationService()
    await edit_profile_enter_value(
        message,
        state,
        profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        advertiser_registration_service=FakeAdvertiserRegistrationService(),
        user_role_service=FakeUserRoleService(),
        max_order_price=10_000.0,
    )
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "число" in text.lower()
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_show_profile_blogger_confirmed_shows_inline_keyboard(
    user_repo,
    config,
    bot_texts_service,
) -> None:
    """Show profile with blogger and agreement confirmed shows keyboard."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000085c"),
        external_id="77",
        username="u",
        agreement_confirmed_at=datetime.now(timezone.utc),
    )
    message = FakeMessage(user=FakeUser(77))
    service = FakeProfileService(
        user=user, has_blogger=True, has_advertiser=False
    )
    await show_profile(
        message,
        service,
        FakeFSMContext(),
        config=config,
        bot_texts_service=bot_texts_service,
    )
    assert message.answers
    assert message.reply_markups


@pytest.mark.asyncio
async def test_handle_profile_agree_callback_get_user_returns_none(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """After confirm, get_user_by_id returns None -> send profile not found."""
    user = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-00000000085d"),
        external_id="78",
        username="u",
    )
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    role_service = FakeUserRoleService(get_user_by_id_returns=None)
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    adv_reg = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(_BLOGGER_AGREEMENTS_STATE)
    await state.update_data(user_id=user.user_id)
    callback = FakeCallback(
        data=CALLBACK_PROFILE_AGREE,
        user=FakeUser(78),
        message=FakeMessage(user=FakeUser(78)),
    )
    await handle_profile_agree_callback(
        callback,
        state,
        profile_service=profile_service,
        user_role_service=role_service,
        blogger_registration_service=blogger_reg,
        advertiser_registration_service=adv_reg,
        config=config,
        bot_texts_service=bot_texts_service,
        currency_symbol="₽",
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Профиль не найден" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_callback_advertiser_only_path(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit callback when user has only advertiser shows advertiser fields."""
    user = await create_test_user(
        user_repo, external_id="79", username="adv_only"
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT,
        user=FakeUser(79),
        message=FakeMessage(user=FakeUser(79)),
    )
    await handle_profile_edit_callback(
        callback,
        FakeFSMContext(),
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Выберите раздел" in s["text"] for s in client.sent_text)
    assert any("редактирования" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_empty_field_key_returns(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback with prefix-only data returns without sending."""
    user = await create_test_user(user_repo, external_id="80e", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="80e",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=CALLBACK_PROFILE_EDIT_FIELD_PREFIX,
        user=FakeUser(800),
        message=FakeMessage(user=FakeUser(800)),
    )
    initial_sent = len(client.sent_text)
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert len(client.sent_text) == initial_sent


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_audience_gender_keyboard(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for audience_gender sends gender keyboard."""
    user = await create_test_user(user_repo, external_id="81a", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="81a",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}audience_gender",
        user=FakeUser(81),
        message=FakeMessage(user=FakeUser(81)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "аудитори" in s["text"].lower() or "контент" in s["text"].lower()
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_blogger_gender_keyboard(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for blogger_gender sends gender keyboard."""
    user = await create_test_user(user_repo, external_id="82b", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="82b",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}blogger_gender",
        user=FakeUser(82),
        message=FakeMessage(user=FakeUser(82)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("пол" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_audience_age_keyboard(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for audience_age sends age keyboard."""
    user = await create_test_user(user_repo, external_id="83c", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="83c",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}audience_age",
        user=FakeUser(83),
        message=FakeMessage(user=FakeUser(83)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("возраст" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_barter_keyboard(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for barter sends barter keyboard."""
    user = await create_test_user(user_repo, external_id="84d", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="84d",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}barter",
        user=FakeUser(84),
        message=FakeMessage(user=FakeUser(84)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("бартер" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_work_format_keyboard(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for work_format sends format keyboard."""
    user = await create_test_user(user_repo, external_id="85e", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="85e",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}work_format",
        user=FakeUser(85),
        message=FakeMessage(user=FakeUser(85)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "бренд" in s["text"].lower() or "работа" in s["text"].lower()
        for s in client.sent_text
    )


@pytest.mark.asyncio
async def test_handle_profile_edit_field_callback_city_blogger_sends_picker(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Edit field callback for city (blogger) sends city picker keyboard."""
    user = await create_test_user(user_repo, external_id="86f", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    config = _profile_test_config()
    blogger_reg = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user_role_service = UserRoleService(user_repo=user_repo)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.update_data(
        edit_user_id=user.user_id,
        edit_external_id="86f",
        edit_profile_type="blogger",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_EDIT_FIELD_PREFIX}city",
        user=FakeUser(86),
        message=FakeMessage(user=FakeUser(86)),
    )
    await handle_profile_edit_field_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=blogger_reg,
        user_role_service=user_role_service,
        max_order_price=10_000.0,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("город" in s["text"].lower() for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_city_web_app_data_profile_success(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """City from Mini App updates blogger profile and shows profile."""
    user = await create_test_user(user_repo, external_id="87", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        editing_field="city",
        edit_user_id=user.user_id,
        edit_external_id="87",
    )
    message = FakeMessage(
        user=FakeUser(87),
        web_app_data=FakeWebAppData("москва"),
    )
    await handle_city_web_app_data_profile(
        message,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=FakeUserRoleService(),
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Профиль обновлён" in s["text"] for s in client.sent_text)
    assert reg_service.update_calls
    assert reg_service.update_calls[0][1].get("city") == "москва"


@pytest.mark.asyncio
async def test_handle_city_web_app_data_profile_editing_field_not_city_returns(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When editing_field is not city, handler returns without sending."""
    user = await create_test_user(user_repo, external_id="88", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    reg_service = FakeBloggerRegistrationService()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        editing_field="nickname",
        edit_user_id=user.user_id,
        edit_external_id="88",
    )
    message = FakeMessage(
        user=FakeUser(88),
        web_app_data=FakeWebAppData("москва"),
    )
    await handle_city_web_app_data_profile(
        message,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=FakeUserRoleService(),
        messenger_client=client,
        event_adapter=adapter,
    )
    assert len(client.sent_text) == 0
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_handle_city_web_app_data_profile_invalid_city(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Invalid city from Mini App sends choose from list message."""
    user = await create_test_user(user_repo, external_id="89", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    reg_service = FakeBloggerRegistrationService()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        editing_field="city",
        edit_user_id=user.user_id,
        edit_external_id="89",
    )
    message = FakeMessage(
        user=FakeUser(89),
        web_app_data=FakeWebAppData("invalid-city-xyz"),
    )
    await handle_city_web_app_data_profile(
        message,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=FakeUserRoleService(),
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "Выберите город из списка" in s["text"] for s in client.sent_text
    )
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_handle_city_web_app_data_profile_wrong_region_rejects(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Valid city but wrong region from Mini App sends choose from list."""
    user = await create_test_user(user_repo, external_id="89b", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    reg_service = FakeBloggerRegistrationService()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        editing_field="city",
        edit_user_id=user.user_id,
        edit_external_id="89b",
    )
    message = FakeMessage(
        user=FakeUser(89),
        web_app_data=FakeWebAppData("республика татарстан:москва"),
    )
    await handle_city_web_app_data_profile(
        message,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=FakeUserRoleService(),
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any(
        "Выберите город из списка" in s["text"] for s in client.sent_text
    )
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_handle_city_web_app_data_profile_user_id_missing(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """When edit_user_id missing in state, send session expired."""
    user = await create_test_user(user_repo, external_id="90", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    reg_service = FakeBloggerRegistrationService()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        editing_field="city",
        edit_external_id="90",
    )
    message = FakeMessage(
        user=FakeUser(90),
        web_app_data=FakeWebAppData("москва"),
    )
    await handle_city_web_app_data_profile(
        message,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        user_role_service=FakeUserRoleService(),
        messenger_client=client,
        event_adapter=adapter,
    )
    assert any("Сессия истекла" in s["text"] for s in client.sent_text)
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_handle_profile_region_callback_success(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Profile region callback with valid region updates profile."""
    user = await create_test_user(user_repo, external_id="91", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    updated = _make_blogger_profile(user.user_id)
    reg_service = FakeBloggerRegistrationService(update_returns=updated)
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        pending_city_edit="железногорск",
        edit_user_id=str(user.user_id),
        edit_external_id="91",
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_REGION_PREFIX}красноярский край",
        user=FakeUser(91, "u", "U"),
        message=FakeMessage(user=FakeUser(91)),
    )
    await handle_profile_region_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert state.cleared is True
    assert len(reg_service.update_calls) == 1
    assert reg_service.update_calls[0][1].get("city") == "железногорск"
    assert reg_service.update_calls[0][1].get("region") == "красноярский край"
    assert any("Профиль обновлён" in s["text"] for s in client.sent_text)


@pytest.mark.asyncio
async def test_handle_profile_region_callback_invalid_region_no_update(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Profile region callback with region not for city does not update."""
    user = await create_test_user(user_repo, external_id="92", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    reg_service = FakeBloggerRegistrationService()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(
        pending_city_edit="железногорск",
        edit_user_id=str(user.user_id),
    )
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_REGION_PREFIX}несуществующий регион",
        user=FakeUser(92),
        message=FakeMessage(user=FakeUser(92)),
    )
    await handle_profile_region_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert not reg_service.update_calls


@pytest.mark.asyncio
async def test_handle_profile_region_callback_missing_state_answers_only(
    user_repo, blogger_repo, advertiser_repo, config, bot_texts_service
) -> None:
    """Profile region callback with no pending_city_edit does not update."""
    user = await create_test_user(user_repo, external_id="93", username="u")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    profile_service = build_profile_service(
        user_repo, blogger_repo=blogger_repo, advertiser_repo=advertiser_repo
    )
    reg_service = FakeBloggerRegistrationService()
    client = FakeMessengerClient()
    adapter = TelegramEventAdapter()
    state = FakeFSMContext()
    await state.set_state(EditProfileStates.entering_value.state)
    await state.update_data(edit_user_id=str(user.user_id))
    callback = FakeCallback(
        data=f"{CALLBACK_PROFILE_REGION_PREFIX}красноярский край",
        user=FakeUser(93),
        message=FakeMessage(user=FakeUser(93)),
    )
    await handle_profile_region_callback(
        callback,
        state,
        profile_service=profile_service,
        config=config,
        bot_texts_service=bot_texts_service,
        blogger_registration_service=reg_service,
        messenger_client=client,
        event_adapter=adapter,
    )
    assert not reg_service.update_calls
