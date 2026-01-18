"""Application entrypoint."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import router as start_router
from ugc_bot.bot.handlers.advertiser_registration import (
    router as advertiser_router,
)
from ugc_bot.bot.handlers.blogger_registration import router as blogger_router
from ugc_bot.bot.handlers.instagram_verification import (
    router as instagram_router,
)
from ugc_bot.bot.handlers.order_creation import router as order_router
from ugc_bot.bot.handlers.payments import router as payments_router
from ugc_bot.config import load_config
from ugc_bot.logging_setup import configure_logging
from ugc_bot.infrastructure.db.repositories import (
    NoopOfferBroadcaster,
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory


def build_dispatcher(database_url: str) -> Dispatcher:
    """Build the aiogram dispatcher."""

    if not database_url:
        raise ValueError("DATABASE_URL is required for repository setup.")

    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    session_factory = create_session_factory(database_url)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(session_factory=session_factory)
    advertiser_repo = SqlAlchemyAdvertiserProfileRepository(
        session_factory=session_factory
    )
    instagram_repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=session_factory
    )
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    payment_repo = SqlAlchemyPaymentRepository(session_factory=session_factory)
    dispatcher["user_role_service"] = UserRoleService(user_repo=user_repo)
    dispatcher["blogger_registration_service"] = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
    )
    dispatcher["advertiser_registration_service"] = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
    )
    dispatcher["instagram_verification_service"] = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_repo,
    )
    dispatcher["order_service"] = OrderService(
        user_repo=user_repo,
        order_repo=order_repo,
    )
    dispatcher["payment_service"] = PaymentService(
        user_repo=user_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
    )
    dispatcher.include_router(start_router)
    dispatcher.include_router(blogger_router)
    dispatcher.include_router(advertiser_router)
    dispatcher.include_router(instagram_router)
    dispatcher.include_router(order_router)
    dispatcher.include_router(payments_router)
    return dispatcher


async def run_bot() -> None:
    """Run the Telegram bot."""

    config = load_config()
    configure_logging(config.log_level)

    logging.getLogger(__name__).info("Starting UGC bot")
    dispatcher = build_dispatcher(config.database_url)
    bot = Bot(token=config.bot_token)
    await dispatcher.start_polling(bot)


def main() -> None:
    """Entry point for the CLI."""

    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
