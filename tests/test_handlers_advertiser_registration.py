"""Tests for advertiser registration handlers."""

from uuid import UUID

import pytest

from tests.helpers.factories import create_test_user
from tests.helpers.fakes import (
    FakeFSMContext,
    FakeFsmDraftService,
    FakeMessage,
    FakeUser,
    RecordingFsmDraftService,
)
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.advertiser_registration import (
    AdvertiserRegistrationStates,
    advertiser_draft_choice,
    handle_advertiser_start,
    handle_agreements_confirm,
    handle_brand,
    handle_city,
    handle_company_activity,
    handle_name,
    handle_phone,
    handle_site_link,
)
from ugc_bot.bot.handlers.keyboards import (
    CONFIRM_AGREEMENT_BUTTON_TEXT,
    DRAFT_QUESTION_TEXT,
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import AdvertiserProfile
from ugc_bot.domain.enums import MessengerType, UserStatus


@pytest.mark.asyncio
async def test_start_advertiser_registration_requires_user(
    user_repo, advertiser_repo
) -> None:
    """Require existing user before registration."""

    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(1, "user", "User"))
    state = FakeFSMContext()
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert message.answers
    ans = message.answers[0]
    assert "Пользователь не найден" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_sets_state(
    user_repo, advertiser_repo
) -> None:
    """Start registration for advertiser role."""

    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert state._data["user_id"] is not None
    assert state.state is not None
    assert message.answers
    first_ans = message.answers[0]
    assert "Как вас зовут" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_start_advertiser_registration_skips_name_when_username_set(
    user_repo, advertiser_repo
) -> None:
    """When user has username, skip name step and ask for phone."""

    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text=None, user=FakeUser(10, "adv", "Adv"))
    state = FakeFSMContext()
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert state._data["user_id"] is not None
    assert state._data["name"] == "adv"
    assert state.state is not None
    assert message.answers
    first_ans = message.answers[0]
    assert "телефона" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_start_advertiser_registration_blocked_user(
    user_repo, advertiser_repo
) -> None:
    """Reject registration for blocked advertiser."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000720"),
        external_id="11",
        username="blocked",
        status=UserStatus.BLOCKED,
    )
    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(11, "blocked", "Blocked"))
    state = FakeFSMContext()

    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert message.answers
    ans = message.answers[0]
    assert "Заблокированные" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_start_advertiser_registration_paused_user(
    user_repo, advertiser_repo
) -> None:
    """Reject registration for paused advertiser."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000721"),
        external_id="12",
        username="paused",
        status=UserStatus.PAUSE,
    )
    service = UserRoleService(user_repo=user_repo)
    message = FakeMessage(text=None, user=FakeUser(12, "paused", "Paused"))
    state = FakeFSMContext()

    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )

    await handle_advertiser_start(
        message,
        state,
        service,
        profile_service=profile_service,
        fsm_draft_service=FakeFsmDraftService(),
    )

    assert message.answers
    ans = message.answers[0]
    assert "паузе" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_name_requires_value(user_repo, advertiser_repo) -> None:
    """Require non-empty name with min 2 chars."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(message, state)
    assert message.answers
    ans = message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()


@pytest.mark.asyncio
async def test_handle_brand_success(user_repo) -> None:
    """Store brand and ask for company activity."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )

    message = FakeMessage(text="My Brand", user=FakeUser(20, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:brand"
    await state.update_data(
        user_id=user.user_id,
        name="Test Name",
        phone="+79001234567",
        city="Казань",
    )

    await handle_brand(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "занимается" in (ans if isinstance(ans, str) else ans[0])
    assert state._data.get("brand") == "My Brand"


@pytest.mark.asyncio
async def test_handle_advertiser_start_user_not_found(
    user_repo, advertiser_repo
) -> None:
    """When user not in repo, 'Начать' asks to start with /start."""

    user_service = UserRoleService(user_repo=user_repo)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text="Начать", user=FakeUser(999, "x", "X"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message, state, user_service, profile_service, FakeFsmDraftService()
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "Пользователь не найден" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_handle_advertiser_start_shows_menu_when_profile_exists(
    user_repo, advertiser_repo
) -> None:
    """When advertiser has profile, 'Начать' shows menu."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    await advertiser_repo.save(
        AdvertiserProfile(
            user_id=user.user_id,
            phone="+79001234567",
            brand="B",
        )
    )
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text="Начать", user=FakeUser(30, "adv", "Adv"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message, state, user_service, profile_service, FakeFsmDraftService()
    )

    assert message.answers
    first_ans = message.answers[0]
    assert "Выберите действие" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )


@pytest.mark.asyncio
async def test_handle_name_success_asks_phone(user_repo) -> None:
    """Valid name leads to phone prompt."""

    message = FakeMessage(text="Иван", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(message, state)

    assert message.answers
    first_ans = message.answers[0]
    assert "телефона" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )
    assert state._data.get("name") == "Иван"


@pytest.mark.asyncio
async def test_handle_phone_success_asks_city(user_repo) -> None:
    """Valid phone leads to city prompt."""

    message = FakeMessage(text="89001110777", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"
    await state.update_data(name="Test")

    await handle_phone(message, state)

    assert message.answers
    first_ans = message.answers[0]
    assert "города" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )
    assert state._data.get("phone") == "89001110777"


@pytest.mark.asyncio
async def test_handle_phone_requires_value(user_repo) -> None:
    """Require non-empty phone."""

    message = FakeMessage(text=" ", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:phone"

    await handle_phone(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "Номер телефона не может быть пустым" in (
        ans if isinstance(ans, str) else ans[0]
    )


@pytest.mark.asyncio
async def test_handle_city_success_asks_brand(user_repo) -> None:
    """Valid city leads to brand prompt."""

    message = FakeMessage(text="Казань", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:city"
    await state.update_data(name="Test", phone="+79001234567")

    await handle_city(message, state)

    assert message.answers
    first_ans = message.answers[0]
    assert "бренда" in (
        first_ans if isinstance(first_ans, str) else first_ans[0]
    )
    assert state._data.get("city") == "Казань"


@pytest.mark.asyncio
async def test_handle_company_activity_success_asks_site_link(
    user_repo,
) -> None:
    """Valid company activity leads to site link prompt."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(
        text="Продажа одежды", user=FakeUser(20, "adv", "Adv")
    )
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:company_activity"
    await state.update_data(
        user_id=user.user_id,
        name="Test Name",
        phone="+79001234567",
        city="Казань",
        brand="My Brand",
    )

    await handle_company_activity(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "Ссылка на сайт" in (ans if isinstance(ans, str) else ans[0])
    assert state._data.get("company_activity") == "Продажа одежды"


@pytest.mark.asyncio
async def test_handle_brand_requires_value(user_repo) -> None:
    """Require non-empty brand."""

    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="40",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text=" ", user=FakeUser(40, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:brand"
    await state.update_data(
        user_id=user.user_id, name="N", phone="+79001234567"
    )

    await handle_brand(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()


@pytest.mark.asyncio
async def test_handle_advertiser_start_with_draft_shows_draft_question(
    user_repo, advertiser_repo
) -> None:
    """When draft exists, show DRAFT_QUESTION_TEXT and set choosing_draft."""
    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="50",
        messenger_type=MessengerType.TELEGRAM,
        username="",
    )
    draft = {"user_id": user.user_id, "name": "Draft"}
    draft_service = RecordingFsmDraftService(draft_to_return=draft)
    profile_service = build_profile_service(
        user_repo, advertiser_repo=advertiser_repo
    )
    message = FakeMessage(text="Начать", user=FakeUser(50, "", "User"))
    state = FakeFSMContext()

    await handle_advertiser_start(
        message, state, service, profile_service, draft_service
    )

    assert DRAFT_QUESTION_TEXT in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert state.state == AdvertiserRegistrationStates.choosing_draft_restore


@pytest.mark.asyncio
async def test_advertiser_draft_choice_resume_restores(user_repo) -> None:
    """RESUME_DRAFT restores draft and shows first prompt."""
    from datetime import datetime, timezone

    from ugc_bot.domain.entities import FsmDraft

    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="51",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    draft = FsmDraft(
        user_id=user.user_id,
        flow_type="advertiser_registration",
        state_key="AdvertiserRegistrationStates:name",
        data={"user_id": user.user_id, "name": "Test"},
        updated_at=datetime.now(timezone.utc),
    )
    draft_service = RecordingFsmDraftService(draft_to_return=draft)
    message = FakeMessage(
        text=RESUME_DRAFT_BUTTON_TEXT, user=FakeUser(51, "adv", "Adv")
    )
    state = FakeFSMContext()
    state._data = {"user_id": user.user_id}
    state.state = AdvertiserRegistrationStates.choosing_draft_restore

    await advertiser_draft_choice(message, state, draft_service)

    assert state.state == AdvertiserRegistrationStates.name
    assert "Как вас зовут" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_advertiser_draft_choice_start_over(user_repo) -> None:
    """START_OVER deletes draft and shows first step."""
    service = UserRoleService(user_repo=user_repo)
    user = await service.set_user(
        external_id="52",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    draft_service = RecordingFsmDraftService(draft_to_return=None)
    message = FakeMessage(
        text=START_OVER_BUTTON_TEXT, user=FakeUser(52, "adv", "Adv")
    )
    state = FakeFSMContext()
    state._data = {"user_id": user.user_id}
    state.state = AdvertiserRegistrationStates.choosing_draft_restore

    await advertiser_draft_choice(message, state, draft_service)

    assert state.state == AdvertiserRegistrationStates.name
    assert len(draft_service.delete_calls) == 1


@pytest.mark.asyncio
async def test_handle_name_empty_string(user_repo) -> None:
    """Reject empty name (empty string after strip)."""
    message = FakeMessage(text="", user=FakeUser(1, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:name"

    await handle_name(message, state)

    assert message.answers
    ans = message.answers[0]
    assert "символ" in (ans if isinstance(ans, str) else ans[0]).lower()


def _test_config() -> AppConfig:
    """Create test config with doc URLs."""
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
            "DOCS_PRIVACY_URL": "https://example.com/privacy",
            "DOCS_CONSENT_URL": "https://example.com/consent",
        }
    )


def _test_config_no_docs() -> AppConfig:
    """Config with no doc URLs (triggers len(parts)==2 branch)."""
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


@pytest.mark.asyncio
async def test_handle_site_link_no_docs_shows_fallback(user_repo) -> None:
    """handle_site_link with no doc URLs shows fallback text."""
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="56",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(text="https://x.com", user=FakeUser(56, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:site_link"
    await state.update_data(
        user_id=user.user_id,
        name="Test",
        phone="+79001234567",
        city="City",
        brand="Brand",
        company_activity="Activity",
    )
    config = _test_config_no_docs()

    await handle_site_link(message, state, config)

    assert "Подтвердите согласие с документами" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_handle_site_link_shows_agreements(user_repo) -> None:
    """handle_site_link shows agreements message with doc links."""
    user_service = UserRoleService(user_repo=user_repo)
    user = await user_service.set_user(
        external_id="53",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
    )
    message = FakeMessage(
        text="https://mysite.com", user=FakeUser(53, "adv", "Adv")
    )
    state = FakeFSMContext()
    state.state = "AdvertiserRegistrationStates:site_link"
    await state.update_data(
        user_id=user.user_id,
        name="Test",
        phone="+79001234567",
        city="City",
        brand="Brand",
        company_activity="Activity",
    )
    config = _test_config()

    await handle_site_link(message, state, config)

    assert "Оферта" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )
    assert state.state == AdvertiserRegistrationStates.agreements
    assert state._data.get("site_link") == "https://mysite.com"


@pytest.mark.asyncio
async def test_handle_agreements_confirm_session_expired(
    user_repo, advertiser_repo
) -> None:
    """handle_agreements_confirm clears state when user_id missing."""
    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(57, "adv", "Adv")
    )
    state = FakeFSMContext()
    state.state = AdvertiserRegistrationStates.agreements
    await state.update_data(name="X", phone="+7")  # no user_id
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    user_service = UserRoleService(user_repo=user_repo)

    await handle_agreements_confirm(message, state, adv_service, user_service)

    assert state.cleared
    assert "Сессия истекла" in (
        message.answers[0]
        if isinstance(message.answers[0], str)
        else message.answers[0][0]
    )


@pytest.mark.asyncio
async def test_handle_agreements_confirm_wrong_button(
    user_repo, advertiser_repo
) -> None:
    """handle_agreements_confirm rejects non-confirm text."""
    message = FakeMessage(text="Wrong", user=FakeUser(54, "adv", "Adv"))
    state = FakeFSMContext()
    state.state = AdvertiserRegistrationStates.agreements
    await state.update_data(
        user_id=UUID("00000000-0000-0000-0000-000000000054")
    )
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    user_service = UserRoleService(user_repo=user_repo)

    await handle_agreements_confirm(message, state, adv_service, user_service)

    assert message.answers
    ans = message.answers[0]
    assert "Подтвердить согласие" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_handle_agreements_confirm_success(
    user_repo, advertiser_repo
) -> None:
    """handle_agreements_confirm creates profile on confirm."""
    from tests.helpers.factories import create_test_user

    user_id = UUID("00000000-0000-0000-0000-000000000055")
    await create_test_user(
        user_repo,
        user_id=user_id,
        external_id="55",
        username="adv55",
        status=UserStatus.ACTIVE,
    )
    message = FakeMessage(
        text=CONFIRM_AGREEMENT_BUTTON_TEXT, user=FakeUser(55, "adv55", "Adv")
    )
    state = FakeFSMContext()
    state.state = AdvertiserRegistrationStates.agreements
    await state.update_data(
        user_id=user_id,
        name="Test Name",
        phone="+79001234567",
        brand="My Brand",
        site_link="https://site.com",
        city="City",
        company_activity="Activity",
    )
    adv_service = AdvertiserRegistrationService(
        user_repo=user_repo, advertiser_repo=advertiser_repo
    )
    user_service = UserRoleService(user_repo=user_repo)

    await handle_agreements_confirm(message, state, adv_service, user_service)

    assert state.cleared
    assert message.answers
    ans = message.answers[0]
    assert "UGC-креаторов" in (ans if isinstance(ans, str) else ans[0])
    profile = await advertiser_repo.get_by_user_id(user_id)
    assert profile is not None
    assert profile.phone == "+79001234567"
