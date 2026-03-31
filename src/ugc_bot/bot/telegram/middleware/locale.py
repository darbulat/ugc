"""Locale middleware: resolve per-user locale and currency."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ugc_bot.domain.enums import MessengerType

logger = logging.getLogger(__name__)


class LocaleMiddleware(BaseMiddleware):
    """Inject ``user_locale`` and ``currency_symbol`` into handler data.

    Looks up the current Telegram user in the DB and sets:
    - ``data["user_locale"]``: from ``user.language``, fallback to
      ``default_locale``
    - ``data["currency_symbol"]``: from user's country currency, fallback to
      the static ``data["currency_symbol"]`` config value

    Also keeps the stored Telegram username in sync with the actual
    ``from_user.username`` provided by the Telegram API on every update.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Resolve locale and currency_symbol, then pass to handler."""
        user = await self._get_user(data)
        await self._sync_telegram_username(user, data)
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
    async def _sync_telegram_username(user: Any, data: dict[str, Any]) -> None:
        """Update stored Telegram username if it changed."""
        if user is None:
            return
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return
        user_role_service = data.get("user_role_service")
        if user_role_service is None:
            return
        try:
            await user_role_service.update_telegram(user, tg_user.username)
        except Exception:
            logger.warning(
                "Failed to sync telegram username",
                extra={"user_id": str(user.user_id)},
                exc_info=True,
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
        # data["currency_symbol"] is set from config by the DI container;
        # use it as fallback so EN users don't see a hardcoded ruble symbol.
        fallback: str = data.get("currency_symbol") or ""
        if not user or not user.country:
            return fallback
        country_repo = data.get("country_repo")
        if not country_repo:
            return fallback
        country = await country_repo.get_by_code(user.country)
        if not country or not country.currency_symbol:
            return fallback
        return country.currency_symbol
