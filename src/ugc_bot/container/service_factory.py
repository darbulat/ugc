"""Factory for creating application services."""

from pathlib import Path
from typing import Any

from ugc_bot.application.cache_ports import CachePort
from ugc_bot.application.ports import GeocoderPort
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.geocoder import NominatimGeocoder
from ugc_bot.application.services.geocoder_cache import CachingGeocoder
from ugc_bot.application.services.geocoder_dadata import DadataGeocoder
from ugc_bot.application.services.geocoder_rate_limit_store import (
    RedisGeocoderRateLimitStore,
)
from ugc_bot.application.services.geocoder_rate_limiter import (
    RateLimitedGeocoder,
)
from ugc_bot.application.services.instagram_stats_collector_service import (
    InstagramStatsCollectorService,
)
from ugc_bot.application.services.instagram_stats_update_service import (
    InstagramStatsUpdateService,
)
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig
from ugc_bot.container.types import BotServices
from ugc_bot.infrastructure.geocoder_cache_memory import GeocoderCacheMemory
from ugc_bot.infrastructure.geocoder_cache_redis import (
    DEFAULT_PREFIX as GEOCODER_CACHE_KEY_PREFIX,
)
from ugc_bot.infrastructure.geocoder_cache_redis import (
    GeocoderCacheRedis,
)
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher


def build_geocoder(config: AppConfig) -> GeocoderPort:
    """Build geocoder implementation from AppConfig (with optional cache)."""
    cfg = config.geocoder
    bare: GeocoderPort
    if cfg.provider == "dadata":
        bare = DadataGeocoder(
            base_url=cfg.dadata_base_url,
            api_key=cfg.dadata_api_key,
            secret=cfg.dadata_secret,
            timeout_seconds=cfg.dadata_timeout_seconds,
            enabled=cfg.dadata_enabled,
        )
    else:
        nominatim = NominatimGeocoder(
            base_url=cfg.nominatim_base_url,
            user_agent=cfg.nominatim_user_agent,
            timeout_seconds=cfg.nominatim_timeout_seconds,
            enabled=cfg.nominatim_enabled,
        )
        rate_limit_store = None
        if config.redis.redis_url:
            rate_limit_store = RedisGeocoderRateLimitStore(
                redis_url=config.redis.redis_url,
                delay_seconds=cfg.nominatim_delay_seconds,
            )
        bare = RateLimitedGeocoder(
            delegate=nominatim,
            delay_seconds=cfg.nominatim_delay_seconds,
            store=rate_limit_store,
        )
    if not cfg.cache_enabled:
        return bare
    cache_backend: CachePort
    if cfg.cache_backend == "redis" and config.redis.redis_url:
        cache_backend = GeocoderCacheRedis(
            redis_url=config.redis.redis_url,
            key_prefix=GEOCODER_CACHE_KEY_PREFIX,
        )
    else:
        cache_backend = GeocoderCacheMemory(
            max_entries=cfg.cache_memory_max_entries,
        )
    return CachingGeocoder(
        delegate=bare,
        cache=cache_backend,
        ttl_seconds=cfg.cache_ttl_seconds,
        cache_negative=True,
    )


def build_offer_dispatch_service(repos, transaction_manager):
    """Build OfferDispatchService for Kafka consumer."""
    return OfferDispatchService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        order_repo=repos["order_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        interaction_repo=repos["interaction_repo"],
        instagram_stats_repo=repos.get("instagram_stats_repo"),
        transaction_manager=transaction_manager,
    )


def build_referral_income_service(repos, transaction_manager):
    """Build ReferralIncomeService for admin dashboard balance calculation."""
    return ReferralIncomeService(
        user_referral_binding_repo=repos["user_referral_binding_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        order_repo=repos["order_repo"],
        payment_repo=repos["payment_repo"],
        interaction_repo=repos["interaction_repo"],
        user_repo=repos["user_repo"],
        payout_request_repo=repos["payout_request_repo"],
        transaction_manager=transaction_manager,
        referral_order_income_loader=repos.get("referral_order_income_loader"),
    )


def build_admin_services(config: AppConfig, repos):
    """Build UserRoleService, ComplaintService, InteractionService for admin."""
    return (
        UserRoleService(user_repo=repos["user_repo"]),
        ComplaintService(complaint_repo=repos["complaint_repo"]),
        InteractionService(
            interaction_repo=repos["interaction_repo"],
            postpone_delay_minutes=config.feedback.feedback_delay_minutes,
            feedback_config=config.feedback,
        ),
    )


def build_outbox_deps(config: AppConfig, repos, transaction_manager):
    """Build OutboxPublisher and optional KafkaOrderActivationPublisher."""
    outbox_publisher = OutboxPublisher(
        outbox_repo=repos["outbox_repo"],
        order_repo=repos["order_repo"],
        transaction_manager=transaction_manager,
    )
    kafka_publisher = None
    if config.kafka.kafka_enabled:
        kafka_publisher = KafkaOrderActivationPublisher(
            bootstrap_servers=config.kafka.kafka_bootstrap_servers,
            topic=config.kafka.kafka_topic,
        )
    return (outbox_publisher, kafka_publisher)


def build_feedback_scheduler_deps(
    config: AppConfig, repos, transaction_manager
):
    """Build deps for feedback scheduler: services and repos."""
    return {
        "interaction_repo": repos["interaction_repo"],
        "order_repo": repos["order_repo"],
        "transaction_manager": transaction_manager,
        "interaction_service": InteractionService(
            interaction_repo=repos["interaction_repo"],
            postpone_delay_minutes=config.feedback.feedback_delay_minutes,
            transaction_manager=transaction_manager,
            feedback_config=config.feedback,
        ),
        "user_role_service": UserRoleService(
            user_repo=repos["user_repo"],
            transaction_manager=transaction_manager,
        ),
        "profile_service": ProfileService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            advertiser_repo=repos["advertiser_repo"],
            transaction_manager=transaction_manager,
        ),
    }


def build_instagram_verification_service(
    repos, instagram_api_client, transaction_manager
):
    """Build InstagramVerificationService for webhook."""
    return InstagramVerificationService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        verification_repo=repos["instagram_repo"],
        instagram_api_client=instagram_api_client,
        transaction_manager=transaction_manager,
    )


def build_instagram_stats_scheduler_deps(
    config: AppConfig, repos, transaction_manager, instagram_api_client
):
    """Build deps for Instagram stats update scheduler."""
    ig_config = config.instagram
    return {
        "instagram_stats_update_service": InstagramStatsUpdateService(
            blogger_repo=repos["blogger_repo"],
            instagram_api_client=instagram_api_client,
            transaction_manager=transaction_manager,
            batch_size=ig_config.instagram_stats_batch_size,
            delay_seconds=ig_config.instagram_stats_delay_seconds,
        ),
        "interval_seconds": ig_config.instagram_stats_update_interval_seconds,
    }


def _build_aiograpi_fetcher(config: AppConfig):
    """Build AiograpiStatsFetcher when config and aiograpi are available."""
    ig = config.instagram
    username = (ig.instagram_stats_aiograpi_username or "").strip()
    password = (ig.instagram_stats_aiograpi_password or "").strip()
    if not username or not password:
        return None
    try:
        from ugc_bot.infrastructure.instagram.aiograpi_stats_fetcher import (
            AiograpiStatsFetcher,
        )

        session_path = (ig.instagram_stats_aiograpi_session_path or "").strip()
        return AiograpiStatsFetcher(
            instagram_username=username,
            instagram_password=password,
            session_path=Path(session_path) if session_path else None,
        )
    except ImportError:
        return None


def build_instagram_stats_collector_scheduler_deps(
    config: AppConfig,
    repos,
    transaction_manager,
    stats_provider_client,
):
    """Build deps for Instagram stats collector scheduler."""
    ig_config = config.instagram
    aiograpi_fetcher = _build_aiograpi_fetcher(config)
    return {
        "instagram_stats_collector_service": (
            InstagramStatsCollectorService(
                blogger_repo=repos["blogger_repo"],
                instagram_stats_repo=repos["instagram_stats_repo"],
                stats_provider_client=stats_provider_client,
                transaction_manager=transaction_manager,
                batch_size=ig_config.instagram_stats_collector_batch_size,
                delay_seconds=ig_config.instagram_stats_collector_delay_seconds,
                stats_update_interval_seconds=(
                    ig_config.instagram_stats_collector_interval_seconds
                ),
                aiograpi_fetcher=aiograpi_fetcher,
            )
        ),
        "interval_seconds": (
            ig_config.instagram_stats_collector_interval_seconds
        ),
    }


def build_bot_services(
    config: AppConfig,
    repos: dict[str, Any],
    transaction_manager: Any,
    metrics_collector: Any,
    instagram_api_client: Any,
    outbox_publisher: OutboxPublisher,
    issue_lock_manager: Any,
    offer_response_rate_limiter: Any,
) -> BotServices:
    """Build all services and repos for the bot dispatcher."""
    referral_service = ReferralService(
        user_repo=repos["user_repo"],
        user_referral_pending_repo=repos["user_referral_pending_repo"],
        user_referral_binding_repo=repos["user_referral_binding_repo"],
        transaction_manager=transaction_manager,
    )
    geocoder = build_geocoder(config)
    return {
        "metrics_collector": metrics_collector,
        "content_moderation_service": ContentModerationService(),
        "user_role_service": UserRoleService(
            user_repo=repos["user_repo"],
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "blogger_registration_service": BloggerRegistrationService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            referral_service=referral_service,
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
            geocoder=geocoder,
            country_repo=repos.get("country_repo"),
        ),
        "advertiser_registration_service": AdvertiserRegistrationService(
            user_repo=repos["user_repo"],
            advertiser_repo=repos["advertiser_repo"],
            referral_service=referral_service,
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "instagram_verification_service": InstagramVerificationService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            verification_repo=repos["instagram_repo"],
            instagram_api_client=instagram_api_client,
            transaction_manager=transaction_manager,
        ),
        "order_service": OrderService(
            user_repo=repos["user_repo"],
            advertiser_repo=repos["advertiser_repo"],
            order_repo=repos["order_repo"],
            allowed_blogger_counts=config.order.get_allowed_blogger_counts_set(),
            max_order_price=config.order.max_order_price,
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
            geocoder=geocoder,
            country_repo=repos.get("country_repo"),
        ),
        "offer_dispatch_service": OfferDispatchService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            order_repo=repos["order_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            interaction_repo=repos["interaction_repo"],
            transaction_manager=transaction_manager,
            currency_symbol=config.market.currency_symbol,
        ),
        "offer_response_service": OfferResponseService(
            order_repo=repos["order_repo"],
            dispatch_repo=repos["offer_dispatch_repo"],
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "interaction_service": InteractionService(
            interaction_repo=repos["interaction_repo"],
            postpone_delay_minutes=config.feedback.feedback_delay_minutes,
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
            feedback_config=config.feedback,
        ),
        "payment_service": PaymentService(
            user_repo=repos["user_repo"],
            advertiser_repo=repos["advertiser_repo"],
            order_repo=repos["order_repo"],
            payment_repo=repos["payment_repo"],
            pricing_repo=repos["pricing_repo"],
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "contact_pricing_service": ContactPricingService(
            pricing_repo=repos["pricing_repo"],
            transaction_manager=transaction_manager,
        ),
        "profile_service": ProfileService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            advertiser_repo=repos["advertiser_repo"],
            transaction_manager=transaction_manager,
        ),
        "complaint_service": ComplaintService(
            complaint_repo=repos["complaint_repo"],
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "nps_service": NpsService(
            nps_repo=repos["nps_repo"],
            transaction_manager=transaction_manager,
        ),
        "referral_service": ReferralService(
            user_repo=repos["user_repo"],
            user_referral_pending_repo=repos["user_referral_pending_repo"],
            user_referral_binding_repo=repos["user_referral_binding_repo"],
            transaction_manager=transaction_manager,
        ),
        "referral_income_service": ReferralIncomeService(
            user_referral_binding_repo=repos["user_referral_binding_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            order_repo=repos["order_repo"],
            payment_repo=repos["payment_repo"],
            interaction_repo=repos["interaction_repo"],
            user_repo=repos["user_repo"],
            payout_request_repo=repos["payout_request_repo"],
            transaction_manager=transaction_manager,
            referral_order_income_loader=repos.get(
                "referral_order_income_loader"
            ),
        ),
        "issue_lock_manager": issue_lock_manager,
        "offer_response_rate_limiter": offer_response_rate_limiter,
        "order_repo": repos["order_repo"],
        "offer_dispatch_repo": repos["offer_dispatch_repo"],
        "interaction_repo": repos["interaction_repo"],
        "user_repo": repos["user_repo"],
        "user_referral_binding_repo": repos["user_referral_binding_repo"],
        "user_referral_pending_repo": repos["user_referral_pending_repo"],
        "payout_request_repo": repos["payout_request_repo"],
        "outbox_publisher": outbox_publisher,
        "transaction_manager": transaction_manager,
        "max_order_price": config.order.max_order_price,
        "allowed_blogger_counts": config.order.get_allowed_blogger_counts_set(),
        "payment_currency": config.market.payment_currency,
        "currency_symbol": config.market.currency_symbol,
        "default_locale": config.market.default_locale,
        "bot_texts_service": BotTextsService(
            bot_texts_repo=repos["bot_texts_repo"],
            default_locale=config.market.default_locale,
            transaction_manager=transaction_manager,
        ),
        "country_repo": repos["country_repo"],
    }
