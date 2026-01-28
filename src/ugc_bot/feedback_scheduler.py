"""Scheduler for feedback requests after contacts sharing."""

import asyncio
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import logging
from typing import Any, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.config import load_config
from ugc_bot.domain.entities import Interaction
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyInteractionRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.logging_setup import configure_logging


logger = logging.getLogger(__name__)
_send_retries = 3
_send_retry_delay_seconds = 0.5
_MASK = "***"
_SENSITIVE_KEYS = {
    "admin_password",
    "admin_secret",
    "bot_token",
    "database_url",
    "instagram_access_token",
    "instagram_app_secret",
    "instagram_webhook_verify_token",
    "redis_url",
    "telegram_provider_token",
}
_SENSITIVE_KEYWORDS = ("password", "secret", "token")


def _get_service_version() -> str:
    """Return installed service version if available."""

    for dist_name in ("ugc-bot", "ugc_bot"):
        try:
            return version(dist_name)
        except PackageNotFoundError:
            continue
    return "unknown"


def _mask_url_credentials(value: str) -> str:
    """Mask credentials in URLs like scheme://user:pass@host."""

    try:
        parts: SplitResult = urlsplit(value)
    except Exception:
        return value

    if not parts.scheme or not parts.netloc:
        return value

    if "@" not in parts.netloc:
        return value

    userinfo, hostinfo = parts.netloc.rsplit("@", 1)
    if ":" not in userinfo:
        return value

    username = userinfo.split(":", 1)[0]
    masked_netloc = f"{username}:{_MASK}@{hostinfo}"
    return urlunsplit(
        (parts.scheme, masked_netloc, parts.path, parts.query, parts.fragment)
    )


def _is_sensitive_key(key: str) -> bool:
    """Return True if key likely holds sensitive value."""

    lowered = key.lower()
    if lowered in _SENSITIVE_KEYS:
        return True
    return any(marker in lowered for marker in _SENSITIVE_KEYWORDS)


def _sanitize_for_logging(obj: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize config for safe logging."""

    if key is not None and _is_sensitive_key(key):
        return _MASK

    if isinstance(obj, dict):
        return {str(k): _sanitize_for_logging(v, key=str(k)) for k, v in obj.items()}

    if isinstance(obj, list):
        return [_sanitize_for_logging(v) for v in obj]

    if isinstance(obj, str):
        return _mask_url_credentials(obj)

    return obj


def _safe_config_for_logging(config: Any) -> dict[str, Any]:
    """Return config dump suitable for logs (secrets masked)."""

    raw = config.model_dump() if hasattr(config, "model_dump") else dict(config)
    sanitized = _sanitize_for_logging(raw)
    return sanitized if isinstance(sanitized, dict) else {}


def _log_startup_info(config: Any) -> None:
    """Log service version and sanitized config at startup."""

    service_version = _get_service_version()
    safe_config = _safe_config_for_logging(config)
    log_format = (
        getattr(getattr(config, "log", None), "log_format", "")
        if config is not None
        else ""
    )
    is_json = str(log_format).lower() == "json"

    # In text logs, standard formatter drops extra fields. Include details in message.
    if not is_json:
        logger.info(
            "Feedback scheduler starting (version=%s, config=%s)",
            service_version,
            json.dumps(safe_config, ensure_ascii=False, default=str, sort_keys=True),
        )
        return

    logger.info(
        "Feedback scheduler starting",
        extra={
            "service_version": service_version,
            "config": safe_config,
        },
    )


def _feedback_keyboard(kind: str, interaction_id: UUID) -> InlineKeyboardMarkup:
    """Build feedback buttons."""

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Сделка состоялась"
                    if kind == "adv"
                    else "✅ Всё прошло нормально",
                    callback_data=f"feedback:{kind}:{interaction_id}:ok",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Не договорились",
                    callback_data=f"feedback:{kind}:{interaction_id}:no_deal",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⏳ Еще не связался",
                    callback_data=f"feedback:{kind}:{interaction_id}:postpone",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚠️ Проблема / подозрение на мошенничество",
                    callback_data=f"feedback:{kind}:{interaction_id}:issue",
                )
            ],
        ]
    )


async def _iter_due_interactions(
    interaction_repo, cutoff: datetime
) -> Iterable[Interaction]:
    """List interactions due for feedback."""

    return await interaction_repo.list_due_for_feedback(cutoff)


async def _send_feedback_requests(
    bot: Bot,
    interaction: Interaction,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
) -> None:
    """Send feedback requests to both sides for a single interaction."""

    blogger = await user_role_service.get_user_by_id(interaction.blogger_id)
    advertiser = await user_role_service.get_user_by_id(interaction.advertiser_id)

    # Send to advertiser if not yet responded
    if advertiser and interaction.from_advertiser is None:
        if advertiser.external_id.isdigit():
            blogger_handle = (
                f"@{blogger.username}" if blogger and blogger.username else "блогер"
            )
            await send_with_retry(
                bot,
                chat_id=int(advertiser.external_id),
                text=(
                    f"Вы связывались с блогером {blogger_handle} "
                    f"по заказу #{interaction.order_id}?\n"
                    f"Выберите вариант:"
                ),
                reply_markup=_feedback_keyboard("adv", interaction.interaction_id),
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"interaction_id": str(interaction.interaction_id)},
            )

    # Send to blogger if not yet responded
    if blogger and interaction.from_blogger is None:
        if blogger.external_id.isdigit():
            advertiser_handle = (
                f"@{advertiser.username}"
                if advertiser and advertiser.username
                else "рекламодатель"
            )
            await send_with_retry(
                bot,
                chat_id=int(blogger.external_id),
                text=(
                    f"Вы связывались с рекламодателем {advertiser_handle} "
                    f"по офферу #{interaction.order_id}?\n"
                    f"Выберите вариант:"
                ),
                reply_markup=_feedback_keyboard("blog", interaction.interaction_id),
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"interaction_id": str(interaction.interaction_id)},
            )


async def run_once(
    bot: Bot,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    cutoff: datetime,
) -> None:
    """Run a single feedback dispatch cycle."""

    for interaction in await _iter_due_interactions(interaction_repo, cutoff):
        try:
            await _send_feedback_requests(
                bot,
                interaction,
                interaction_service,
                user_role_service,
            )
        except Exception as exc:  # pragma: no cover - depends on transport failures
            logger.warning(
                "Feedback request failed",
                extra={
                    "interaction_id": str(interaction.interaction_id),
                    "error": str(exc),
                },
            )


async def run_loop(
    bot: Bot,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Run periodic feedback dispatch."""

    iterations = 0
    try:
        while True:
            cutoff = datetime.now(timezone.utc)
            await run_once(
                bot,
                interaction_repo,
                interaction_service,
                user_role_service,
                cutoff,
            )
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        session = getattr(bot, "session", None)
        if session is not None:
            await session.close()


def main() -> None:
    """Start feedback scheduler loop."""

    config = load_config()
    configure_logging(
        config.log.log_level, json_format=config.log.log_format.lower() == "json"
    )
    _log_startup_info(config)
    if not config.feedback.feedback_enabled:
        logger.info("Feedback scheduler disabled by config")
        return

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    interaction_repo = SqlAlchemyInteractionRepository(session_factory=session_factory)

    user_role_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    bot = Bot(token=config.bot.bot_token)
    asyncio.run(
        run_loop(
            bot,
            interaction_repo,
            interaction_service,
            user_role_service,
            interval_seconds=config.feedback.feedback_poll_interval_seconds,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main()
