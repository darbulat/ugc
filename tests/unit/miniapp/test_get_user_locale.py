"""Tests for _get_user_locale helper in miniapp/api.py."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import Country, User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.miniapp.api import _get_user_locale


def _make_request(
    default_locale: str = "ru",
    dispatcher: dict | MagicMock | None = None,
) -> MagicMock:
    """Build a minimal mock FastAPI Request for _get_user_locale tests."""
    config = MagicMock()
    config.market.default_locale = default_locale

    if dispatcher is None:
        dispatcher = MagicMock()
        dispatcher.get.return_value = None

    request = MagicMock()
    request.app.state.config = config
    request.app.state.dispatcher = dispatcher
    return request


def _make_user(country: str | None = "ru") -> User:
    """Create a minimal User entity."""
    return User(
        user_id=uuid4(),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country=country,
    )


def _make_country(code: str = "ru", locale: str = "ru") -> Country:
    """Create a Country entity."""
    return Country(
        code=code,
        name_native="Россия",
        currency_code="RUB",
        currency_symbol="₽",
        locale=locale,
    )


class TestGetUserLocale:
    """Tests for the _get_user_locale async helper."""

    @pytest.mark.asyncio
    async def test_no_user_role_service_returns_default(self) -> None:
        """When dispatcher has no user_role_service, returns default locale."""
        dispatcher = MagicMock()
        dispatcher.get.return_value = None

        request = _make_request(default_locale="en", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "en"

    @pytest.mark.asyncio
    async def test_no_country_repo_returns_default(self) -> None:
        """country_repo absent but user_role_service present — default."""
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=_make_user())

        def dispatcher_get(key: str):
            if key == "user_role_service":
                return user_role_service
            return None  # country_repo absent

        dispatcher = MagicMock()
        dispatcher.get = dispatcher_get

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_user_not_found_returns_default(self) -> None:
        """When user_role_service.get_user returns None, returns default."""
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=None)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock()

        def dispatcher_get(key: str):
            return (
                user_role_service
                if key == "user_role_service"
                else country_repo
            )

        dispatcher = MagicMock()
        dispatcher.get = dispatcher_get

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"
        country_repo.get_by_code.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_found_no_country_returns_default(self) -> None:
        """When user.country is None, returns default without country lookup."""
        user = _make_user(country=None)
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock()

        def dispatcher_get(key: str):
            return (
                user_role_service
                if key == "user_role_service"
                else country_repo
            )

        dispatcher = MagicMock()
        dispatcher.get = dispatcher_get

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"
        country_repo.get_by_code.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_and_country_found_returns_country_locale(self) -> None:
        """When user and country are both found, returns country.locale."""
        user = _make_user(country="kz")
        country = Country(
            code="kz",
            name_native="Казахстан",
            currency_code="KZT",
            currency_symbol="₸",
            locale="kk",
        )
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=country)

        def dispatcher_get(key: str):
            return (
                user_role_service
                if key == "user_role_service"
                else country_repo
            )

        dispatcher = MagicMock()
        dispatcher.get = dispatcher_get

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "kk"
        user_role_service.get_user.assert_awaited_once_with(
            "123", MessengerType.TELEGRAM
        )
        country_repo.get_by_code.assert_awaited_once_with("kz")

    @pytest.mark.asyncio
    async def test_user_found_country_not_found_returns_default(self) -> None:
        """When get_by_code returns None, falls back to default."""
        user = _make_user(country="xx")
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=None)

        def dispatcher_get(key: str):
            return (
                user_role_service
                if key == "user_role_service"
                else country_repo
            )

        dispatcher = MagicMock()
        dispatcher.get = dispatcher_get

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_default_locale_from_config_is_used(self) -> None:
        """The default locale comes from config.market.default_locale."""
        dispatcher = MagicMock()
        dispatcher.get.return_value = None

        request = _make_request(default_locale="en", dispatcher=dispatcher)
        result = await _get_user_locale(request, "456")
        assert result == "en"
