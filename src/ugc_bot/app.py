"""Application entrypoint."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import ContactPricingService
from ugc_bot.application.services.user_role_service import UserRoleService
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
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.repositories import NoopOfferBroadcaster
from ugc_bot.logging_setup import configure_logging
from ugc_bot.metrics.collector import MetricsCollector


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

    c = Container(config)
    repos = c.build_repos()
    metrics_collector = MetricsCollector()
    dispatcher["metrics_collector"] = metrics_collector
    dispatcher["user_role_service"] = UserRoleService(
        user_repo=repos["user_repo"],
        metrics_collector=metrics_collector,
    )
    dispatcher["blogger_registration_service"] = BloggerRegistrationService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        metrics_collector=metrics_collector,
    )
    dispatcher["advertiser_registration_service"] = AdvertiserRegistrationService(
        user_repo=repos["user_repo"],
        advertiser_repo=repos["advertiser_repo"],
        metrics_collector=metrics_collector,
    )
    # Create Instagram Graph API client if access token is configured
    instagram_api_client = None
    if config.instagram.instagram_access_token:
        from ugc_bot.infrastructure.instagram.graph_api_client import (
            HttpInstagramGraphApiClient,
        )

        instagram_api_client = HttpInstagramGraphApiClient(
            access_token=config.instagram.instagram_access_token,
            base_url=config.instagram.instagram_api_base_url,
        )

    dispatcher["instagram_verification_service"] = InstagramVerificationService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        verification_repo=repos["instagram_repo"],
        instagram_api_client=instagram_api_client,
    )
    dispatcher["order_service"] = OrderService(
        user_repo=repos["user_repo"],
        advertiser_repo=repos["advertiser_repo"],
        order_repo=repos["order_repo"],
        metrics_collector=metrics_collector,
    )
    dispatcher["offer_dispatch_service"] = OfferDispatchService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        order_repo=repos["order_repo"],
    )
    dispatcher["offer_response_service"] = OfferResponseService(
        order_repo=repos["order_repo"],
        response_repo=repos["order_response_repo"],
        metrics_collector=metrics_collector,
    )
    dispatcher["interaction_service"] = InteractionService(
        interaction_repo=repos["interaction_repo"],
        metrics_collector=metrics_collector,
    )
    outbox_publisher = OutboxPublisher(
        outbox_repo=repos["outbox_repo"], order_repo=repos["order_repo"]
    )

    dispatcher["payment_service"] = PaymentService(
        user_repo=repos["user_repo"],
        advertiser_repo=repos["advertiser_repo"],
        order_repo=repos["order_repo"],
        payment_repo=repos["payment_repo"],
        broadcaster=NoopOfferBroadcaster(),
        outbox_publisher=outbox_publisher,
        metrics_collector=metrics_collector,
        transaction_manager=c.transaction_manager,
    )
    dispatcher["contact_pricing_service"] = ContactPricingService(
        pricing_repo=repos["pricing_repo"]
    )
    dispatcher["profile_service"] = ProfileService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        advertiser_repo=repos["advertiser_repo"],
    )
    dispatcher["complaint_service"] = ComplaintService(
        complaint_repo=repos["complaint_repo"],
        metrics_collector=metrics_collector,
    )
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

    logging.getLogger(__name__).info("Starting UGC bot")
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
