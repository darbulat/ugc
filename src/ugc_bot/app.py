"""Application entrypoint.

Shared components (build_dispatcher, create_storage) are used by
telegram_webhook_app for webhook-based deployment. The bot runs via:
  uvicorn ugc_bot.telegram_webhook_app:app --host 0.0.0.0 --port 9999
"""

import logging

from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from ugc_bot.bot.handlers.admin_message_to_user import (
    router as admin_message_to_user_router,
)
from ugc_bot.bot.handlers.admin_moderation import (
    router as admin_moderation_router,
)
from ugc_bot.bot.handlers.advertiser_registration import (
    router as advertiser_router,
)
from ugc_bot.bot.handlers.blogger_registration import router as blogger_router
from ugc_bot.bot.handlers.complaints import router as complaints_router
from ugc_bot.bot.handlers.feedback import router as feedback_router
from ugc_bot.bot.handlers.instagram_verification import (
    router as instagram_router,
)
from ugc_bot.bot.handlers.my_orders import router as my_orders_router
from ugc_bot.bot.handlers.offer_responses import router as offer_response_router
from ugc_bot.bot.handlers.order_creation import router as order_router
from ugc_bot.bot.handlers.payments import router as payments_router
from ugc_bot.bot.handlers.profile import router as profile_router
from ugc_bot.bot.handlers.referral import router as referral_router
from ugc_bot.bot.handlers.survey_messenger import (
    router as survey_messenger_router,
)

# Services are built via Container.build_bot_services()
from ugc_bot.bot.handlers.start import router as start_router
from ugc_bot.bot.middleware.error_handler import ErrorHandlerMiddleware
from ugc_bot.bot.middleware.locale import LocaleMiddleware
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.fsm_json import fsm_json_dumps, fsm_json_loads


async def create_storage(config: AppConfig):
    """Create FSM storage based on configuration."""
    if config.redis.use_redis_storage:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import Redis

            redis = Redis.from_url(
                config.redis.redis_url, decode_responses=True
            )
            return RedisStorage(
                redis=redis,
                json_dumps=fsm_json_dumps,
                json_loads=fsm_json_loads,
            )
        except ImportError:
            logging.getLogger(__name__).warning(
                "Redis not available, falling back to MemoryStorage"
            )
            return MemoryStorage()
    return MemoryStorage()


def build_dispatcher(
    config: AppConfig,
    include_routers: bool = True,
    storage=None,
) -> Dispatcher:
    """Build the aiogram dispatcher.

    Args:
        config: Application configuration
        include_routers: Whether to include routers
        storage: FSM storage instance. If None, MemoryStorage will be used.
                 For production, use RedisStorage via create_storage().
    """

    if not config.db.database_url:
        raise ValueError("DATABASE_URL is required for repository setup.")

    if storage is None:
        storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    dispatcher["config"] = config

    container = Container(config)
    services = container.build_bot_services()
    dispatcher["container"] = container

    # Register error handling middleware for all updates
    error_handler = ErrorHandlerMiddleware(
        metrics_collector=services["metrics_collector"]
    )
    dispatcher.update.outer_middleware(error_handler)
    dispatcher.update.outer_middleware(LocaleMiddleware())

    # Register all services in dispatcher
    for key, service in services.items():
        dispatcher[key] = service
    if include_routers:
        dispatcher.include_router(
            payments_router
        )  # before start for /start pay_
        dispatcher.include_router(start_router)
        dispatcher.include_router(referral_router)
        dispatcher.include_router(admin_moderation_router)
        dispatcher.include_router(admin_message_to_user_router)
        dispatcher.include_router(blogger_router)
        dispatcher.include_router(advertiser_router)
        dispatcher.include_router(profile_router)
        dispatcher.include_router(instagram_router)
        dispatcher.include_router(my_orders_router)
        dispatcher.include_router(order_router)
        dispatcher.include_router(feedback_router)
        dispatcher.include_router(offer_response_router)
        dispatcher.include_router(complaints_router)
        dispatcher.include_router(survey_messenger_router)
    return dispatcher
