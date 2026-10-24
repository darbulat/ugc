"""Existing-only signed financial identity with no account or country writes."""

from collections.abc import Awaitable
from time import time
from typing import Protocol

from fastapi import HTTPException, Request

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.enums import MessengerType
from ugc_bot.miniapp.auth import validate_init_data_for_platform
from ugc_bot.miniapp.principal import Platform, require_recent_init_data


class FinancialPrincipalResolver(Protocol):
    def __call__(
        self, request: Request, init_data: str, *, platform: Platform
    ) -> Awaitable[AuthenticatedMessengerPrincipal]: ...


async def resolve_financial_principal(
    request: Request, init_data: str, *, platform: Platform
) -> AuthenticatedMessengerPrincipal:
    config = request.app.state.config
    max_config = config.max_bot
    token = (
        config.bot.bot_token
        if platform == "telegram"
        else max_config.token
        if max_config
        else ""
    )
    try:
        require_recent_init_data(init_data, now=time())
        if not token:
            raise ValueError("unconfigured")
        external_id = validate_init_data_for_platform(
            init_data,
            platform=platform,
            telegram_bot_token=config.bot.bot_token,
            max_bot_token=max_config.token if max_config else "",
        )
    except (ValueError, HTTPException):
        raise HTTPException(401, "financial_session_invalid") from None
    roles = request.app.state.dispatcher.get("user_role_service")
    if roles is None:
        raise HTTPException(503, "financial_unavailable")
    user = await roles.get_user(
        external_id,
        MessengerType.TELEGRAM if platform == "telegram" else MessengerType.MAX,
    )
    native = getattr(
        user, "telegram_id" if platform == "telegram" else "max_id", None
    )
    if user is None or native != external_id:
        raise HTTPException(404, "existing_financial_account_required")
    try:
        return AuthenticatedMessengerPrincipal(
            user.user_id, platform, external_id
        )
    except ValueError:
        raise HTTPException(401, "financial_session_invalid") from None
