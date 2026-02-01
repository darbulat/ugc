"""Scheduler for feedback requests after contacts sharing."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Iterable, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.config import FeedbackConfig, load_config
from ugc_bot.domain.entities import Interaction
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import (
    create_session_factory,
    SessionTransactionManager,
    with_optional_tx,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)
_send_retries = 3
_send_retry_delay_seconds = 0.5


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
    interaction_repo,
    cutoff: datetime,
    transaction_manager,
) -> Iterable[Interaction]:
    """List interactions due for feedback within a transaction."""

    async def _run(session: object | None):
        return await interaction_repo.list_due_for_feedback(cutoff, session=session)

    return await with_optional_tx(transaction_manager, _run)


def _next_reminder_datetime(feedback_config: FeedbackConfig) -> datetime:
    """Return next reminder time (e.g. next 10:00 in configured timezone) as UTC."""
    tz = ZoneInfo(feedback_config.feedback_reminder_timezone)
    now_local = datetime.now(tz)
    next_local = now_local.replace(
        hour=feedback_config.feedback_reminder_hour,
        minute=feedback_config.feedback_reminder_minute,
        second=0,
        microsecond=0,
    )
    if next_local <= now_local:
        next_local = next_local + timedelta(days=1)
    return next_local.astimezone(timezone.utc)


async def _send_feedback_requests(
    bot: Bot,
    interaction: Interaction,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    feedback_config: FeedbackConfig,
) -> None:
    """Send feedback requests to both sides for a single interaction (TZ texts + links)."""

    blogger = await user_role_service.get_user_by_id(interaction.blogger_id)
    advertiser = await user_role_service.get_user_by_id(interaction.advertiser_id)
    blogger_profile = (
        await profile_service.get_blogger_profile(interaction.blogger_id)
        if profile_service
        else None
    )
    next_reminder = _next_reminder_datetime(feedback_config)
    sent_to_adv = False
    sent_to_blog = False

    # Send to advertiser if not yet responded
    if advertiser and interaction.from_advertiser is None:
        if advertiser.external_id.isdigit():
            creator_link = ""
            if blogger_profile and blogger_profile.instagram_url:
                url = blogger_profile.instagram_url.strip()
                if url and not url.startswith("http"):
                    url = "https://" + url
                creator_link = f" [креатор]({url})" if url else " креатора"
            text = (
                "Хотим убедиться, что всё прошло корректно. "
                f"Удалось ли вам связаться с креатором{creator_link}?"
            )
            await send_with_retry(
                bot,
                chat_id=int(advertiser.external_id),
                text=text,
                parse_mode="Markdown",
                reply_markup=_feedback_keyboard("adv", interaction.interaction_id),
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"interaction_id": str(interaction.interaction_id)},
            )
            sent_to_adv = True

    # Send to blogger if not yet responded
    if blogger and interaction.from_blogger is None:
        if blogger.external_id.isdigit():
            text = (
                "Мы хотим убедиться, что всё прошло корректно. "
                f"Удалось ли вам связаться с заказчиком по заказу #{interaction.order_id}?"
            )
            await send_with_retry(
                bot,
                chat_id=int(blogger.external_id),
                text=text,
                reply_markup=_feedback_keyboard("blog", interaction.interaction_id),
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"interaction_id": str(interaction.interaction_id)},
            )
            sent_to_blog = True

    if sent_to_adv or sent_to_blog:
        await interaction_service.schedule_next_reminder(
            interaction.interaction_id, next_reminder
        )


async def run_once(
    bot: Bot,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    feedback_config: FeedbackConfig,
    cutoff: datetime,
    transaction_manager,
) -> None:
    """Run a single feedback dispatch cycle."""

    for interaction in await _iter_due_interactions(
        interaction_repo, cutoff, transaction_manager
    ):
        try:
            await _send_feedback_requests(
                bot,
                interaction,
                interaction_service,
                user_role_service,
                profile_service,
                feedback_config,
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
    profile_service: Optional[ProfileService],
    feedback_config: FeedbackConfig,
    interval_seconds: int,
    transaction_manager,
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
                profile_service,
                feedback_config,
                cutoff,
                transaction_manager,
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
    log_startup_info(logger=logger, service_name="Feedback scheduler", config=config)

    if not config.feedback.feedback_enabled:
        logger.info("Feedback scheduler disabled by config")
        return

    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    transaction_manager = SessionTransactionManager(session_factory)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    interaction_repo = SqlAlchemyInteractionRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(session_factory=session_factory)
    advertiser_repo = SqlAlchemyAdvertiserProfileRepository(
        session_factory=session_factory
    )

    user_role_service = UserRoleService(
        user_repo=user_repo, transaction_manager=transaction_manager
    )
    interaction_service = InteractionService(
        interaction_repo=interaction_repo,
        transaction_manager=transaction_manager,
    )
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=advertiser_repo,
    )

    bot = Bot(token=config.bot.bot_token)
    asyncio.run(
        run_loop(
            bot,
            interaction_repo,
            interaction_service,
            user_role_service,
            profile_service,
            config.feedback,
            interval_seconds=config.feedback.feedback_poll_interval_seconds,
            transaction_manager=transaction_manager,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main()
