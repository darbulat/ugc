"""Shared dependency container for entrypoints.

Container delegates to RepositoryFactory, InfrastructureFactory, ServiceFactory.
"""

from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from aiogram import Bot
    from aiohttp import ClientSession

    from ugc_bot.application.services.paid_selection_delivery import (
        PaidSelectionDelivery,
    )
    from ugc_bot.container.types import BotServices

from ugc_bot.application.ports import GeocoderPort
from ugc_bot.application.services.accompaniment_lead_delivery import (
    AccompanimentLeadDelivery,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.collaboration_notice_delivery import (
    CollaborationNoticeDelivery,
)
from ugc_bot.application.services.collaboration_sweep_service import (
    CollaborationSweepService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig
from ugc_bot.container import (
    infrastructure_factory,
    repository_factory,
    service_factory,
)
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    get_engine,
)
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher


class Container:
    """Centralized factory for repos and services used across entrypoints.

    Delegates to RepositoryFactory, InfrastructureFactory, and ServiceFactory
    to follow Single Responsibility Principle.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session_factory = (
            infrastructure_factory.create_session_factory_from_config(config)
        )
        self._transaction_manager = (
            infrastructure_factory.create_transaction_manager(
                self._session_factory
            )
        )
        self._repos: dict | None = None
        self._exchange_rate_service: object | None = None

    @property
    def session_factory(self):
        return self._session_factory

    @property
    def transaction_manager(self) -> SessionTransactionManager | None:
        return self._transaction_manager

    def get_admin_engine(self) -> Engine:
        """Engine for SQLAdmin (pool_pre_ping)."""
        return infrastructure_factory.build_admin_engine(self._config)

    def build_repos(self) -> dict:
        """All repos for the main bot dispatcher. Cached after first call."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for repositories.")
        if self._repos is not None:
            return self._repos
        redis_url = (
            self._config.redis.redis_url
            if self._config.redis.use_redis_storage
            else None
        )
        self._repos = repository_factory.build_repos(
            self._session_factory, redis_url=redis_url
        )
        return self._repos

    def build_offer_dispatch_service(self) -> OfferDispatchService:
        """OfferDispatchService for Kafka consumer."""
        repos = self.build_repos()
        return service_factory.build_offer_dispatch_service(
            repos,
            self._transaction_manager,
            currency_symbol=self._config.market.currency_symbol,
        )

    def build_campaign_runtime(self, bot=None):
        from ugc_bot.container.campaign_runtime_factory import (
            build_campaign_runtime,
        )
        from ugc_bot.container.subscription_factory import (
            build_subscription_access,
        )

        return build_campaign_runtime(
            self._config,
            self._transaction_manager,
            bot=bot,
            delivery_enabled=self._config.campaign.delivery_enabled,
            access=build_subscription_access(self._config),
        )

    def build_financial_review(self):
        from ugc_bot.container.financial_review_factory import (
            build_financial_review,
        )

        return build_financial_review(self._config)

    def build_manual_grant_sweep(self):
        from ugc_bot.container.manual_grant_factory import build_manual_grants

        if self._transaction_manager is None:
            raise ValueError("manual_grant_database_required")
        return build_manual_grants(self._config, self._transaction_manager)[1]

    def build_selection_maturity_sweep(self):
        from ugc_bot.application.services import (
            selection_maturity_sweep_service,
        )
        from ugc_bot.application.services.financial_ledger_service import (
            FinancialLedgerService,
        )
        from ugc_bot.application.services.selection_maturity_service import (
            SelectionMaturityService,
        )
        from ugc_bot.infrastructure.clock import SystemClock
        from ugc_bot.infrastructure.db.repositories.selection_maturity import (
            SqlAlchemySelectionMaturityRepository,
        )

        if self._transaction_manager is None:
            raise ValueError("selection_maturity_database_required")
        maturity = SelectionMaturityService(
            SqlAlchemySelectionMaturityRepository(),
            FinancialLedgerService(self.build_repos()["financial_ledger_repo"]),
            SystemClock(),
        )
        return selection_maturity_sweep_service.SelectionMaturitySweepService(
            maturity, self._transaction_manager
        )

    def build_collaboration_sweep(self) -> CollaborationSweepService:
        if self._transaction_manager is None:
            raise ValueError(
                "DATABASE_URL is required for collaboration sweep."
            )
        return service_factory.build_collaboration_sweep(
            self.build_repos(), self._transaction_manager
        )

    def build_collaboration_notice_delivery(
        self, bot: "Bot", *, max_session: "ClientSession | None" = None
    ) -> CollaborationNoticeDelivery | None:
        if not self._config.financial.core_enabled:
            return None
        if self._transaction_manager is None:
            raise ValueError(
                "DATABASE_URL is required for collaboration notices."
            )
        return service_factory.build_collaboration_notice_delivery(
            self._config,
            self.build_repos(),
            self._transaction_manager,
            bot,
            max_session=max_session,
        )

    def build_accompaniment_lead_delivery(
        self, bot: "Bot", *, max_session: "ClientSession | None" = None
    ) -> AccompanimentLeadDelivery | None:
        if not self._config.financial.core_enabled:
            return None
        if self._transaction_manager is None:
            raise ValueError("DATABASE_URL is required for lead notices.")
        from ugc_bot.container.order_intake_factory import build_lead_delivery

        return build_lead_delivery(
            self._config,
            self._transaction_manager,
            bot,
            max_session=max_session,
        )

    def build_paid_selection_delivery(
        self, bot: "Bot", *, max_session: "ClientSession | None" = None
    ) -> "PaidSelectionDelivery | None":
        if not self._config.financial.core_enabled:
            return None
        if self._transaction_manager is None:
            raise ValueError(
                "DATABASE_URL is required for paid selection delivery."
            )
        from ugc_bot.container.paid_selection_delivery_factory import (
            build_paid_selection_delivery,
        )

        return build_paid_selection_delivery(
            self._config,
            self._transaction_manager,
            bot,
            max_session=max_session,
        )

    def build_campaign_digest(self, bot: "Bot", *, max_session=None):
        from ugc_bot.container.campaign_digest_factory import (
            build_campaign_digest,
        )

        return build_campaign_digest(
            self._config,
            self._transaction_manager,
            bot,
            max_session=max_session,
        )

    def build_user_role_service(self) -> UserRoleService:
        """UserRoleService for status updates (e.g. bot-blocked marking)."""
        repos = self.build_repos()
        return UserRoleService(
            user_repo=repos["user_repo"],
            transaction_manager=self._transaction_manager,
        )

    def build_bot_texts_service(self) -> BotTextsService:
        """BotTextsService for localized text lookup."""
        repos = self.build_repos()
        return BotTextsService(
            bot_texts_repo=repos["bot_texts_repo"],
            default_locale=self._config.market.default_locale,
            transaction_manager=self._transaction_manager,
        )

    def build_admin_services(
        self,
    ) -> tuple[UserRoleService, ComplaintService, InteractionService]:
        """UserRoleService, ComplaintService, InteractionService for admin."""
        repos = self.build_repos()
        return service_factory.build_admin_services(self._config, repos)

    def build_referral_income_service(self) -> ReferralIncomeService:
        """ReferralIncomeService for admin dashboard (referrer balance)."""
        repos = self.build_repos()
        return service_factory.build_referral_income_service(
            repos, self._transaction_manager
        )

    def build_outbox_publisher(self) -> OutboxPublisher:
        """OutboxPublisher only (no Kafka producer). Use in admin."""
        repos = self.build_repos()
        return OutboxPublisher(
            outbox_repo=repos["outbox_repo"],
            order_repo=repos["order_repo"],
            transaction_manager=self._transaction_manager,
            dispatch_control=repos.get("dispatch_control"),
        )

    def build_outbox_deps(
        self,
    ) -> tuple[OutboxPublisher, KafkaOrderActivationPublisher | None]:
        """OutboxPublisher and optional KafkaOrderActivationPublisher."""
        repos = self.build_repos()
        return service_factory.build_outbox_deps(
            self._config, repos, self._transaction_manager
        )

    def build_feedback_scheduler_deps(self) -> dict:
        """Deps for feedback scheduler: repos and services."""
        repos = self.build_repos()
        return service_factory.build_feedback_scheduler_deps(
            self._config, repos, self._transaction_manager
        )

    def build_instagram_stats_scheduler_deps(
        self,
        telegram_messenger_client=None,
        max_messenger_client=None,
        bot_texts_service=None,
    ) -> dict:
        """Deps for Instagram stats update scheduler."""
        repos = self.build_repos()
        instagram_api_client = self.build_instagram_api_client()
        return service_factory.build_instagram_stats_scheduler_deps(
            self._config,
            repos,
            self._transaction_manager,
            instagram_api_client,
            telegram_messenger_client=telegram_messenger_client,
            max_messenger_client=max_messenger_client,
            bot_texts_service=bot_texts_service,
        )

    def build_instagram_stats_collector_scheduler_deps(self) -> dict:
        """Deps for Instagram stats collector scheduler."""
        repos = self.build_repos()
        stats_provider_client = (
            infrastructure_factory.build_instagram_stats_provider_client(
                self._config
            )
        )
        return service_factory.build_instagram_stats_collector_scheduler_deps(
            self._config,
            repos,
            self._transaction_manager,
            stats_provider_client,
        )

    def build_instagram_verification_service(
        self,
    ) -> InstagramVerificationService:
        """InstagramVerificationService for webhook."""
        repos = self.build_repos()
        instagram_api_client = self.build_instagram_api_client()
        return service_factory.build_instagram_verification_service(
            repos, instagram_api_client, self._transaction_manager
        )

    def build_metrics_collector(self):
        """Create metrics collector."""
        return infrastructure_factory.build_metrics_collector()

    def build_geocoder(self) -> GeocoderPort:
        """Create geocoder implementation configured for this app."""
        return service_factory.build_geocoder(self._config)

    def build_issue_lock_manager(self):
        """Create lock manager for issue description (Redis or in-memory)."""
        return infrastructure_factory.build_issue_lock_manager(self._config)

    def build_offer_response_rate_limiter(self):
        """Create rate limiter for offer responses (Redis or in-memory)."""
        return infrastructure_factory.build_offer_response_rate_limiter(
            self._config
        )

    def build_geocode_public_rate_limiter(self):
        """Create per-IP rate limiter for the public geocode endpoint."""
        return infrastructure_factory.build_geocode_public_rate_limiter(
            self._config
        )

    def build_instagram_api_client(self):
        """Create Instagram Graph API client if configured."""
        return infrastructure_factory.build_instagram_api_client(self._config)

    def build_referral_reconciliation_deps(self) -> dict:
        """Deps for referral reconciliation scheduler."""
        repos = self.build_repos()
        return service_factory.build_referral_reconciliation_deps(
            self._config, repos, self._transaction_manager
        )

    def build_manager_service(self) -> ManagerService:
        """ManagerService for admin panel."""
        repos = self.build_repos()
        return ManagerService(
            manager_order_repo=repos["manager_order_repo"],
            user_repo=repos["user_repo"],
            order_repo=repos["order_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            transaction_manager=self._transaction_manager,
        )

    async def dispose(self) -> None:
        """Dispose the async engine, closing all pooled DB connections.

        Call this during application shutdown to prevent connection leaks.
        """
        if self._exchange_rate_service is not None and hasattr(
            self._exchange_rate_service, "close"
        ):
            await self._exchange_rate_service.close()  # type: ignore[union-attr]
            self._exchange_rate_service = None
        if self._session_factory is not None:
            engine = get_engine(self._session_factory)
            if engine is not None:
                await engine.dispose()

    def build_order_image_service(self):
        """Private attachment storage shared by API replicas and cleanup."""
        from ugc_bot.application.services.order_image_service import (
            OrderImageService,
        )
        from ugc_bot.infrastructure.clock import SystemClock
        from ugc_bot.infrastructure.db.repositories.order_images import (
            SqlAlchemyOrderImageRepository,
        )
        from ugc_bot.infrastructure.order_images import PrivateOrderImageStorage

        if self._transaction_manager is None:
            return None
        return OrderImageService(
            SqlAlchemyOrderImageRepository(),
            PrivateOrderImageStorage(),
            self._transaction_manager,
            SystemClock(),
        )

    def build_order_notice_details_service(self):
        """Saved quote projection shared by private cards and admin views."""
        from ugc_bot.application.services.order_notice_details_service import (
            OrderNoticeDetailsService,
        )
        from ugc_bot.infrastructure.db.repositories import order_notice_details

        if self._transaction_manager is None:
            return None
        return OrderNoticeDetailsService(
            order_notice_details.SqlAlchemyOrderNoticeDetailsRepository(),
            self._transaction_manager,
        )

    def build_order_notice_delivery(self, messenger_client):
        """Durable created/paid cards use the persisted quote and contacts."""
        from ugc_bot.container.order_notice_factory import (
            build_order_notice_delivery,
        )

        details = self.build_order_notice_details_service()
        if details is None:
            return None
        return build_order_notice_delivery(
            self._config,
            self._transaction_manager,
            messenger_client,
            self.build_repos(),
            details_loader=details.for_order,
        )

    def build_bot_services(self) -> "BotServices":
        """Build all services and repos for the bot dispatcher."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for bot services.")
        repos = self.build_repos()
        metrics_collector = self.build_metrics_collector()
        instagram_api_client = self.build_instagram_api_client()
        issue_lock_manager = self.build_issue_lock_manager()
        offer_response_rate_limiter = self.build_offer_response_rate_limiter()
        geocode_public_rate_limiter = self.build_geocode_public_rate_limiter()
        outbox_publisher = OutboxPublisher(
            outbox_repo=repos["outbox_repo"],
            order_repo=repos["order_repo"],
            transaction_manager=self._transaction_manager,
            dispatch_control=repos.get("dispatch_control"),
        )
        bot_services = service_factory.build_bot_services(
            self._config,
            repos,
            self._transaction_manager,
            metrics_collector,
            instagram_api_client,
            outbox_publisher,
            issue_lock_manager,
            offer_response_rate_limiter,
            geocode_public_rate_limiter,
            session_factory=self._session_factory,
        )
        self._exchange_rate_service = bot_services["exchange_rate_service"]
        return bot_services
