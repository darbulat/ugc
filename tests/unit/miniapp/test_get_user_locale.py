"""Tests for _get_user_locale helper in miniapp/api.py."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import User
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


def _make_user(language: str | None = "ru") -> User:
    """Create a minimal User entity."""
    return User(
        user_id=uuid4(),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        language=language,
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
    async def test_user_not_found_returns_default(self) -> None:
        """When user_role_service.get_user returns None, returns default."""
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=None)

        dispatcher = MagicMock()
        dispatcher.get.return_value = user_role_service

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_user_found_no_language_returns_default(self) -> None:
        """When user.language is None, returns default."""
        user = _make_user(language=None)
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)

        dispatcher = MagicMock()
        dispatcher.get.return_value = user_role_service

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"

    @pytest.mark.asyncio
    async def test_user_with_language_en_returns_en(self) -> None:
        """When user.language is 'en', returns 'en'."""
        user = _make_user(language="en")
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)

        dispatcher = MagicMock()
        dispatcher.get.return_value = user_role_service

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "en"
        user_role_service.get_user.assert_awaited_once_with(
            "123", MessengerType.TELEGRAM
        )

    @pytest.mark.asyncio
    async def test_user_with_language_ru_returns_ru(self) -> None:
        """When user.language is 'ru', returns 'ru'."""
        user = _make_user(language="ru")
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(return_value=user)

        dispatcher = MagicMock()
        dispatcher.get.return_value = user_role_service

        request = _make_request(default_locale="en", dispatcher=dispatcher)
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

    @pytest.mark.asyncio
    async def test_exception_in_get_user_returns_default(self) -> None:
        """When get_user raises an exception, returns default locale."""
        user_role_service = MagicMock()
        user_role_service.get_user = AsyncMock(
            side_effect=RuntimeError("DB error")
        )

        dispatcher = MagicMock()
        dispatcher.get.return_value = user_role_service

        request = _make_request(default_locale="ru", dispatcher=dispatcher)
        result = await _get_user_locale(request, "123")
        assert result == "ru"
