"""Middleware functions for Max messenger handlers."""

import logging

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType

logger = logging.getLogger(__name__)


async def resolve_locale(
    incoming: IncomingMessage | IncomingCallback,
    user_role_service: UserRoleService,
    default_locale: str = "ru",
) -> str:
    """Resolve user locale from DB, fallback to default."""
    try:
        user = await user_role_service.get_user(
            external_id=incoming.user.external_id,
            messenger_type=MessengerType.MAX,
        )
        if user and user.language:
            return user.language
    except Exception:
        logger.exception(
            "Failed to resolve locale for Max user %s",
            incoming.user.external_id,
        )
    return default_locale
