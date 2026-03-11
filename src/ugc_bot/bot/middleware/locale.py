"""Locale middleware: resolve per-user locale from user.country → locale."""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from ugc_bot.domain.enums import MessengerType


class LocaleMiddleware(BaseMiddleware):
    """Inject ``user_locale`` into handler data based on user.country.

    Looks up the current Telegram user in the DB, fetches their country,
    and sets ``data["user_locale"]`` to ``country.locale``.
    Falls back to ``data["default_locale"]`` when user/country is unknown.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Resolve locale and pass to handler."""
        data["user_locale"] = await self._resolve(data)
        return await handler(event, data)

    @staticmethod
    async def _resolve(data: dict[str, Any]) -> str:
        default: str = data.get("default_locale") or "ru"
        user_repo = data.get("user_repo")
        country_repo = data.get("country_repo")
        if not user_repo or not country_repo:
            return default
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return default
        external_id = str(tg_user.id)
        user = await user_repo.get_by_external(
            external_id, MessengerType.TELEGRAM
        )
        if not user or not user.country:
            return default
        country = await country_repo.get_by_code(user.country)
        return country.locale if country else default
