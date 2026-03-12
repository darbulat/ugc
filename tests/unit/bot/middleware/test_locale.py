"""Tests for LocaleMiddleware."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.bot.middleware.locale import LocaleMiddleware
from ugc_bot.domain.entities import Country, User
from ugc_bot.domain.enums import MessengerType, UserStatus


def _make_user(country: str | None = "ru") -> User:
    """Create a minimal User entity for testing."""
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


def _make_country(locale: str = "ru") -> Country:
    """Create a Country entity for testing."""
    return Country(
        code="ru",
        name_native="Россия",
        currency_code="RUB",
        currency_symbol="₽",
        locale=locale,
    )


def _make_tg_user(user_id: int = 123) -> MagicMock:
    """Create a mock Telegram user object."""
    tg_user = MagicMock()
    tg_user.id = user_id
    return tg_user


class TestLocaleMiddlewareResolve:
    """Tests for LocaleMiddleware._resolve static method."""

    @pytest.mark.asyncio
    async def test_no_user_role_service_returns_default(self) -> None:
        """When user_role_service is absent, returns the default locale."""
        data: dict = {
            "country_repo": MagicMock(),
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_no_country_repo_returns_default(self) -> None:
        """When country_repo is absent, returns the default locale."""
        data: dict = {
            "user_role_service": MagicMock(),
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_neither_service_nor_repo_returns_default(self) -> None:
        """When both service and repo are absent, returns the default locale."""
        data: dict = {"event_from_user": _make_tg_user()}
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_no_event_from_user_returns_default(self) -> None:
        """When event_from_user is None, returns the default locale."""
        data: dict = {
            "user_role_service": MagicMock(),
            "country_repo": MagicMock(),
            "event_from_user": None,
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_event_from_user_missing_returns_default(self) -> None:
        """When event_from_user key is absent, returns the default."""
        data: dict = {
            "user_role_service": MagicMock(),
            "country_repo": MagicMock(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_user_not_found_in_db_returns_default(self) -> None:
        """When user_role_service.get_user returns None, returns default."""
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=None)
        country_repo = MagicMock()

        data: dict = {
            "user_role_service": user_role_service,
            "country_repo": country_repo,
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"
        user_role_service.get_user.assert_awaited_once_with(
            "123", MessengerType.TELEGRAM
        )

    @pytest.mark.asyncio
    async def test_user_found_but_no_country_returns_default(self) -> None:
        """When user.country is None, returns the default locale."""
        user = _make_user(country=None)
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock()

        data: dict = {
            "user_role_service": user_role_service,
            "country_repo": country_repo,
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"
        country_repo.get_by_code.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_user_and_country_found_returns_country_locale(self) -> None:
        """User has country and country exists — returns country.locale."""
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

        data: dict = {
            "user_role_service": user_role_service,
            "country_repo": country_repo,
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "kk"
        country_repo.get_by_code.assert_awaited_once_with("kz")

    @pytest.mark.asyncio
    async def test_user_found_country_not_found_returns_default(self) -> None:
        """When get_by_code returns None, falls back to default."""
        user = _make_user(country="xx")
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=None)

        data: dict = {
            "user_role_service": user_role_service,
            "country_repo": country_repo,
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_custom_default_locale_is_respected(self) -> None:
        """When data has default_locale set, it is used instead of 'ru'."""
        data: dict = {
            "default_locale": "en",
            "event_from_user": None,
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "en"

    @pytest.mark.asyncio
    async def test_falsy_default_locale_falls_back_to_ru(self) -> None:
        """When default_locale is an empty string, falls back to 'ru'."""
        data: dict = {
            "default_locale": "",
            "event_from_user": None,
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_custom_default_locale_used_when_user_not_found(self) -> None:
        """Custom default_locale is returned when the user lookup fails."""
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=None)
        country_repo = MagicMock()

        data: dict = {
            "default_locale": "en",
            "user_role_service": user_role_service,
            "country_repo": country_repo,
            "event_from_user": _make_tg_user(),
        }
        result = await LocaleMiddleware._resolve(data)
        assert result == "en"


class TestLocaleMiddlewareCall:
    """Tests for LocaleMiddleware.__call__ method."""

    @pytest.mark.asyncio
    async def test_call_injects_user_locale_into_data(self) -> None:
        """__call__ sets data['user_locale'] before invoking the handler."""
        middleware = LocaleMiddleware()
        handler = AsyncMock(return_value="handler_result")
        event = MagicMock()
        data: dict = {}  # no services → locale will be "ru"

        result = await middleware(handler, event, data)

        assert data["user_locale"] == "ru"
        handler.assert_awaited_once_with(event, data)
        assert result == "handler_result"

    @pytest.mark.asyncio
    async def test_call_resolves_locale_from_country(self) -> None:
        """__call__ sets data['user_locale'] to the resolved country locale."""
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

        middleware = LocaleMiddleware()
        handler = AsyncMock(return_value=None)
        event = MagicMock()
        data: dict = {
            "user_role_service": user_role_service,
            "country_repo": country_repo,
            "event_from_user": _make_tg_user(),
        }

        await middleware(handler, event, data)

        assert data["user_locale"] == "kk"
        handler.assert_awaited_once_with(event, data)

    @pytest.mark.asyncio
    async def test_call_returns_handler_return_value(self) -> None:
        """__call__ propagates the handler's return value to its caller."""
        middleware = LocaleMiddleware()
        handler = AsyncMock(return_value=42)
        event = MagicMock()
        data: dict = {}

        result = await middleware(handler, event, data)

        assert result == 42
