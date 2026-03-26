"""Custom filters (e.g. match message text to localized bot_texts key)."""

from typing import Any

from aiogram.filters import BaseFilter
from aiogram.types import Message


class TextEqualsKey(BaseFilter):
    """Pass when message.text equals bot_texts[key] for current locale."""

    def __init__(self, key: str) -> None:
        self.key = key

    async def __call__(self, event: Message, *args: Any, **kwargs: Any) -> bool:
        """Compare event.text to bot_texts_service.get(key, locale)."""
        data = (args[1] if len(args) > 1 else kwargs.get("data")) or {}
        service = data.get("bot_texts_service")
        config = data.get("config")
        locale = (
            data.get("user_locale")
            or data.get("default_locale")
            or (config.market.default_locale if config else "ru")
        )
        if not service:
            return False
        expected = (await service.get(self.key, locale)).strip()
        return (event.text or "").strip() == expected
