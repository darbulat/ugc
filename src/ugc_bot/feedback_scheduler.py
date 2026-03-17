"""Scheduler for feedback requests after contacts sharing."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from aiogram import Bot

from ugc_bot.application.feedback_utils import (
    needs_feedback_reminder,
    next_reminder_datetime,
)
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.config import FeedbackConfig, load_config
from ugc_bot.container import Container
from ugc_bot.domain.entities import BloggerProfile, Interaction, Order, User
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.db.session import with_optional_tx
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)
_send_retries = 3
_send_retry_delay_seconds = 0.5


def _feedback_keyboard(
    kind: str, interaction_id: UUID, texts: dict[str, str]
) -> Keyboard:
    """Build feedback buttons from localized texts."""
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=texts.get(
                        "msg_fb_feedback_ok", "✅ Всё прошло нормально"
                    ),
                    callback_data=f"feedback:{kind}:{interaction_id}:ok",
                )
            ],
            [
                Button(
                    text=texts.get(
                        "msg_fb_feedback_no_deal", "❌ Не договорились"
                    ),
                    callback_data=f"feedback:{kind}:{interaction_id}:no_deal",
                )
            ],
            [
                Button(
                    text=texts.get(
                        "msg_fb_feedback_postpone", "⏳ Ещё не связался"
                    ),
                    callback_data=f"feedback:{kind}:{interaction_id}:postpone",
                )
            ],
            [
                Button(
                    text=texts.get(
                        "msg_fb_feedback_issue",
                        "⚠️ Проблема / подозрение на мошенничество",
                    ),
                    callback_data=f"feedback:{kind}:{interaction_id}:issue",
                )
            ],
        ],
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


async def _send_advertiser_feedback(
    messenger_client: MessengerClient,
    interaction: Interaction,
    advertiser: User,
    blogger_profile: Optional[BloggerProfile],
    texts: dict[str, str],
) -> bool:
    """Send feedback request to advertiser. Return True if sent."""
    creator_link = ""
    if blogger_profile and blogger_profile.instagram_url:
        url = blogger_profile.instagram_url.strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        creator_link = f" [{url}]({url})"
    template = texts.get(
        "msg_feedback_request_adv",
        "Хотим убедиться, что всё прошло корректно 🙌\n"
        "Удалось ли вам связаться с креатором{creator_link}?\n"
        "Выберите подходящий вариант:",
    )
    text = template.format(creator_link=creator_link)
    await send_with_retry(
        messenger_client,
        chat_id=advertiser.external_id,
        text=text,
        parse_mode="Markdown",
        keyboard=_feedback_keyboard("adv", interaction.interaction_id, texts),
        retries=_send_retries,
        delay_seconds=_send_retry_delay_seconds,
        logger=logger,
        extra={"interaction_id": str(interaction.interaction_id)},
    )
    logger.info(
        "Sent interaction feedback request to advertiser",
        extra={
            "interaction_id": str(interaction.interaction_id),
            "advertiser_id": str(advertiser.user_id),
        },
    )
    return True


async def _send_blogger_feedback(
    messenger_client: MessengerClient,
    interaction: Interaction,
    blogger: User,
    order: Optional[Order],
    texts: dict[str, str],
) -> bool:
    """Send feedback request to blogger. Return True if sent."""
    order_link_part = "по заказу?"
    if order and order.product_link:
        url = order.product_link.strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        order_link_part = f"[по заказу]({url})?"
    template = texts.get(
        "msg_feedback_request_blog",
        "Мы хотим убедиться, что всё прошло корректно 🙌\n"
        "Удалось ли вам связаться с заказчиком {order_link_part}",
    )
    text = template.format(order_link_part=order_link_part)
    await send_with_retry(
        messenger_client,
        chat_id=blogger.external_id,
        text=text,
        parse_mode="Markdown",
        keyboard=_feedback_keyboard("blog", interaction.interaction_id, texts),
        retries=_send_retries,
        delay_seconds=_send_retry_delay_seconds,
        logger=logger,
        extra={"interaction_id": str(interaction.interaction_id)},
    )
    logger.info(
        "Sent interaction feedback request to blogger",
        extra={
            "interaction_id": str(interaction.interaction_id),
            "blogger_id": str(interaction.blogger_id),
        },
    )
    return True


def _feedback_texts_for_locale(locale: str) -> dict[str, str]:
    """Get feedback button and request texts for locale from defaults."""
    locale_map = DEFAULT_TEXTS.get(locale) or DEFAULT_TEXTS.get("ru") or {}
    keys = [
        "msg_fb_feedback_ok",
        "msg_fb_feedback_no_deal",
        "msg_fb_feedback_postpone",
        "msg_fb_feedback_issue",
        "msg_feedback_request_adv",
        "msg_feedback_request_blog",
    ]
    return {k: locale_map.get(k, "") for k in keys}


_FEEDBACK_TEXT_KEYS = [
    "msg_fb_feedback_ok",
    "msg_fb_feedback_no_deal",
    "msg_fb_feedback_postpone",
    "msg_fb_feedback_issue",
    "msg_feedback_request_adv",
    "msg_feedback_request_blog",
]


async def _send_feedback_requests(
    messenger_client: MessengerClient,
    interaction: Interaction,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    order: Optional[Order],
    feedback_config: FeedbackConfig,
    locale: str,
    bot_texts_service: BotTextsService | None = None,
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
    if not blogger and not advertiser:
        return
    blogger_profile = (
        await profile_service.get_blogger_profile(interaction.blogger_id)
        if profile_service
        else None
    )
    next_reminder = next_reminder_datetime(
        feedback_config.feedback_reminder_timezone,
        feedback_config.feedback_reminder_hour,
        feedback_config.feedback_reminder_minute,
    )
    sent_to_adv = False
    sent_to_blog = False

    if (
        advertiser
        and needs_feedback_reminder(interaction.from_advertiser)
        and advertiser.external_id.isdigit()
    ):
        adv_locale = getattr(advertiser, "language", None) or locale
        if bot_texts_service is not None:
            adv_texts = await bot_texts_service.get_many(
                _FEEDBACK_TEXT_KEYS, adv_locale
            )
        else:
            adv_texts = _feedback_texts_for_locale(adv_locale)
        sent_to_adv = await _send_advertiser_feedback(
            messenger_client,
            interaction,
            advertiser,
            blogger_profile,
            adv_texts,
        )

    if (
        blogger
        and needs_feedback_reminder(interaction.from_blogger)
        and blogger.external_id.isdigit()
    ):
        blog_locale = getattr(blogger, "language", None) or locale
        if bot_texts_service is not None:
            blog_texts = await bot_texts_service.get_many(
                _FEEDBACK_TEXT_KEYS, blog_locale
            )
        else:
            blog_texts = _feedback_texts_for_locale(blog_locale)
        sent_to_blog = await _send_blogger_feedback(
            messenger_client, interaction, blogger, order, blog_texts
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
    messenger_client: MessengerClient,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    order_repo,
    feedback_config: FeedbackConfig,
    cutoff: datetime,
    transaction_manager,
    locale: str = "ru",
    bot_texts_service: BotTextsService | None = None,
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
                messenger_client,
                interaction,
                interaction_service,
                user_role_service,
                profile_service,
                order,
                feedback_config,
                locale,
                bot_texts_service=bot_texts_service,
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
    messenger_client: MessengerClient,
    interaction_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    profile_service: Optional[ProfileService],
    order_repo,
    feedback_config: FeedbackConfig,
    interval_seconds: int,
    transaction_manager,
    default_locale: str = "ru",
    max_iterations: int | None = None,
    bot_texts_service: BotTextsService | None = None,
) -> None:
    """Run periodic feedback dispatch."""
    install_asyncio_exception_handler("feedback-scheduler")

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
                messenger_client,
                interaction_repo,
                interaction_service,
                user_role_service,
                profile_service,
                order_repo,
                feedback_config,
                cutoff,
                transaction_manager,
                locale=default_locale,
                bot_texts_service=bot_texts_service,
            )
            if max_iterations is not None and iterations >= max_iterations:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info(
            "Feedback scheduler loop stopped",
            extra={"total_iterations": iterations},
        )
        close_method = getattr(messenger_client, "close", None)
        if callable(close_method):
            await close_method()
        else:
            session = getattr(messenger_client, "session", None)
            if session is not None and hasattr(session, "close"):
                await session.close()


def main() -> None:
    """Start feedback scheduler loop."""

    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("feedback-scheduler")
    log_startup_info(
        logger=logger, service_name="Feedback scheduler", config=config
    )

    if not config.feedback.feedback_enabled:
        logger.info("Feedback scheduler disabled by config")
        return

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for feedback scheduler")
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
    container = Container(config)
    deps = container.build_feedback_scheduler_deps()
    bot_texts_service = container.build_bot_texts_service()

    bot = Bot(token=config.bot.bot_token)
    messenger_client = TelegramMessengerClient(bot)
    default_locale = (
        getattr(getattr(config, "market", None), "default_locale", "ru") or "ru"
    )
    try:
        asyncio.run(
            run_loop(
                messenger_client,
                deps["interaction_repo"],
                deps["interaction_service"],
                deps["user_role_service"],
                deps["profile_service"],
                deps["order_repo"],
                config.feedback,
                interval_seconds=config.feedback.feedback_poll_interval_seconds,
                transaction_manager=deps["transaction_manager"],
                default_locale=default_locale,
                bot_texts_service=bot_texts_service,
            )
        )
    finally:
        session = getattr(bot, "session", None)
        if session is not None:
            asyncio.run(session.close())
        asyncio.run(container.dispose())


if __name__ == "__main__":  # pragma: no cover
    main()
