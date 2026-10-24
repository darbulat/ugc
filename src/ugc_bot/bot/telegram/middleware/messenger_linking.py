"""Consume reserved proofs before locale lookup, metadata sync or signup.

Register after ErrorHandlerMiddleware and before LocaleMiddleware. Webhook
production ingress has its own secret-validated, durable pre-ACK interception.
This fallback accepts the actual Update/Bot from the dispatcher transport.
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from ugc_bot.infrastructure.messenger.telegram.messenger_linking import (
    intercept_reserved_link,
)


class ReservedLinkMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update) and await intercept_reserved_link(
            event, data["bot"], data.get("messenger_linking_service")
        ):
            return True
        return await handler(event, data)
