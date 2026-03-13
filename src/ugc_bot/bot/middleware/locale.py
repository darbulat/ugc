"""Locale middleware: resolve per-user locale and currency."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ugc_bot.domain.enums import MessengerType


class LocaleMiddleware(BaseMiddleware):
    """Inject ``user_locale`` and ``currency_symbol`` into handler data.

    Looks up the current Telegram user in the DB and sets:
    - ``data["user_locale"]``: from ``user.language``, fallback to
      ``default_locale``
    - ``data["currency_symbol"]``: from user's country currency, fallback to
      the static ``data["currency_symbol"]`` config value
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Resolve locale and currency_symbol, then pass to handler."""
        user = await self._get_user(data)
        data["user_locale"] = self._resolve_locale(user, data)
        data["currency_symbol"] = await self._resolve_currency(user, data)
        return await handler(event, data)

    @staticmethod
    async def _get_user(data: dict[str, Any]) -> Any:
        """Fetch user entity for the current Telegram user, or None."""
        user_role_service = data.get("user_role_service")
        if not user_role_service:
            return None
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return None
        return await user_role_service.get_user(
            str(tg_user.id), MessengerType.TELEGRAM
        )

    @staticmethod
    def _resolve_locale(user: Any, data: dict[str, Any]) -> str:
        """Return user.language or default_locale."""
        default: str = data.get("default_locale") or "ru"
        if not user or not user.language:
            return default
        return user.language

    @staticmethod
    async def _resolve_currency(user: Any, data: dict[str, Any]) -> str:
        """Return currency_symbol from user's country, or static fallback."""
        fallback: str = data.get("currency_symbol") or "₽"
        if not user or not user.country:
            return fallback
        country_repo = data.get("country_repo")
        if not country_repo:
            return fallback
        country = await country_repo.get_by_code(user.country)
        if not country or not country.currency_symbol:
            return fallback
        return country.currency_symbol
