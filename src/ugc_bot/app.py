"""Application entrypoint."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

# Services are built via Container.build_bot_services()
from ugc_bot.bot.handlers.cancel import router as cancel_router
from ugc_bot.bot.handlers.start import router as start_router
from ugc_bot.bot.handlers.advertiser_registration import (
    router as advertiser_router,
)
from ugc_bot.bot.handlers.blogger_registration import router as blogger_router
from ugc_bot.bot.handlers.instagram_verification import (
    router as instagram_router,
)
from ugc_bot.bot.handlers.my_orders import router as my_orders_router
from ugc_bot.bot.handlers.profile import router as profile_router
from ugc_bot.bot.handlers.offer_responses import router as offer_response_router
from ugc_bot.bot.handlers.order_creation import router as order_router
from ugc_bot.bot.handlers.payments import router as payments_router
from ugc_bot.bot.handlers.feedback import router as feedback_router
from ugc_bot.bot.handlers.complaints import router as complaints_router
from ugc_bot.bot.middleware.error_handler import ErrorHandlerMiddleware
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info


def _json_dumps(obj: dict) -> str:
    """Custom JSON dumps that handles UUID and other non-serializable types."""
    import json
    from datetime import datetime
    from uuid import UUID

    class UUIDEncoder(json.JSONEncoder):
        """JSON encoder that handles UUID and datetime objects."""

        def default(self, obj):  # type: ignore[no-untyped-def]
            if isinstance(obj, UUID):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            return super().default(obj)

    return json.dumps(obj, cls=UUIDEncoder)


def _json_loads(data: str) -> dict:
    """Custom JSON loads for FSM data."""
    import json

    return json.loads(data)


async def create_storage(config: AppConfig):
    """Create FSM storage based on configuration."""
    if config.redis.use_redis_storage:
        try:
            from redis.asyncio import Redis

            redis = Redis.from_url(config.redis.redis_url, decode_responses=True)
            return RedisStorage(
                redis=redis,
                json_dumps=_json_dumps,
                json_loads=_json_loads,
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

    # Register error handling middleware for all updates
    error_handler = ErrorHandlerMiddleware(
        metrics_collector=services["metrics_collector"]
    )
    dispatcher.update.outer_middleware(error_handler)

    # Register all services in dispatcher
    for key, service in services.items():
        dispatcher[key] = service
    if include_routers:
        dispatcher.include_router(cancel_router)
        dispatcher.include_router(start_router)
        dispatcher.include_router(blogger_router)
        dispatcher.include_router(advertiser_router)
        dispatcher.include_router(instagram_router)
        dispatcher.include_router(my_orders_router)
        dispatcher.include_router(profile_router)
        dispatcher.include_router(feedback_router)
        dispatcher.include_router(offer_response_router)
        dispatcher.include_router(order_router)
        dispatcher.include_router(payments_router)
        dispatcher.include_router(complaints_router)
    return dispatcher


async def run_bot() -> None:
    """Run the Telegram bot."""

    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )

    log_startup_info(
        logger=logging.getLogger(__name__), service_name="ugc-bot", config=config
    )
    storage = await create_storage(config)
    dispatcher = build_dispatcher(config, storage=storage)
    bot = Bot(token=config.bot.bot_token)
    try:
        await dispatcher.start_polling(bot)
    finally:
        if hasattr(storage, "close"):
            await storage.close()


def main() -> None:
    """Entry point for the CLI."""

    asyncio.run(run_bot())


if __name__ == "__main__":  # pragma: no cover
    main()
