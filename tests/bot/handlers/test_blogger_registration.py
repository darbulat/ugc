"""Tests for blogger registration handlers."""

from uuid import UUID

import pytest

from tests.helpers.factories import (
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeMessage,
    FakeUser,
)
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.blogger_registration import (
    BloggerRegistrationStates,
    _start_registration_flow,
    choose_creator_role,
    handle_age,
    handle_agreements,
    handle_barter,
    handle_blogger_gender,
    handle_city,
    handle_gender,
    handle_geo,
    handle_instagram,
    handle_name,
    handle_price,
    handle_topics,
    handle_work_format,
    start_registration_button,
)
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    CONFIRM_INSTAGRAM_BUTTON_TEXT,
    CREATE_PROFILE_BUTTON_TEXT,
    MY_PROFILE_BUTTON_TEXT,
    WORK_FORMAT_ADS_BUTTON_TEXT,
    WORK_FORMAT_UGC_ONLY_BUTTON_TEXT,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)


@pytest.mark.asyncio
async def test_start_registration_requires_user(user_repo) -> None:
    """Require existing user before registration."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service)

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

    await _start_registration_flow(message, state, service)

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

    await _start_registration_flow(message, state, service)

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

    await _start_registration_flow(message, state, service)

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
async def test_instagram_url_normalized_with_query_and_www(
    user_repo, blogger_repo
) -> None:
    """URL with query and www is accepted and stored normalized."""
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text="https://www.instagram.com/norm_user?igsh=bjh1MHRkczhxcTho&utm_source=qr",
        user=FakeUser(1, "user", "User"),
    )
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert state._data["instagram_url"] == "https://instagram.com/norm_user"


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

    await handle_price(message, state, max_order_price=10_000.0)

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
    ans = name_message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()

    topics_message = FakeMessage(text=" ", user=None)
    await handle_topics(topics_message, state)
    ans_t = topics_message.answers[0]
    assert "тематику" in (ans_t if isinstance(ans_t, str) else ans_t[0])


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
    await handle_price(price_message, state, max_order_price=10_000.0)
    assert state._data["price"] == 1500.0


@pytest.mark.asyncio
async def test_geo_empty_and_price_negative() -> None:
    """Handle invalid geo and price inputs."""

    state = FakeFSMContext()
    geo_message = FakeMessage(text=" ", user=None)
    await handle_geo(geo_message, state)
    ans_g = geo_message.answers[0]
    assert "город" in (ans_g if isinstance(ans_g, str) else ans_g[0])

    price_message = FakeMessage(text="-5", user=None)
    await handle_price(price_message, state, max_order_price=10_000.0)
    ans_p = price_message.answers[0]
    assert "Цена должна" in (ans_p if isinstance(ans_p, str) else ans_p[0])


@pytest.mark.asyncio
async def test_handle_agreements_creates_profile(
    user_repo, blogger_repo
) -> None:
    """Agreement step confirms consent; profile is saved in work_format step."""

    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    user = await user_role_service.set_user(
        external_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
    )

    await registration_service.save_blogger_before_agreement(
        user_id=user.user_id,
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
        blogger_gender=BloggerGender.MALE,
        display_name="bob",
        telegram_username="bob",
    )

    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(42, "bob", "Bob")
    )
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_agreements(message, state, registration_service)

    assert message.answers
    ans = message.answers[0]
    assert "Профиль создан" in (ans if isinstance(ans, str) else ans[0])
    assert await blogger_repo.get_by_user_id(user.user_id) is not None


@pytest.mark.asyncio
async def test_handle_agreements_requires_consent(
    user_repo, blogger_repo
) -> None:
    """Require explicit consent."""

    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )

    message = FakeMessage(text="нет", user=FakeUser(1, "bob", "Bob"))
    state = FakeFSMContext()

    await handle_agreements(message, state, registration_service)

    assert message.answers
    first_answer = message.answers[0]
    text = first_answer[0] if isinstance(first_answer, tuple) else first_answer
    assert "Регистрация прервана" in text or "Мой профиль" in text


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
        blogger_gender=BloggerGender.MALE,
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

    await registration_service.save_blogger_before_agreement(
        user_id=user.user_id,
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
        blogger_gender=BloggerGender.MALE,
        display_name="alice",
        telegram_username="alice",
    )

    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(43, "alice", "Alice")
    )
    state = FakeFSMContext()
    await state.update_data(user_id=user.user_id)

    await handle_agreements(message, state, registration_service)

    assert message.reply_markups
    keyboard = message.reply_markups[0]
    rows = keyboard.rows if hasattr(keyboard, "rows") else keyboard.keyboard
    assert rows is not None
    # After registration: Confirm Instagram + My profile
    assert len(rows) == 2
    assert rows[0][0].text == CONFIRM_INSTAGRAM_BUTTON_TEXT
    assert rows[1][0].text == MY_PROFILE_BUTTON_TEXT


@pytest.mark.asyncio
async def test_start_registration_no_username_asks_name(user_repo) -> None:
    """When user has no username, ask for name first."""
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "", "User"))
    state = FakeFSMContext()

    await _start_registration_flow(message, state, service)

    ans = message.answers[0]
    assert "ваше имя" in (ans if isinstance(ans, str) else ans[0]).lower()
    assert state.state == BloggerRegistrationStates.name


@pytest.mark.asyncio
async def test_handle_city_empty_rejects(user_repo) -> None:
    """handle_city rejects empty city."""
    message = FakeMessage(text="   ", user=FakeUser(1, "u", "U"))
    state = FakeFSMContext()

    await handle_city(message, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "город" in text.lower()


@pytest.mark.asyncio
async def test_handle_city_valid_stores_and_asks_blogger_gender() -> None:
    """handle_city stores city and asks for blogger gender."""
    state = FakeFSMContext()
    message = FakeMessage(text="Москва", user=FakeUser(1, "u", "U"))

    await handle_city(message, state)

    assert state._data["city"] == "Москва"
    assert state.state == BloggerRegistrationStates.blogger_gender
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "пол" in text.lower()


@pytest.mark.asyncio
async def test_handle_blogger_gender_valid_stores_and_asks_topics() -> None:
    """handle_blogger_gender stores gender and asks for topics."""
    state = FakeFSMContext()
    message = FakeMessage(text="Мужской", user=FakeUser(1, "u", "U"))

    await handle_blogger_gender(message, state)

    assert state._data["blogger_gender"] == BloggerGender.MALE
    assert state.state == BloggerRegistrationStates.topics
    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "контент" in text.lower() or "тематик" in text.lower()


@pytest.mark.asyncio
async def test_handle_blogger_gender_female_stores() -> None:
    """handle_blogger_gender stores FEMALE."""
    state = FakeFSMContext()
    message = FakeMessage(text="Женский", user=FakeUser(1, "u", "U"))

    await handle_blogger_gender(message, state)

    assert state._data["blogger_gender"] == BloggerGender.FEMALE


@pytest.mark.asyncio
async def test_handle_blogger_gender_invalid_rejects() -> None:
    """handle_blogger_gender rejects invalid input."""
    state = FakeFSMContext()
    message = FakeMessage(text="Другое", user=FakeUser(1, "u", "U"))

    await handle_blogger_gender(message, state)

    assert "blogger_gender" not in state._data
    assert message.answers
    assert "Выберите" in message.answers[0] or "кнопок" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_topics_only_commas_rejects(user_repo) -> None:
    """handle_topics rejects input that yields no topics (e.g. ',,')."""
    message = FakeMessage(text=", , ,", user=FakeUser(1, "u", "U"))
    state = FakeFSMContext()

    await handle_topics(message, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "тематику" in text.lower()


@pytest.mark.asyncio
async def test_handle_geo_too_many_cities_rejects(user_repo) -> None:
    """handle_geo rejects more than 3 cities."""
    message = FakeMessage(
        text="Moscow, Kazan, SPb, Novosibirsk",
        user=FakeUser(1, "u", "U"),
    )
    state = FakeFSMContext()

    await handle_geo(message, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "не более 3" in text


@pytest.mark.asyncio
async def test_handle_barter_invalid_rejects(user_repo) -> None:
    """handle_barter rejects non-Da/Net input."""
    message = FakeMessage(text="maybe", user=FakeUser(1, "u", "U"))
    state = FakeFSMContext()

    await handle_barter(message, state)

    assert message.answers
    assert "Да или Нет" in message.answers[0]


def _blogger_test_config() -> AppConfig:
    """Test config for blogger handlers."""
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
            "DOCS_OFFER_URL": "https://example.com/offer",
            "DOCS_PRIVACY_URL": "",
            "DOCS_CONSENT_URL": "",
        }
    )


@pytest.mark.asyncio
async def test_handle_work_format_valid_ads(user_repo, blogger_repo) -> None:
    """handle_work_format accepts ADS_IN_ACCOUNT and saves profile."""
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000099"),
        external_id="1",
        username="u",
    )
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text=WORK_FORMAT_ADS_BUTTON_TEXT, user=FakeUser(1, "u", "U")
    )
    state = FakeFSMContext()
    state.state = BloggerRegistrationStates.work_format
    await state.update_data(
        user_id=UUID("00000000-0000-0000-0000-000000000099"),
        nickname="x",
        instagram_url="https://instagram.com/x",
        city="M",
        topics={"selected": ["a"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="M",
        price=1000.0,
        barter=False,
        blogger_gender=BloggerGender.MALE,
    )
    config = _blogger_test_config()

    await handle_work_format(message, state, config, registration_service)

    assert state._data["work_format"] == WorkFormat.ADS_IN_ACCOUNT
    assert state.state == BloggerRegistrationStates.agreements
    assert "Оферта" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_handle_work_format_invalid_rejects(
    user_repo, blogger_repo
) -> None:
    """handle_work_format rejects invalid choice."""
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="Other", user=FakeUser(1, "u", "U"))
    state = FakeFSMContext()
    config = _blogger_test_config()

    await handle_work_format(message, state, config, registration_service)

    assert message.answers
    assert "Выберите одну из кнопок" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_agreements_session_expired(
    user_repo, blogger_repo
) -> None:
    """handle_agreements clears when user_id missing from state."""
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(1, "bob", "Bob")
    )
    state = FakeFSMContext()
    state.state = BloggerRegistrationStates.agreements
    await state.update_data(nickname="x", external_id="1")  # no user_id

    await handle_agreements(message, state, registration_service)

    assert "Сессия истекла" in message.answers[0]


@pytest.mark.asyncio
async def test_choose_creator_role_no_from_user(
    user_repo, blogger_repo
) -> None:
    """choose_creator_role returns early when message.from_user is None."""
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    message = FakeMessage(text="Я креатор", user=None)
    message.from_user = None
    state = FakeFSMContext()

    await choose_creator_role(message, user_service, profile_service, state)

    assert not message.answers


@pytest.mark.asyncio
async def test_choose_creator_role_with_profile(
    user_repo, blogger_repo
) -> None:
    """choose_creator_role shows action menu when blogger profile exists."""
    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(user_repo, blogger_repo)
    user = await user_service.set_user(
        external_id="50",
        messenger_type=MessengerType.TELEGRAM,
        username="creator",
    )
    await create_test_blogger_profile(
        blogger_repo, user.user_id, confirmed=True
    )
    message = FakeMessage(
        text="Я креатор", user=FakeUser(50, "creator", "Creator")
    )
    state = FakeFSMContext()

    await choose_creator_role(message, user_service, profile_service, state)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "Выберите действие" in text


@pytest.mark.asyncio
async def test_start_registration_button(user_repo) -> None:
    """start_registration_button delegates to _start_registration_flow."""
    user_service = UserRoleService(user_repo=user_repo)
    await user_service.set_user(
        external_id="51",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
    )
    message = FakeMessage(
        text=CREATE_PROFILE_BUTTON_TEXT, user=FakeUser(51, "alice", "Alice")
    )
    state = FakeFSMContext()

    await start_registration_button(message, state, user_service)

    assert message.answers
    ans = message.answers[0]
    text = (ans[0] if isinstance(ans, tuple) else ans).lower()
    assert "инстаграмм" in text or "имя" in text


@pytest.mark.asyncio
async def test_handle_instagram_empty_url(user_repo, blogger_repo) -> None:
    """handle_instagram rejects empty URL."""
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(text="   ", user=FakeUser(1, "u", "U"))
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert message.answers
    assert "пустой" in message.answers[0].lower()


@pytest.mark.asyncio
async def test_handle_instagram_no_instagram_domain(
    user_repo, blogger_repo
) -> None:
    """handle_instagram rejects URL without instagram.com/."""
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text="https://facebook.com/user", user=FakeUser(1, "u", "U")
    )
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert message.answers
    assert "Неверный формат" in message.answers[0]


@pytest.mark.asyncio
async def test_handle_instagram_invalid_regex(user_repo, blogger_repo) -> None:
    """handle_instagram rejects URL with instagram.com but invalid format."""
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    message = FakeMessage(
        text="https://instagram.com/user/path/extra",
        user=FakeUser(1, "u", "U"),
    )
    state = FakeFSMContext()

    await handle_instagram(message, state, registration_service)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "Неверный формат" in text or "Пример" in text


@pytest.mark.asyncio
async def test_handle_gender_female_and_male() -> None:
    """handle_gender accepts В основном женщины and В основном мужчины."""
    state = FakeFSMContext()

    msg_female = FakeMessage(text="👩 В основном женщины", user=None)
    await handle_gender(msg_female, state)
    assert state._data["audience_gender"] == AudienceGender.FEMALE

    state2 = FakeFSMContext()
    msg_male = FakeMessage(text="👨 В основном мужчины", user=None)
    await handle_gender(msg_male, state2)
    assert state2._data["audience_gender"] == AudienceGender.MALE


@pytest.mark.asyncio
async def test_handle_work_format_with_all_docs(
    user_repo, blogger_repo
) -> None:
    """handle_work_format shows all doc links when config has them."""
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000099"),
        external_id="1",
        username="u",
    )
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    config = AppConfig.model_validate(
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
            "DOCS_OFFER_URL": "https://example.com/offer",
            "DOCS_PRIVACY_URL": "https://example.com/privacy",
            "DOCS_CONSENT_URL": "https://example.com/consent",
        }
    )
    message = FakeMessage(
        text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT, user=FakeUser(1, "u", "U")
    )
    state = FakeFSMContext()
    await state.update_data(
        user_id=UUID("00000000-0000-0000-0000-000000000099"),
        nickname="x",
        instagram_url="https://instagram.com/x",
        city="M",
        topics={"selected": ["a"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="M",
        price=1000.0,
        barter=False,
        blogger_gender=BloggerGender.MALE,
    )

    await handle_work_format(message, state, config, registration_service)

    text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Политика конфиденциальности" in text
    assert "Согласие на обработку" in text


@pytest.mark.asyncio
async def test_handle_work_format_no_docs(user_repo, blogger_repo) -> None:
    """handle_work_format shows fallback when no doc URLs configured."""
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000099"),
        external_id="1",
        username="u",
    )
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    config = AppConfig.model_validate(
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
    message = FakeMessage(
        text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT, user=FakeUser(1, "u", "U")
    )
    state = FakeFSMContext()
    await state.update_data(
        user_id=UUID("00000000-0000-0000-0000-000000000099"),
        nickname="x",
        instagram_url="https://instagram.com/x",
        city="M",
        topics={"selected": ["a"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="M",
        price=1000.0,
        barter=False,
        blogger_gender=BloggerGender.MALE,
    )

    await handle_work_format(message, state, config, registration_service)

    text = (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert "Подтвердите согласие с документами платформы" in text


@pytest.mark.asyncio
async def test_handle_agreements_from_user_none(
    user_repo, blogger_repo
) -> None:
    """handle_agreements works when message.from_user is None."""
    user_role_service = UserRoleService(user_repo=user_repo)
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    user = await user_role_service.set_user(
        external_id="52",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
    )
    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(52, "bob", "Bob")
    )
    message.from_user = None
    state = FakeFSMContext()
    await state.update_data(
        user_id=user.user_id,
        external_id="52",
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
        blogger_gender=BloggerGender.MALE,
    )

    await handle_agreements(message, state, registration_service)

    assert message.answers
    ans = message.answers[0]
    assert "Профиль создан" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_agreements_unique_violation(
    user_repo, blogger_repo
) -> None:
    """handle_work_format handles duplicate instagram_url gracefully."""
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000053"),
        external_id="53",
        username="bob",
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000100"),
        external_id="100",
        username="other",
    )
    await create_test_blogger_profile(
        blogger_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000100"),
        instagram_url="https://instagram.com/duplicate",
    )
    registration_service = BloggerRegistrationService(
        user_repo=user_repo, blogger_repo=blogger_repo
    )
    config = _blogger_test_config()
    message = FakeMessage(
        text=WORK_FORMAT_UGC_ONLY_BUTTON_TEXT, user=FakeUser(53, "bob", "Bob")
    )
    state = FakeFSMContext()
    state.state = BloggerRegistrationStates.work_format
    await state.update_data(
        user_id=UUID("00000000-0000-0000-0000-000000000053"),
        nickname="bob",
        instagram_url="https://instagram.com/duplicate",
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1500.0,
        barter=False,
        blogger_gender=BloggerGender.MALE,
    )

    await handle_work_format(message, state, config, registration_service)

    assert message.answers
    ans = message.answers[0]
    text = ans[0] if isinstance(ans, tuple) else ans
    assert "уже зарегистрирован" in text
