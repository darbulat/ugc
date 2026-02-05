"""Scheduler for feedback requests after contacts sharing."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.feedback_utils import (
    needs_feedback_reminder,
    next_reminder_datetime,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.config import FeedbackConfig, load_config
from ugc_bot.domain.entities import Interaction, Order
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_session_factory,
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
                    text="✅ Всё прошло нормально",
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
                    text="⏳ Ещё не связался",
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
        return await interaction_repo.list_due_for_feedback(
            cutoff, session=session
        )

    interactions = await with_optional_tx(transaction_manager, _run)
    interactions_list = list(interactions)
    logger.debug(
        "Found interactions due for feedback",
        extra={"cutoff": cutoff.isoformat(), "count": len(interactions_list)},
    )
    return interactions_list


async def _send_feedback_requests(
    bot: Bot,
    interaction: Interaction,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    order: Optional[Order],
    feedback_config: FeedbackConfig,
) -> None:
    """Send feedback requests to both sides for a single interaction."""

    logger.debug(
        "Processing interaction for feedback",
        extra={
            "interaction_id": str(interaction.interaction_id),
            "order_id": str(interaction.order_id),
        },
    )
    blogger = await user_role_service.get_user_by_id(interaction.blogger_id)
    advertiser = await user_role_service.get_user_by_id(
        interaction.advertiser_id
    )
    if not blogger:
        logger.debug(
            "Skipping blogger feedback: user not found",
            extra={"blogger_id": str(interaction.blogger_id)},
        )
    if not advertiser:
        logger.debug(
            "Skipping advertiser feedback: user not found",
            extra={"advertiser_id": str(interaction.advertiser_id)},
        )
    blogger_profile = (
        await profile_service.get_blogger_profile(interaction.blogger_id)
        if profile_service
        else None
    )
    next_reminder = next_reminder_datetime(feedback_config)
    sent_to_adv = False
    sent_to_blog = False

    if (
        advertiser
        and needs_feedback_reminder(interaction.from_advertiser)
        and advertiser.external_id.isdigit()
    ):
        creator_link = ""
        if blogger_profile and blogger_profile.instagram_url:
            url = blogger_profile.instagram_url.strip()
            if url and not url.startswith("http"):
                url = "https://" + url
            creator_link = f" [{url}]({url})"
        text = (
            "Хотим убедиться, что всё прошло корректно 🙌\n"
            f"Удалось ли вам связаться с креатором{creator_link}?\n"
            "Выберите подходящий вариант:"
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
        logger.info(
            "Sent interaction feedback request to advertiser",
            extra={
                "interaction_id": str(interaction.interaction_id),
                "advertiser_id": str(advertiser.user_id),
            },
        )

    if (
        blogger
        and needs_feedback_reminder(interaction.from_blogger)
        and blogger.external_id.isdigit()
    ):
        order_link_part = "по заказу?"
        if order and order.product_link:
            url = order.product_link.strip()
            if url and not url.startswith("http"):
                url = "https://" + url
            order_link_part = f"[по заказу]({url})?"
        text = (
            "Мы хотим убедиться, что всё прошло корректно 🙌\n"
            f"Удалось ли вам связаться с заказчиком {order_link_part}"
        )
        await send_with_retry(
            bot,
            chat_id=int(blogger.external_id),
            text=text,
            parse_mode="Markdown",
            reply_markup=_feedback_keyboard("blog", interaction.interaction_id),
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"interaction_id": str(interaction.interaction_id)},
        )
        sent_to_blog = True
        logger.info(
            "Sent interaction feedback request to blogger",
            extra={
                "interaction_id": str(interaction.interaction_id),
                "blogger_id": str(interaction.blogger_id),
            },
        )

    if sent_to_adv or sent_to_blog:
        await interaction_service.schedule_next_reminder(
            interaction.interaction_id, next_reminder
        )
        logger.debug(
            "Scheduled next reminder for interaction",
            extra={
                "interaction_id": str(interaction.interaction_id),
                "next_reminder": next_reminder.isoformat()
                if next_reminder
                else None,
            },
        )


async def run_once(
    bot: Bot,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    order_repo,
    feedback_config: FeedbackConfig,
    cutoff: datetime,
    transaction_manager,
) -> None:
    """Run a single feedback dispatch cycle."""

    logger.debug(
        "Starting feedback dispatch cycle",
        extra={"cutoff": cutoff.isoformat()},
    )

    interactions = await _iter_due_interactions(
        interaction_repo, cutoff, transaction_manager
    )
    interaction_count = 0
    for interaction in interactions:
        interaction_count += 1
        try:
            async with transaction_manager.transaction() as session:
                order = await order_repo.get_by_id(
                    interaction.order_id, session=session
                )
            await _send_feedback_requests(
                bot,
                interaction,
                interaction_service,
                user_role_service,
                profile_service,
                order,
                feedback_config,
            )
        except (
            Exception
        ) as exc:  # pragma: no cover - depends on transport failures
            logger.warning(
                "Feedback request failed",
                extra={
                    "interaction_id": str(interaction.interaction_id),
                    "error": str(exc),
                },
            )
    logger.info(
        "Feedback cycle completed",
        extra={
            "interactions_processed": interaction_count,
            "cutoff": cutoff.isoformat(),
        },
    )


async def run_loop(
    bot: Bot,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    order_repo,
    feedback_config: FeedbackConfig,
    interval_seconds: int,
    transaction_manager,
    max_iterations: int | None = None,
) -> None:
    """Run periodic feedback dispatch."""

    iterations = 0
    logger.info("Feedback scheduler loop started")
    try:
        while True:
            iterations += 1
            cutoff = datetime.now(timezone.utc)
            logger.debug(
                "Feedback loop iteration", extra={"iteration": iterations}
            )
            await run_once(
                bot,
                interaction_repo,
                interaction_service,
                user_role_service,
                profile_service,
                order_repo,
                feedback_config,
                cutoff,
                transaction_manager,
            )
            if max_iterations is not None and iterations >= max_iterations:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info(
            "Feedback scheduler loop stopped",
            extra={"total_iterations": iterations},
        )
        session = getattr(bot, "session", None)
        if session is not None:
            await session.close()


def main() -> None:
    """Start feedback scheduler loop."""

    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    log_startup_info(
        logger=logger, service_name="Feedback scheduler", config=config
    )

    if not config.feedback.feedback_enabled:
        logger.info("Feedback scheduler disabled by config")
        return

    logger.info(
        "Initializing feedback scheduler",
        extra={
            "feedback_delay_minutes": config.feedback.feedback_delay_minutes,
            "poll_interval_seconds": (
                config.feedback.feedback_poll_interval_seconds
            ),
        },
    )
    session_factory = create_session_factory(
        config.db.database_url,
        pool_size=config.db.pool_size,
        max_overflow=config.db.max_overflow,
        pool_timeout=config.db.pool_timeout,
    )
    transaction_manager = SessionTransactionManager(session_factory)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    interaction_repo = SqlAlchemyInteractionRepository(
        session_factory=session_factory
    )
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(
        session_factory=session_factory
    )
    advertiser_repo = SqlAlchemyAdvertiserProfileRepository(
        session_factory=session_factory
    )

    user_role_service = UserRoleService(
        user_repo=user_repo, transaction_manager=transaction_manager
    )
    interaction_service = InteractionService(
        interaction_repo=interaction_repo,
        postpone_delay_minutes=config.feedback.feedback_delay_minutes,
        transaction_manager=transaction_manager,
        feedback_config=config.feedback,
    )
    profile_service = ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=advertiser_repo,
        transaction_manager=transaction_manager,
    )

    bot = Bot(token=config.bot.bot_token)
    asyncio.run(
        run_loop(
            bot,
            interaction_repo,
            interaction_service,
            user_role_service,
            profile_service,
            order_repo,
            config.feedback,
            interval_seconds=config.feedback.feedback_poll_interval_seconds,
            transaction_manager=transaction_manager,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main()
