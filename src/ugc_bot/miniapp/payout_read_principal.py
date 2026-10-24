"""Existing-only signed native identity; snapshot revalidation is mandatory."""

from time import time

from fastapi import HTTPException

from ugc_bot.application.payout_view_ports import PayoutReadPrincipal
from ugc_bot.domain.enums import MessengerType
from ugc_bot.miniapp.auth import validate_init_data_for_platform
from ugc_bot.miniapp.principal import require_recent_init_data


async def resolve_payout_read_principal(request, init_data, *, platform):
    require_recent_init_data(init_data, now=time())
    config = request.app.state.config
    max_config = config.max_bot
    try:
        external_id = validate_init_data_for_platform(
            init_data,
            platform=platform,
            telegram_bot_token=config.bot.bot_token,
            max_bot_token=max_config.token if max_config else "",
        )
    except ValueError:
        raise HTTPException(401, "payout_read_session_invalid") from None
    roles = request.app.state.dispatcher.get("user_role_service")
    if roles is None:
        raise HTTPException(503, "payout_read_unavailable")
    user = await roles.get_user(
        external_id,
        MessengerType.TELEGRAM if platform == "telegram" else MessengerType.MAX,
    )
    native = getattr(
        user, "telegram_id" if platform == "telegram" else "max_id", None
    )
    if user is None or native != external_id:
        raise HTTPException(404, "existing_payout_account_required")
    return PayoutReadPrincipal(user.user_id, platform, external_id)
