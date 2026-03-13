"""Tests for language selection step in /start handler."""

import pytest

from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeMessengerClient,
    FakeReferralService,
    FakeUser,
    make_language_repo,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import (
    language_command,
    language_selected,
    start_command,
)
from ugc_bot.domain.entities import Country, Language
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryCountryRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_start_always_shows_language_keyboard_when_language_not_set(
    messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Always show language keyboard when user.language is None.

    user.language=None, tg_language_code='ru' (matches available)
    -> shows language keyboard regardless of tg code (no auto-detect).
    """
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    referral_service = FakeReferralService()

    language_repo = make_language_repo(
        Language(code="ru", name_native="Русский", enabled=True),
        Language(code="en", name_native="English", enabled=True),
    )

    # User whose tg language_code matches an available language
    message = FakeMessage(
        text="/start",
        user=FakeUser(1, "alice", "Alice", language_code="ru"),
    )
    state = FakeFSMContext(state=None)
    client = FakeMessengerClient()

    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        language_repo=language_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    # Language is NOT auto-detected — user must choose manually
    saved = await user_repo.get_by_external("1", MessengerType.TELEGRAM)
    assert saved is None or saved.language is None

    # Should show language keyboard
    assert len(client.sent_text) == 1
    sent = client.sent_text[0]
    assert sent["keyboard"] is not None
    all_callback_data = [
        btn.callback_data
        for row in sent["keyboard"].rows
        for btn in row
        if btn.callback_data
    ]
    assert any(cd.startswith("lang:") for cd in all_callback_data)


@pytest.mark.asyncio
async def test_start_shows_language_keyboard_when_tg_code_not_in_available(
    messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Show language keyboard when tg code is not in available set.

    user.language=None, tg_language_code='fr', available={'ru','en'}
    -> sends language keyboard.
    """
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    referral_service = FakeReferralService()

    language_repo = make_language_repo(
        Language(code="ru", name_native="Русский", enabled=True),
        Language(code="en", name_native="English", enabled=True),
    )

    # User with tg language_code="fr" (not available)
    message = FakeMessage(
        text="/start",
        user=FakeUser(2, "bob", "Bob", language_code="fr"),
    )
    state = FakeFSMContext(state=None)
    client = FakeMessengerClient()

    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        language_repo=language_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    # Should show language keyboard and return early
    assert len(client.sent_text) == 1
    sent = client.sent_text[0]
    assert sent["keyboard"] is not None
    # Language keyboard has rows with lang: callback data
    all_callback_data = [
        btn.callback_data
        for row in sent["keyboard"].rows
        for btn in row
        if btn.callback_data
    ]
    assert any(cd.startswith("lang:") for cd in all_callback_data)

    # Language should NOT be set on user
    saved = await user_repo.get_by_external("2", MessengerType.TELEGRAM)
    assert saved is None or saved.language is None


@pytest.mark.asyncio
async def test_start_skips_language_step_when_language_set(
    messenger_client, event_adapter, config, bot_texts_service
) -> None:
    """Skip language step when language already set; show country keyboard.

    user.language='en' (already set), country=None
    -> shows country keyboard (language step skipped).
    """
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    referral_service = FakeReferralService()

    language_repo = make_language_repo(
        Language(code="ru", name_native="Русский", enabled=True),
        Language(code="en", name_native="English", enabled=True),
    )

    # Pre-create user with language already set but no country
    await service.set_user(
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
        username="carol",
    )
    await service.set_language(
        external_id="3",
        messenger_type=MessengerType.TELEGRAM,
        language_code="en",
    )

    country_repo = InMemoryCountryRepository(
        countries={
            "us": Country(
                code="us",
                name_native="United States",
                currency_code="USD",
                currency_symbol="$",
                enabled=True,
            )
        }
    )

    message = FakeMessage(
        text="/start",
        user=FakeUser(3, "carol", "Carol", language_code="en"),
    )
    state = FakeFSMContext(state=None)
    client = FakeMessengerClient()

    await start_command(
        message,
        state=state,
        user_role_service=service,
        referral_service=referral_service,
        config=config,
        bot_texts_service=bot_texts_service,
        language_repo=language_repo,
        country_repo=country_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    # Should skip language step and show country keyboard
    assert len(client.sent_text) == 1
    sent = client.sent_text[0]
    assert sent["keyboard"] is not None
    # Country keyboard has rows with country: callback data
    all_callback_data = [
        btn.callback_data
        for row in sent["keyboard"].rows
        for btn in row
        if btn.callback_data
    ]
    assert any(cd.startswith("country:") for cd in all_callback_data)


@pytest.mark.asyncio
async def test_language_selected_sets_language_and_shows_country_keyboard(
    event_adapter, config, bot_texts_service
) -> None:
    """lang: callback saves language, shows country keyboard when no country."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="dave",
    )

    country_repo = InMemoryCountryRepository(
        countries={
            "ru": Country(
                code="ru",
                name_native="Россия",
                currency_code="RUB",
                currency_symbol="₽",
                enabled=True,
            )
        }
    )

    message = FakeMessage(user=FakeUser(10, "dave", "Dave"))
    callback = FakeCallback(
        data="lang:ru",
        user=FakeUser(10, "dave", "Dave"),
        message=message,
    )
    client = FakeMessengerClient()

    await language_selected(
        callback,
        user_role_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        country_repo=country_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    saved = await user_repo.get_by_external("10", MessengerType.TELEGRAM)
    assert saved is not None
    assert saved.language == "ru"

    assert len(client.sent_text) == 1
    all_callback_data = [
        btn.callback_data
        for row in client.sent_text[0]["keyboard"].rows
        for btn in row
        if btn.callback_data
    ]
    assert any(cd.startswith("country:") for cd in all_callback_data)


@pytest.mark.asyncio
async def test_language_selected_shows_role_keyboard_when_country_set(
    event_adapter, config, bot_texts_service
) -> None:
    """lang: callback shows role keyboard when country is already set."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        username="eve",
    )
    await service.set_country(
        external_id="11",
        messenger_type=MessengerType.TELEGRAM,
        country_code="ru",
    )

    message = FakeMessage(user=FakeUser(11, "eve", "Eve"))
    callback = FakeCallback(
        data="lang:ru",
        user=FakeUser(11, "eve", "Eve"),
        message=message,
    )
    client = FakeMessengerClient()

    await language_selected(
        callback,
        user_role_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(client.sent_text) == 1
    # Role keyboard — no country: prefix
    all_callback_data = [
        btn.callback_data
        for row in client.sent_text[0]["keyboard"].rows
        for btn in row
        if btn.callback_data
    ]
    assert not any(cd.startswith("country:") for cd in all_callback_data)


@pytest.mark.asyncio
async def test_language_callback_rejects_unknown_code(
    event_adapter, config, bot_texts_service
) -> None:
    """lang: callback with unknown code does not save the language."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="mallory",
    )

    language_repo = make_language_repo(
        Language(code="ru", name_native="Русский", enabled=True),
        Language(code="en", name_native="English", enabled=True),
    )

    message = FakeMessage(user=FakeUser(30, "mallory", "Mallory"))
    callback = FakeCallback(
        data="lang:xx",
        user=FakeUser(30, "mallory", "Mallory"),
        message=message,
    )
    client = FakeMessengerClient()

    await language_selected(
        callback,
        user_role_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        language_repo=language_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    # Language should NOT be saved
    saved = await user_repo.get_by_external("30", MessengerType.TELEGRAM)
    assert saved is None or saved.language is None

    # No message should have been sent
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_language_command_sends_language_keyboard(
    event_adapter, bot_texts_service
) -> None:
    """language command sends language selection keyboard."""
    language_repo = make_language_repo(
        Language(code="ru", name_native="Русский", enabled=True),
        Language(code="en", name_native="English", enabled=True),
    )
    message = FakeMessage(text="/language", user=FakeUser(20, "frank", "Frank"))
    client = FakeMessengerClient()

    await language_command(
        message,
        bot_texts_service=bot_texts_service,
        language_repo=language_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(client.sent_text) == 1
    sent = client.sent_text[0]
    assert sent["keyboard"] is not None
    all_callback_data = [
        btn.callback_data
        for row in sent["keyboard"].rows
        for btn in row
        if btn.callback_data
    ]
    assert any(cd.startswith("lang:") for cd in all_callback_data)
