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
from ugc_bot.application.ports import BloggerRelevanceSelector
from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.application.services.offer_response_service import OfferResponseService
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
from ugc_bot.bot.handlers.offer_responses import router as offer_response_router
from ugc_bot.bot.handlers.order_creation import router as order_router
from ugc_bot.bot.handlers.payments import router as payments_router
from ugc_bot.config import AppConfig, load_config
from ugc_bot.logging_setup import configure_logging
from ugc_bot.infrastructure.db.repositories import (
    NoopOfferBroadcaster,
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderResponseRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.llm.local_relevance_selector import (
    LocalBloggerRelevanceSelector,
)
from ugc_bot.infrastructure.llm.openai_relevance_selector import (
    OpenAIBloggerRelevanceSelector,
)


def build_dispatcher(
    config: AppConfig,
) -> Dispatcher:
    """Build the aiogram dispatcher."""

    if not config.database_url:
        raise ValueError("DATABASE_URL is required for repository setup.")
    if config.openai_enabled and not config.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for blogger matching.")

    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    session_factory = create_session_factory(config.database_url)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(session_factory=session_factory)
    advertiser_repo = SqlAlchemyAdvertiserProfileRepository(
        session_factory=session_factory
    )
    instagram_repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=session_factory
    )
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    order_response_repo = SqlAlchemyOrderResponseRepository(
        session_factory=session_factory
    )
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
    relevance_selector: BloggerRelevanceSelector
    if config.openai_enabled:
        relevance_selector = OpenAIBloggerRelevanceSelector(
            api_key=config.openai_api_key,
            model=config.openai_model,
        )
    else:
        relevance_selector = LocalBloggerRelevanceSelector()

    dispatcher["offer_dispatch_service"] = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        relevance_selector=relevance_selector,
    )
    dispatcher["offer_response_service"] = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
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
    dispatcher.include_router(offer_response_router)
    dispatcher.include_router(order_router)
    dispatcher.include_router(payments_router)
    return dispatcher


async def run_bot() -> None:
    """Run the Telegram bot."""

    config = load_config()
    configure_logging(config.log_level)

    logging.getLogger(__name__).info("Starting UGC bot")
    dispatcher = build_dispatcher(config)
    bot = Bot(token=config.bot_token)
    await dispatcher.start_polling(bot)


def main() -> None:
    """Entry point for the CLI."""

    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
