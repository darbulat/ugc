"""Tests for LocaleMiddleware."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.bot.middleware.locale import LocaleMiddleware
from ugc_bot.domain.entities import Country, User
from ugc_bot.domain.enums import MessengerType, UserStatus


def _make_user(language: str | None = "ru", country: str | None = None) -> User:
    """Create a minimal User entity for testing."""
    return User(
        user_id=uuid4(),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        language=language,
        country=country,
    )


def _make_tg_user(user_id: int = 123) -> MagicMock:
    """Create a mock Telegram user object."""
    tg_user = MagicMock()
    tg_user.id = user_id
    return tg_user


class TestLocaleMiddlewareResolveLocale:
    """Tests for LocaleMiddleware._resolve_locale static method."""

    def test_no_user_returns_default(self) -> None:
        """When user is None, returns the default locale."""
        data: dict = {}
        result = LocaleMiddleware._resolve_locale(None, data)
        assert result == "ru"

    def test_user_without_language_returns_default(self) -> None:
        """When user.language is None, returns the default locale."""
        user = _make_user(language=None)
        data: dict = {}
        result = LocaleMiddleware._resolve_locale(user, data)
        assert result == "ru"

    def test_user_with_language_en_returns_en(self) -> None:
        """When user.language is 'en', returns 'en'."""
        user = _make_user(language="en")
        data: dict = {}
        result = LocaleMiddleware._resolve_locale(user, data)
        assert result == "en"

    def test_user_with_language_ru_returns_ru(self) -> None:
        """When user.language is 'ru', returns 'ru'."""
        user = _make_user(language="ru")
        data: dict = {}
        result = LocaleMiddleware._resolve_locale(user, data)
        assert result == "ru"

    def test_custom_default_locale_is_respected(self) -> None:
        """When data has default_locale set, it is used instead of 'ru'."""
        data: dict = {"default_locale": "en"}
        result = LocaleMiddleware._resolve_locale(None, data)
        assert result == "en"

    def test_falsy_default_locale_falls_back_to_ru(self) -> None:
        """When default_locale is an empty string, falls back to 'ru'."""
        data: dict = {"default_locale": ""}
        result = LocaleMiddleware._resolve_locale(None, data)
        assert result == "ru"

    def test_custom_default_locale_used_when_no_language(self) -> None:
        """Custom default_locale is returned when user has no language set."""
        user = _make_user(language=None)
        data: dict = {"default_locale": "en"}
        result = LocaleMiddleware._resolve_locale(user, data)
        assert result == "en"


class TestLocaleMiddlewareResolveCurrency:
    """Tests for LocaleMiddleware._resolve_currency static method."""

    @pytest.mark.asyncio
    async def test_no_user_returns_fallback(self) -> None:
        """When user is None, returns the static fallback."""
        data: dict = {"currency_symbol": "₽"}
        result = await LocaleMiddleware._resolve_currency(None, data)
        assert result == "₽"

    @pytest.mark.asyncio
    async def test_user_no_country_returns_fallback(self) -> None:
        """When user.country is None, returns the static fallback."""
        user = _make_user(country=None)
        data: dict = {"currency_symbol": "₽"}
        result = await LocaleMiddleware._resolve_currency(user, data)
        assert result == "₽"

    @pytest.mark.asyncio
    async def test_user_country_no_repo_returns_fallback(self) -> None:
        """When country_repo is absent, returns the static fallback."""
        user = _make_user(country="kz")
        data: dict = {"currency_symbol": "₽"}
        result = await LocaleMiddleware._resolve_currency(user, data)
        assert result == "₽"

    @pytest.mark.asyncio
    async def test_resolves_currency_from_country(self) -> None:
        """Returns currency_symbol from user's country."""
        user = _make_user(country="kz")
        kz = Country(
            code="kz",
            name_native="Казахстан",
            currency_code="KZT",
            currency_symbol="₸",
        )
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=kz)
        data: dict = {"currency_symbol": "₽", "country_repo": country_repo}
        result = await LocaleMiddleware._resolve_currency(user, data)
        assert result == "₸"
        country_repo.get_by_code.assert_awaited_once_with("kz")

    @pytest.mark.asyncio
    async def test_country_not_found_returns_fallback(self) -> None:
        """When country_repo returns None, returns the static fallback."""
        user = _make_user(country="xx")
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=None)
        data: dict = {"currency_symbol": "₽", "country_repo": country_repo}
        result = await LocaleMiddleware._resolve_currency(user, data)
        assert result == "₽"

    @pytest.mark.asyncio
    async def test_no_fallback_in_data_defaults_to_empty_string(self) -> None:
        """No currency_symbol in data and no country: falls back to ''."""
        data: dict = {}
        result = await LocaleMiddleware._resolve_currency(None, data)
        assert result == ""


class TestLocaleMiddlewareGetUser:
    """Tests for LocaleMiddleware._get_user static method."""

    @pytest.mark.asyncio
    async def test_no_user_role_service_returns_none(self) -> None:
        """When user_role_service is absent, returns None."""
        data: dict = {"event_from_user": _make_tg_user()}
        result = await LocaleMiddleware._get_user(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_event_from_user_returns_none(self) -> None:
        """When event_from_user is None, returns None."""
        data: dict = {"user_role_service": MagicMock(), "event_from_user": None}
        result = await LocaleMiddleware._get_user(data)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_user_from_service(self) -> None:
        """Fetches and returns the user from user_role_service."""
        user = _make_user()
        svc = MagicMock()
        svc.get_user = AsyncMock(return_value=user)
        data: dict = {
            "user_role_service": svc,
            "event_from_user": _make_tg_user(42),
        }
        result = await LocaleMiddleware._get_user(data)
        assert result is user
        svc.get_user.assert_awaited_once_with("42", MessengerType.TELEGRAM)


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
    async def test_call_resolves_locale_from_user_language(self) -> None:
        """__call__ sets data['user_locale'] to user.language when available."""
        user = _make_user(language="en")
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)

        middleware = LocaleMiddleware()
        handler = AsyncMock(return_value=None)
        event = MagicMock()
        data: dict = {
            "user_role_service": user_role_service,
            "event_from_user": _make_tg_user(),
        }

        await middleware(handler, event, data)

        assert data["user_locale"] == "en"
        handler.assert_awaited_once_with(event, data)

    @pytest.mark.asyncio
    async def test_call_injects_currency_symbol_from_country(self) -> None:
        """__call__ resolves currency_symbol from user's country."""
        kz = Country(
            code="kz",
            name_native="Казахстан",
            currency_code="KZT",
            currency_symbol="₸",
        )
        user = _make_user(language="ru", country="kz")
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)
        country_repo = MagicMock()
        country_repo.get_by_code = AsyncMock(return_value=kz)

        middleware = LocaleMiddleware()
        handler = AsyncMock(return_value=None)
        event = MagicMock()
        data: dict = {
            "user_role_service": user_role_service,
            "event_from_user": _make_tg_user(),
            "currency_symbol": "₽",
            "country_repo": country_repo,
        }

        await middleware(handler, event, data)

        assert data["currency_symbol"] == "₸"

    @pytest.mark.asyncio
    async def test_call_returns_handler_return_value(self) -> None:
        """__call__ propagates the handler's return value to its caller."""
        middleware = LocaleMiddleware()
        handler = AsyncMock(return_value=42)
        event = MagicMock()
        data: dict = {}

        result = await middleware(handler, event, data)

        assert result == 42
