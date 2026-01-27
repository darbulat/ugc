"""Scheduler for feedback requests after contacts sharing."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Iterable
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


def _iter_due_interactions(interaction_repo, cutoff: datetime) -> Iterable[Interaction]:
    """List interactions due for feedback."""

    return interaction_repo.list_due_for_feedback(cutoff)


async def _send_feedback_requests(
    bot: Bot,
    interaction: Interaction,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
) -> None:
    """Send feedback requests to both sides for a single interaction."""

    blogger = user_role_service.get_user_by_id(interaction.blogger_id)
    advertiser = user_role_service.get_user_by_id(interaction.advertiser_id)

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

    for interaction in _iter_due_interactions(interaction_repo, cutoff):
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
    if not config.feedback.feedback_enabled:
        logger.info("Feedback scheduler disabled by config")
        return

    session_factory = create_session_factory(config.db.database_url)
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
