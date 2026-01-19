"""Scheduler for feedback requests after contacts sharing."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Iterable
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import load_config
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyInteractionRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderResponseRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.logging_setup import configure_logging


logger = logging.getLogger(__name__)


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
                    text="⚠️ Проблема / мошенничество",
                    callback_data=f"feedback:{kind}:{interaction_id}:issue",
                )
            ],
        ]
    )


def _iter_due_orders(order_repo, cutoff: datetime) -> Iterable[Order]:
    """List orders eligible for feedback."""

    return [
        order
        for order in order_repo.list_with_contacts_before(cutoff)
        if order.status == OrderStatus.CLOSED
    ]


async def _send_feedback_requests(
    bot: Bot,
    order: Order,
    responses,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
) -> None:
    """Send feedback requests to both sides."""

    for response in responses:
        interaction = interaction_service.get_or_create(
            order_id=order.order_id,
            blogger_id=response.blogger_id,
            advertiser_id=order.advertiser_id,
        )

        blogger = user_role_service.get_user_by_id(response.blogger_id)
        advertiser = user_role_service.get_user_by_id(order.advertiser_id)

        if advertiser and interaction.from_advertiser is None:
            if advertiser.external_id.isdigit():
                blogger_handle = (
                    f"@{blogger.username}" if blogger and blogger.username else "блогер"
                )
                await bot.send_message(
                    chat_id=int(advertiser.external_id),
                    text=(
                        f"Вы связывались с блогером {blogger_handle} "
                        f"по заказу #{order.order_id}?"
                    ),
                    reply_markup=_feedback_keyboard("adv", interaction.interaction_id),
                )

        if blogger and interaction.from_blogger is None:
            if blogger.external_id.isdigit():
                advertiser_handle = (
                    f"@{advertiser.username}"
                    if advertiser and advertiser.username
                    else "рекламодатель"
                )
                await bot.send_message(
                    chat_id=int(blogger.external_id),
                    text=(
                        f"Вы связывались с рекламодателем {advertiser_handle} "
                        f"по офферу #{order.order_id}?"
                    ),
                    reply_markup=_feedback_keyboard("blog", interaction.interaction_id),
                )

        if interaction.from_advertiser and interaction.from_blogger:
            pass


async def run_once(
    bot: Bot,
    order_repo,
    response_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    cutoff: datetime,
) -> None:
    """Run a single feedback dispatch cycle."""

    for order in _iter_due_orders(order_repo, cutoff):
        responses = response_repo.list_by_order(order.order_id)
        if not responses:
            continue
        await _send_feedback_requests(
            bot,
            order,
            responses,
            interaction_service,
            user_role_service,
        )


async def run_loop(
    bot: Bot,
    order_repo,
    response_repo,
    interaction_service: InteractionService,
    user_role_service: UserRoleService,
    delay_hours: int,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Run periodic feedback dispatch."""

    iterations = 0
    try:
        while True:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=delay_hours)
            await run_once(
                bot,
                order_repo,
                response_repo,
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
    configure_logging(config.log_level)
    if not config.feedback_enabled:
        logger.info("Feedback scheduler disabled by config")
        return

    session_factory = create_session_factory(config.database_url)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    response_repo = SqlAlchemyOrderResponseRepository(session_factory=session_factory)
    interaction_repo = SqlAlchemyInteractionRepository(session_factory=session_factory)

    user_role_service = UserRoleService(user_repo=user_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    bot = Bot(token=config.bot_token)
    asyncio.run(
        run_loop(
            bot,
            order_repo,
            response_repo,
            interaction_service,
            user_role_service,
            delay_hours=config.feedback_delay_hours,
            interval_seconds=config.feedback_poll_interval_seconds,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main()
