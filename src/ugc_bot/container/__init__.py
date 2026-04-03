"""Shared dependency container for entrypoints.

Container delegates to RepositoryFactory, InfrastructureFactory, ServiceFactory.
"""

from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from ugc_bot.container.types import BotServices

from ugc_bot.application.ports import GeocoderPort
from ugc_bot.application.services.bot_texts_service import BotTextsService
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
        self, messenger_client=None, bot_texts_service=None
    ) -> dict:
        """Deps for Instagram stats update scheduler."""
        repos = self.build_repos()
        instagram_api_client = self.build_instagram_api_client()
        return service_factory.build_instagram_stats_scheduler_deps(
            self._config,
            repos,
            self._transaction_manager,
            instagram_api_client,
            messenger_client=messenger_client,
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
        )
        self._exchange_rate_service = bot_services["exchange_rate_service"]
        return bot_services
