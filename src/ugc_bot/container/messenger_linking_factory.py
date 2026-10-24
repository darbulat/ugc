"""Only configured dedicated material can enable new linking authority."""

import hashlib

from aiogram.utils.token import TokenValidationError, extract_bot_id

from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.messenger_linking_service import (
    MessengerLinkingService,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.messenger_linking import LinkScope
from ugc_bot.infrastructure.db.repositories.messenger_linking import (
    SqlMessengerLinkingRepository,
)
from ugc_bot.infrastructure.messenger.link_tokens import LinkTokens


def build_messenger_linking_service(
    config: AppConfig, transactions: TransactionManager | None
) -> MessengerLinkingService | None:
    if transactions is None:
        return None
    settings = config.messenger_linking
    tokens = None
    if (
        settings.token_secret
        and settings.key_id
        and config.max_bot
        and config.max_bot.token
        and config.webhook.webhook_secret
        and config.webhook.webhook_secret.strip()
    ):
        try:
            scope = LinkScope(
                extract_bot_id(config.bot.bot_token),
                config.bot.bot_username,
                settings.key_id,
                hashlib.sha256(
                    b"ugc:link:max-bot-scope:v1\0"
                    + config.max_bot.token.encode()
                ).hexdigest(),
            )
            tokens = LinkTokens(settings.token_secret, scope)
        except (ValueError, TypeError, TokenValidationError):
            tokens = None
    return MessengerLinkingService(
        SqlMessengerLinkingRepository(), transactions, tokens, settings.enabled
    )
