"""Factory for creating application services."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ugc_bot.application.cache_ports import CachePort

if TYPE_CHECKING:
    from aiogram import Bot
    from aiohttp import ClientSession

from ugc_bot.application.ports import GeocoderPort, TransactionManager
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.campaign_audience_service import (
    CampaignAudienceService,
)
from ugc_bot.application.services.campaign_review_service import (
    CampaignReviewService,
)
from ugc_bot.application.services.campaign_service import (
    CampaignFoundationService,
)
from ugc_bot.application.services.campaign_summary_service import (
    CampaignSummaryService,
)
from ugc_bot.application.services.client_entitlement_service import (
    ClientEntitlementService,
)
from ugc_bot.application.services.collaboration_notice_delivery import (
    CollaborationNoticeDelivery,
)
from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.application.services.collaboration_sweep_service import (
    CollaborationSweepService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.exchange_rate_service import (
    ExchangeRateService,
)
from ugc_bot.application.services.financial_event_router import (
    FinancialEventHandler,
    FinancialEventRouter,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
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
from ugc_bot.application.services.legacy_financial_case_service import (
    LegacyFinancialCaseService,
)
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_image_service import OrderImageService
from ugc_bot.application.services.order_intake_service import OrderIntakeService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.paid_item_service import PaidItemService
from ugc_bot.application.services.paid_selection_interest import (
    PaidSelectionInterestService,
)
from ugc_bot.application.services.partner_admin_service import (
    PartnerAdminService,
)
from ugc_bot.application.services.partner_view_service import PartnerViewService
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.rate_override_service import (
    RateOverrideService,
)
from ugc_bot.application.services.referral_income_recorder import (
    ReferralIncomeRecorder,
)
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.selection_maturity_service import (
    SelectionMaturityService,
)
from ugc_bot.application.services.selection_view_service import (
    SelectionViewService,
)
from ugc_bot.application.services.social_account_service import (
    SocialAccountService,
)
from ugc_bot.application.services.subscription_service import (
    SubscriptionService,
)
from ugc_bot.application.services.support_service import SupportService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.application.services.work_entitlement_service import (
    WorkEntitlementService,
)
from ugc_bot.application.services.work_financial_guard import WorkFinancialGuard
from ugc_bot.application.work_entitlement_ports import WORK_EVENT_TYPES
from ugc_bot.config import AppConfig
from ugc_bot.container.campaign_analytics_factory import (
    build_campaign_analytics,
)
from ugc_bot.container.campaign_runtime_factory import build_campaign_runtime
from ugc_bot.container.checkout_factory import build_checkout_service
from ugc_bot.container.correction_factory import (
    build_accompaniment_refund_service,
    build_correction_services,
)
from ugc_bot.container.customer_workflow_factory import build_customer_workflows
from ugc_bot.container.debt_recovery_factory import build_debt_recovery
from ugc_bot.container.financial_review_factory import build_financial_review
from ugc_bot.container.manual_grant_factory import build_manual_grants
from ugc_bot.container.messenger_linking_factory import (
    build_messenger_linking_service,
)
from ugc_bot.container.payout_factory import build_payout_service
from ugc_bot.container.payout_view_factory import build_payout_view_service
from ugc_bot.container.replacement_factory import build_replacement_service
from ugc_bot.container.subscription_factory import build_subscription_access
from ugc_bot.container.types import BotServices
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)
from ugc_bot.infrastructure.db.repositories.order_images import (
    SqlAlchemyOrderImageRepository,
)
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
)
from ugc_bot.infrastructure.db.repositories.partner_admin import (
    SqlAlchemyPartnerAdminRepository,
)
from ugc_bot.infrastructure.db.repositories.rating_eligibility import (
    SqlAlchemyRatingEligibilityRepository,
)
from ugc_bot.infrastructure.db.repositories.selection_maturity import (
    SqlAlchemySelectionMaturityRepository,
)
from ugc_bot.infrastructure.db.repositories.subscriptions import (
    SqlAlchemySubscriptionRepository,
)
from ugc_bot.infrastructure.geocoder_cache_memory import GeocoderCacheMemory
from ugc_bot.infrastructure.geocoder_cache_redis import (
    DEFAULT_PREFIX as GEOCODER_CACHE_KEY_PREFIX,
)
from ugc_bot.infrastructure.geocoder_cache_redis import (
    GeocoderCacheRedis,
)
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryFinancialDeliveryRepository,
    InMemoryOutboxRepository,
)
from ugc_bot.infrastructure.order_images import PrivateOrderImageStorage


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


def build_offer_dispatch_service(
    repos, transaction_manager, currency_symbol="₽"
):
    """Build OfferDispatchService for Kafka consumer."""
    return OfferDispatchService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        order_repo=repos["order_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        country_repo=repos.get("country_repo"),
        interaction_repo=repos["interaction_repo"],
        instagram_stats_repo=repos.get("instagram_stats_repo"),
        blogger_rating_repo=repos.get("blogger_rating_repo"),
        manager_order_repo=repos.get("manager_order_repo"),
        transaction_manager=transaction_manager,
        currency_symbol=currency_symbol,
        intake_repository=repos.get("order_intake_repo"),
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
        referral_income_entry_repo=repos.get("referral_income_entry_repo"),
        contact_pricing_repo=repos.get("pricing_repo"),
    )


def build_admin_services(config: AppConfig, repos):
    """Build UserRoleService, ComplaintService, InteractionService for admin."""
    return (
        UserRoleService(user_repo=repos["user_repo"]),
        ComplaintService(complaint_repo=repos["complaint_repo"]),
        InteractionService(
            interaction_repo=repos["interaction_repo"],
            postpone_delay_minutes=config.feedback.feedback_delay_minutes,
            feedback_reminder_timezone=config.feedback.feedback_reminder_timezone,
            feedback_reminder_hour=config.feedback.feedback_reminder_hour,
            feedback_reminder_minute=config.feedback.feedback_reminder_minute,
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
    financial_repo = repos.get("financial_delivery_repo")
    if financial_repo is None and isinstance(
        repos["outbox_repo"], InMemoryOutboxRepository
    ):
        financial_repo = InMemoryFinancialDeliveryRepository(
            repos["outbox_repo"].events, repos["outbox_repo"]._claimed_at
        )
    if financial_repo is not None:
        handlers: dict[str, FinancialEventHandler] = {}
        work_repo = repos.get("work_entitlement_repo")
        work_guard = (
            WorkFinancialGuard(work_repo) if work_repo is not None else None
        )
        if config.financial.core_enabled and repos.get(
            "client_entitlement_repo"
        ):
            handlers["financial.client_snapshot_requested"] = (
                ClientEntitlementService(
                    repos["client_entitlement_repo"],
                    FinancialLedgerService(repos["financial_ledger_repo"]),
                    CreatorIdentityHistoryService(
                        repos["creator_identity_history_repo"]
                    ),
                    repos["rate_override_repo"],
                    SystemClock(),
                    work_guard=work_guard,
                    funding_guard=LiveCorrectionFundingGuard(
                        SqlAlchemyCorrectionRepository()
                    ),
                )
            )
            if work_repo is not None:
                work_handler = WorkEntitlementService(
                    work_repo,
                    FinancialLedgerService(repos["financial_ledger_repo"]),
                    CreatorIdentityHistoryService(
                        repos["creator_identity_history_repo"]
                    ),
                    repos["rate_override_repo"],
                    SystemClock(),
                    guard=work_guard,
                    funding_guard=LiveCorrectionFundingGuard(
                        SqlAlchemyCorrectionRepository()
                    ),
                )
                handlers.update(
                    {kind: work_handler for kind in WORK_EVENT_TYPES}
                )
        outbox_publisher.financial_delivery = OutboxPublisher(
            financial_repo,
            repos["order_repo"],
            transaction_manager,
            financial_router=FinancialEventRouter(handlers),
        )
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
            feedback_reminder_timezone=config.feedback.feedback_reminder_timezone,
            feedback_reminder_hour=config.feedback.feedback_reminder_hour,
            feedback_reminder_minute=config.feedback.feedback_reminder_minute,
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
    user_role_service = UserRoleService(
        user_repo=repos["user_repo"],
        transaction_manager=transaction_manager,
        blogger_profile_repo=repos["blogger_repo"],
    )
    return InstagramVerificationService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        verification_repo=repos["instagram_repo"],
        instagram_api_client=instagram_api_client,
        transaction_manager=transaction_manager,
        user_role_service=user_role_service,
        social_repo=repos.get("social_account_repo"),
    )


def build_instagram_stats_scheduler_deps(
    config: AppConfig,
    repos,
    transaction_manager,
    instagram_api_client,
    telegram_messenger_client=None,
    max_messenger_client=None,
    bot_texts_service=None,
):
    """Build deps for Instagram stats update scheduler."""
    ig_config = config.instagram
    default_locale = config.market.default_locale or "ru"
    return {
        "instagram_stats_update_service": InstagramStatsUpdateService(
            blogger_repo=repos["blogger_repo"],
            instagram_api_client=instagram_api_client,
            transaction_manager=transaction_manager,
            batch_size=ig_config.instagram_stats_batch_size,
            delay_seconds=ig_config.instagram_stats_delay_seconds,
            user_repo=repos["user_repo"],
            telegram_messenger_client=telegram_messenger_client,
            max_messenger_client=max_messenger_client,
            bot_texts_service=bot_texts_service,
            default_locale=default_locale,
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
    except ImportError:  # pragma: no cover
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


logger = logging.getLogger(__name__)


def build_collaboration_sweep(repos, transaction_manager):
    return CollaborationSweepService(
        CollaborationService(repos["collaboration_repo"], SystemClock()),
        transaction_manager,
    )


def build_collaboration_notice_delivery(
    config: AppConfig,
    repos: dict,
    transaction_manager: TransactionManager,
    bot: "Bot",
    *,
    max_session: "ClientSession | None" = None,
) -> CollaborationNoticeDelivery | None:
    if not config.financial.core_enabled:
        return None
    from urllib.parse import urlsplit

    from ugc_bot.application.notice_delivery_ports import NoticeReceiptTransport
    from ugc_bot.infrastructure.db.repositories.notice_delivery import (
        SqlAlchemyNoticeDeliveryRepository,
    )
    from ugc_bot.infrastructure.messenger.notice_receipts import (
        MaxNoticeReceipts,
        RoutedNoticeReceipts,
        TelegramNoticeReceipts,
    )

    transports: dict[str, NoticeReceiptTransport] = {
        "telegram": TelegramNoticeReceipts(bot)
    }
    max_config = config.max_bot
    if max_config and max_config.token.strip() and max_session is not None:
        transports["max"] = MaxNoticeReceipts(max_session, max_config.token)
    telegram_base = config.webhook.webhook_base_url.rstrip("/")
    try:
        max_url = urlsplit(max_config.webhook_url if max_config else "")
        max_base = (
            f"{max_url.scheme}://{max_url.netloc}"
            if max_url.scheme and max_url.netloc
            else ""
        )
    except ValueError:
        max_base = ""
    return CollaborationNoticeDelivery(
        CollaborationService(repos["collaboration_repo"], SystemClock()),
        SqlAlchemyNoticeDeliveryRepository(),
        transaction_manager,
        RoutedNoticeReceipts(transports),
        {
            "telegram": telegram_base + "/miniapp/app.html"
            if telegram_base
            else "",
            "max": max_base + "/miniapp/max_app.html" if max_base else "",
        },
        default_locale=config.market.default_locale or "ru",
    )


def build_exchange_rate_service(
    config: AppConfig,
) -> ExchangeRateService | None:
    """Build ExchangeRateService if Redis is configured, else None."""
    if not config.redis.redis_url:
        return None
    try:
        import aiohttp
        from redis.asyncio import Redis

        from ugc_bot.infrastructure.exchange_rate import (
            OpenERApiProvider,
            RedisExchangeRateCache,
        )

        session = aiohttp.ClientSession()
        provider = OpenERApiProvider(session=session)
        redis_client = Redis.from_url(
            config.redis.redis_url, decode_responses=True
        )
        cache = RedisExchangeRateCache(redis=redis_client)
        return ExchangeRateService(provider=provider, cache=cache)
    except Exception:
        logger.warning("Could not build ExchangeRateService", exc_info=True)
        return None


def build_bot_services(
    config: AppConfig,
    repos: dict[str, Any],
    transaction_manager: Any,
    metrics_collector: Any,
    instagram_api_client: Any,
    outbox_publisher: OutboxPublisher,
    issue_lock_manager: Any,
    offer_response_rate_limiter: Any,
    geocode_public_rate_limiter: Any,
    session_factory: Any = None,
) -> BotServices:
    """Build all services and repos for the bot dispatcher."""
    referral_service = ReferralService(
        user_repo=repos["user_repo"],
        user_referral_pending_repo=repos["user_referral_pending_repo"],
        user_referral_binding_repo=repos["user_referral_binding_repo"],
        transaction_manager=transaction_manager,
    )
    geocoder = build_geocoder(config)
    exchange_rate_service = build_exchange_rate_service(config)
    referral_income_service = ReferralIncomeService(
        user_referral_binding_repo=repos["user_referral_binding_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        order_repo=repos["order_repo"],
        payment_repo=repos["payment_repo"],
        interaction_repo=repos["interaction_repo"],
        user_repo=repos["user_repo"],
        payout_request_repo=repos["payout_request_repo"],
        transaction_manager=transaction_manager,
        referral_order_income_loader=repos.get("referral_order_income_loader"),
        referral_income_entry_repo=repos.get("referral_income_entry_repo"),
        contact_pricing_repo=repos.get("pricing_repo"),
    )
    user_role_service = UserRoleService(
        user_repo=repos["user_repo"],
        metrics_collector=metrics_collector,
        transaction_manager=transaction_manager,
        blogger_profile_repo=repos["blogger_repo"],
    )
    order_service = OrderService(
        order_notices=SqlAlchemyOrderNoticeRepository()
        if transaction_manager is not None
        else None,
        user_repo=repos["user_repo"],
        advertiser_repo=repos["advertiser_repo"],
        order_repo=repos["order_repo"],
        paid_item_service=PaidItemService(
            repository=repos["financial_item_repo"],
            policy_service=FinancialPolicyService(
                config.financial,
                reader=repos["financial_policy_repo"],
                transaction_manager=transaction_manager,
            ),
        ),
        allowed_blogger_counts=config.order.get_allowed_blogger_counts_set(),
        max_order_price=config.order.max_order_price,
        metrics_collector=metrics_collector,
        transaction_manager=transaction_manager,
        geocoder=geocoder,
        country_repo=repos.get("country_repo"),
    )
    correction_service, correction_view_service = (
        build_correction_services(config, transaction_manager, session_factory)
        if session_factory is not None
        else (None, None)
    )
    manual_grant_service, manual_grant_sweep = (
        build_manual_grants(config, transaction_manager)
        if transaction_manager is not None
        else (None, None)
    )
    image_service = (
        OrderImageService(
            SqlAlchemyOrderImageRepository(),
            PrivateOrderImageStorage(),
            transaction_manager,
            SystemClock(),
        )
        if transaction_manager is not None
        else None
    )
    customer_workflows = (
        build_customer_workflows(transaction_manager)
        if transaction_manager is not None
        else {}
    )
    return {
        "order_image_service": image_service,
        "order_support_service": customer_workflows.get(
            "order_support_service"
        ),
        "service_lead_service": customer_workflows.get("service_lead_service"),
        "client_followup_service": customer_workflows.get(
            "client_followup_service"
        ),
        "client_order_view_service": customer_workflows.get(
            "client_order_view_service"
        ),
        "payment_repo": repos["payment_repo"],
        "financial_review_service": build_financial_review(config),
        "manual_grant_service": manual_grant_service,
        "manual_grant_sweep": manual_grant_sweep,
        **build_campaign_runtime(
            config,
            transaction_manager,
            access=build_subscription_access(config),
        ),
        **build_campaign_analytics(transaction_manager),
        "accompaniment_refund_service": build_accompaniment_refund_service(
            config, transaction_manager, session_factory
        )
        if transaction_manager is not None and session_factory is not None
        else None,
        "debt_recovery_service": build_debt_recovery(config),
        "partner_admin_service": PartnerAdminService(
            SqlAlchemyPartnerAdminRepository(), SystemClock()
        ),
        "replacement_service": build_replacement_service(config),
        "metrics_collector": metrics_collector,
        "messenger_linking_service": build_messenger_linking_service(
            config, transaction_manager
        ),
        "payout_service": build_payout_service(
            config, transaction_manager, session_factory
        )
        if session_factory is not None
        else None,
        "correction_service": correction_service,
        "correction_view_service": correction_view_service,
        "payout_view_service": build_payout_view_service(
            config, session_factory
        )
        if session_factory is not None
        else None,
        "campaign_summary_service": CampaignSummaryService(
            repos["campaign_summary_repo"], transaction_manager, SystemClock()
        )
        if repos.get("campaign_summary_repo") is not None
        else None,
        "content_moderation_service": ContentModerationService(),
        "selection_maturity_service": SelectionMaturityService(
            SqlAlchemySelectionMaturityRepository(),
            FinancialLedgerService(repos["financial_ledger_repo"]),
            SystemClock(),
        ),
        "selection_view_service": SelectionViewService(
            repos["selection_view_repo"],
            transaction_manager,
        )
        if repos.get("selection_view_repo") is not None
        else None,
        "user_role_service": user_role_service,
        "campaign_service": CampaignFoundationService(
            repos["campaign_repo"], SystemClock()
        )
        if repos.get("campaign_repo") is not None
        else None,
        "campaign_review_service": CampaignReviewService(
            repos["campaign_review_repo"],
            repos["campaign_repo"],
            SystemClock(),
        )
        if repos.get("campaign_review_repo") is not None
        and repos.get("campaign_repo") is not None
        else None,
        "campaign_audience_service": CampaignAudienceService(
            repos["campaign_review_repo"], repos["campaign_repo"]
        )
        if repos.get("campaign_review_repo") is not None
        and repos.get("campaign_repo") is not None
        else None,
        "partner_view_service": PartnerViewService(
            repos["partner_view_repo"],
            SystemClock(),
            {
                "telegram": config.referral.referral_bot_username,
                "max": config.referral.max_referral_bot_username,
            },
        )
        if repos.get("partner_view_repo") is not None
        else None,
        "rate_override_service": RateOverrideService(
            repos["rate_override_repo"], SystemClock()
        )
        if repos.get("rate_override_repo") is not None
        else None,
        "creator_identity_history_service": CreatorIdentityHistoryService(
            repos["creator_identity_history_repo"]
        )
        if repos.get("creator_identity_history_repo") is not None
        else None,
        "collaboration_service": CollaborationService(
            repos["collaboration_repo"], SystemClock()
        )
        if repos.get("collaboration_repo") is not None
        else None,
        "social_account_service": SocialAccountService(
            account_repo=repos["social_account_repo"],
            blogger_repo=repos["blogger_repo"],
            transaction_manager=transaction_manager,
            editor_repository=repos["social_account_repo"],
        )
        if repos.get("social_account_repo") is not None
        else None,
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
            user_role_service=user_role_service,
            social_repo=repos.get("social_account_repo"),
        ),
        "order_service": order_service,
        "subscription_service": SubscriptionService(
            SqlAlchemySubscriptionRepository(),
            transaction_manager,
            SystemClock(),
        ),
        "order_intake_service": OrderIntakeService(
            repos["order_intake_repo"],
            order_service,
            repos["financial_policy_repo"],
            transaction_manager,
            SystemClock(),
            config.financial,
            image_service=image_service,
        )
        if repos.get("order_intake_repo") is not None
        else None,
        "offer_dispatch_service": OfferDispatchService(
            intake_repository=repos.get("order_intake_repo"),
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            order_repo=repos["order_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            interaction_repo=repos["interaction_repo"],
            country_repo=repos.get("country_repo"),
            blogger_rating_repo=repos.get("blogger_rating_repo"),
            manager_order_repo=repos.get("manager_order_repo"),
            transaction_manager=transaction_manager,
            currency_symbol=config.market.currency_symbol,
        ),
        "blogger_rating_service": BloggerRatingService(
            eligibility_repo=SqlAlchemyRatingEligibilityRepository(),
            rating_repo=repos["blogger_rating_repo"],
            transaction_manager=transaction_manager,
        ),
        "offer_response_service": OfferResponseService(
            order_repo=repos["order_repo"],
            dispatch_repo=repos["offer_dispatch_repo"],
            manager_order_repo=repos["manager_order_repo"],
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
            user_repo=repos["user_repo"],
            referral_income_service=referral_income_service,
            paid_selection_service=PaidSelectionInterestService(
                repos["paid_selection_repo"],
                transaction_manager,
                SystemClock(),
                enabled=config.financial.core_enabled,
            )
            if repos.get("paid_selection_repo") is not None
            else None,
        ),
        "interaction_service": InteractionService(
            interaction_repo=repos["interaction_repo"],
            postpone_delay_minutes=config.feedback.feedback_delay_minutes,
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
            feedback_reminder_timezone=config.feedback.feedback_reminder_timezone,
            feedback_reminder_hour=config.feedback.feedback_reminder_hour,
            feedback_reminder_minute=config.feedback.feedback_reminder_minute,
            order_repo=repos["order_repo"],
            user_repo=repos["user_repo"],
            referral_income_service=referral_income_service,
        ),
        "checkout_service": build_checkout_service(config, transaction_manager),
        "payment_service": PaymentService(
            order_notices=SqlAlchemyOrderNoticeRepository()
            if transaction_manager is not None
            else None,
            user_repo=repos["user_repo"],
            advertiser_repo=repos["advertiser_repo"],
            order_repo=repos["order_repo"],
            payment_repo=repos["payment_repo"],
            pricing_repo=repos["pricing_repo"],
            country_repo=repos.get("country_repo"),
            capture_repository=(
                SqlAlchemyFinancialCaptureRepository(
                    FinancialPolicyService(config.financial),
                    history=CreatorIdentityHistoryService(
                        repos["creator_identity_history_repo"]
                    )
                    if repos.get("creator_identity_history_repo")
                    else None,
                )
                if config.bot.telegram_payment_account_id
                else None
            ),
            capture_account=config.bot.telegram_payment_account_id,
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
        "legacy_financial_case_service": LegacyFinancialCaseService(
            repos["legacy_financial_case_repo"]
        )
        if repos.get("legacy_financial_case_repo") is not None
        else None,
        "referral_income_service": referral_income_service,
        "issue_lock_manager": issue_lock_manager,
        "offer_response_rate_limiter": offer_response_rate_limiter,
        "geocode_public_rate_limiter": geocode_public_rate_limiter,
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
        "language_repo": repos["language_repo"],
        "manager_service": ManagerService(
            manager_order_repo=repos["manager_order_repo"],
            user_repo=repos["user_repo"],
            order_repo=repos["order_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            transaction_manager=transaction_manager,
        ),
        "manager_order_repo": repos["manager_order_repo"],
        "exchange_rate_service": exchange_rate_service,
        "support_service": SupportService(
            support_message_repo=repos["support_message_repo"],
            transaction_manager=transaction_manager,
        ),
    }


def build_referral_reconciliation_deps(
    config: AppConfig, repos, transaction_manager
):
    """Build deps for referral reconciliation scheduler."""
    return {
        "referral_income_entry_repo": repos["referral_income_entry_repo"],
        "order_repo": repos["order_repo"],
        "transaction_manager": transaction_manager,
        "recorder": ReferralIncomeRecorder(
            user_referral_binding_repo=repos["user_referral_binding_repo"],
            user_repo=repos["user_repo"],
            referral_income_entry_repo=repos["referral_income_entry_repo"],
            contact_pricing_repo=repos["pricing_repo"],
            payment_repo=repos["payment_repo"],
        ),
    }
