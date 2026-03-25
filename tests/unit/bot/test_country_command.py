"""Tests for /country command and country change callback."""

import pytest

from tests.helpers.fakes import (
    FakeCallback,
    FakeMessage,
    FakeMessengerClient,
    FakeUser,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_CHANGE_COUNTRY_PREFIX,
)
from ugc_bot.bot.telegram.handlers.start import (
    country_change_selected,
    country_command,
)
from ugc_bot.domain.entities import Country
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryCountryRepository,
    InMemoryUserRepository,
)


def _make_country_repo(*countries: Country) -> InMemoryCountryRepository:
    return InMemoryCountryRepository(countries={c.code: c for c in countries})


RU_COUNTRY = Country(
    code="ru",
    name_native="Россия",
    currency_code="RUB",
    currency_symbol="₽",
    enabled=True,
)
KZ_COUNTRY = Country(
    code="kz",
    name_native="Қазақстан",
    currency_code="KZT",
    currency_symbol="₸",
    enabled=True,
)


@pytest.mark.asyncio
async def test_country_command_sends_country_keyboard(
    event_adapter, bot_texts_service
) -> None:
    """/country command shows country selection keyboard."""
    country_repo = _make_country_repo(RU_COUNTRY, KZ_COUNTRY)
    message = FakeMessage(text="/country", user=FakeUser(1, "alice", "Alice"))
    client = FakeMessengerClient()

    await country_command(
        message,
        bot_texts_service=bot_texts_service,
        country_repo=country_repo,
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
    assert any(
        cd.startswith(CALLBACK_CHANGE_COUNTRY_PREFIX)
        for cd in all_callback_data
    )


@pytest.mark.asyncio
async def test_country_command_no_repo(
    event_adapter, bot_texts_service
) -> None:
    """/country with no country_repo sends empty keyboard."""
    message = FakeMessage(text="/country", user=FakeUser(2, "bob", "Bob"))
    client = FakeMessengerClient()

    await country_command(
        message,
        bot_texts_service=bot_texts_service,
        country_repo=None,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(client.sent_text) == 1
    sent = client.sent_text[0]
    assert sent["keyboard"] is not None
    assert sent["keyboard"].rows == []


@pytest.mark.asyncio
async def test_country_change_selected_saves_country(
    event_adapter, bot_texts_service
) -> None:
    """chg_country: callback saves the country for existing user."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        username="dave",
    )
    await service.set_country(
        external_id="10",
        messenger_type=MessengerType.TELEGRAM,
        country_code="ru",
    )

    country_repo = _make_country_repo(RU_COUNTRY, KZ_COUNTRY)

    message = FakeMessage(user=FakeUser(10, "dave", "Dave"))
    callback = FakeCallback(
        data=f"{CALLBACK_CHANGE_COUNTRY_PREFIX}kz",
        user=FakeUser(10, "dave", "Dave"),
        message=message,
    )
    client = FakeMessengerClient()

    await country_change_selected(
        callback,
        user_role_service=service,
        bot_texts_service=bot_texts_service,
        country_repo=country_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    saved = await user_repo.get_by_external("10", MessengerType.TELEGRAM)
    assert saved is not None
    assert saved.country == "kz"

    # Should send confirmation message
    assert len(client.sent_text) == 1


@pytest.mark.asyncio
async def test_country_change_rejects_unknown_code(
    event_adapter, bot_texts_service
) -> None:
    """chg_country: callback with unknown code does not change the country."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="eve",
    )
    await service.set_country(
        external_id="20",
        messenger_type=MessengerType.TELEGRAM,
        country_code="ru",
    )

    country_repo = _make_country_repo(RU_COUNTRY)

    message = FakeMessage(user=FakeUser(20, "eve", "Eve"))
    callback = FakeCallback(
        data=f"{CALLBACK_CHANGE_COUNTRY_PREFIX}xx",
        user=FakeUser(20, "eve", "Eve"),
        message=message,
    )
    client = FakeMessengerClient()

    await country_change_selected(
        callback,
        user_role_service=service,
        bot_texts_service=bot_texts_service,
        country_repo=country_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    # Country should NOT be changed
    saved = await user_repo.get_by_external("20", MessengerType.TELEGRAM)
    assert saved is not None
    assert saved.country == "ru"

    # No message should have been sent
    assert len(client.sent_text) == 0


@pytest.mark.asyncio
async def test_country_change_user_not_found(
    event_adapter, bot_texts_service
) -> None:
    """chg_country: callback with no matching user returns silently."""
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)

    country_repo = _make_country_repo(RU_COUNTRY)

    message = FakeMessage(user=FakeUser(99, "ghost", "Ghost"))
    callback = FakeCallback(
        data=f"{CALLBACK_CHANGE_COUNTRY_PREFIX}ru",
        user=FakeUser(99, "ghost", "Ghost"),
        message=message,
    )
    client = FakeMessengerClient()

    await country_change_selected(
        callback,
        user_role_service=service,
        bot_texts_service=bot_texts_service,
        country_repo=country_repo,
        messenger_client=client,
        event_adapter=event_adapter,
    )

    assert len(client.sent_text) == 0
