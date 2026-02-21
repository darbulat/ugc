"""Shared dependency container for entrypoints.

Container delegates to RepositoryFactory, InfrastructureFactory, ServiceFactory.
"""

from typing import TYPE_CHECKING

from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from ugc_bot.container.types import BotServices

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
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
from ugc_bot.infrastructure.db.session import SessionTransactionManager
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
        self._repos = repository_factory.build_repos(self._session_factory)
        return self._repos

    def build_offer_dispatch_service(self) -> OfferDispatchService:
        """OfferDispatchService for Kafka consumer."""
        repos = self.build_repos()
        return service_factory.build_offer_dispatch_service(
            repos, self._transaction_manager
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

    def build_instagram_stats_scheduler_deps(self) -> dict:
        """Deps for Instagram stats update scheduler."""
        repos = self.build_repos()
        instagram_api_client = self.build_instagram_api_client()
        return service_factory.build_instagram_stats_scheduler_deps(
            self._config,
            repos,
            self._transaction_manager,
            instagram_api_client,
        )

    def build_rapid_api_client(self):
        """Create Rapid API Instagram client if configured."""
        return infrastructure_factory.build_rapid_api_client(self._config)

    def build_instagram_rapid_stats_scheduler_deps(self) -> dict:
        """Deps for Instagram Rapid API stats scheduler."""
        repos = self.build_repos()
        stats_provider_client = (
            infrastructure_factory.build_instagram_stats_provider_client(
                self._config
            )
        )
        return service_factory.build_instagram_rapid_stats_scheduler_deps(
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

    def build_issue_lock_manager(self):
        """Create lock manager for issue description (Redis or in-memory)."""
        return infrastructure_factory.build_issue_lock_manager(self._config)

    def build_offer_response_rate_limiter(self):
        """Create rate limiter for offer responses (Redis or in-memory)."""
        return infrastructure_factory.build_offer_response_rate_limiter(
            self._config
        )

    def build_instagram_api_client(self):
        """Create Instagram Graph API client if configured."""
        return infrastructure_factory.build_instagram_api_client(self._config)

    def build_bot_services(self) -> "BotServices":
        """Build all services and repos for the bot dispatcher."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for bot services.")
        repos = self.build_repos()
        metrics_collector = self.build_metrics_collector()
        instagram_api_client = self.build_instagram_api_client()
        issue_lock_manager = self.build_issue_lock_manager()
        offer_response_rate_limiter = self.build_offer_response_rate_limiter()
        outbox_publisher = OutboxPublisher(
            outbox_repo=repos["outbox_repo"],
            order_repo=repos["order_repo"],
            transaction_manager=self._transaction_manager,
        )
        return service_factory.build_bot_services(
            self._config,
            repos,
            self._transaction_manager,
            metrics_collector,
            instagram_api_client,
            outbox_publisher,
            issue_lock_manager,
            offer_response_rate_limiter,
        )
