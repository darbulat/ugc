"""Shared dependency container for entrypoints."""

from sqlalchemy.engine import Engine

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import ContactPricingService
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
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.repositories import NoopOfferBroadcaster
from ugc_bot.metrics.collector import MetricsCollector
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyComplaintRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderResponseRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_db_engine,
    create_session_factory,
)
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher


class Container:
    """Centralized factory for repos and services used across entrypoints."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session_factory = (
            create_session_factory(
                config.db.database_url,
                pool_size=config.db.pool_size,
                max_overflow=config.db.max_overflow,
                pool_timeout=config.db.pool_timeout,
            )
            if config.db.database_url
            else None
        )
        self._transaction_manager = (
            SessionTransactionManager(self._session_factory)
            if self._session_factory
            else None
        )

    @property
    def session_factory(self):
        return self._session_factory

    @property
    def transaction_manager(self) -> SessionTransactionManager | None:
        return self._transaction_manager

    def get_admin_engine(self) -> Engine:
        """Engine for SQLAdmin (pool_pre_ping)."""
        if not self._config.db.database_url:
            raise ValueError("DATABASE_URL is required for admin.")
        return create_db_engine(
            self._config.db.database_url,
            pool_size=self._config.db.pool_size,
            max_overflow=self._config.db.max_overflow,
            pool_timeout=self._config.db.pool_timeout,
        )

    def build_repos(self) -> dict:
        """All repos for the main bot dispatcher."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for repositories.")
        return {
            "user_repo": SqlAlchemyUserRepository(
                session_factory=self._session_factory
            ),
            "blogger_repo": SqlAlchemyBloggerProfileRepository(
                session_factory=self._session_factory
            ),
            "advertiser_repo": SqlAlchemyAdvertiserProfileRepository(
                session_factory=self._session_factory
            ),
            "instagram_repo": SqlAlchemyInstagramVerificationRepository(
                session_factory=self._session_factory
            ),
            "order_repo": SqlAlchemyOrderRepository(
                session_factory=self._session_factory
            ),
            "order_response_repo": SqlAlchemyOrderResponseRepository(
                session_factory=self._session_factory
            ),
            "interaction_repo": SqlAlchemyInteractionRepository(
                session_factory=self._session_factory
            ),
            "payment_repo": SqlAlchemyPaymentRepository(
                session_factory=self._session_factory
            ),
            "pricing_repo": SqlAlchemyContactPricingRepository(
                session_factory=self._session_factory
            ),
            "complaint_repo": SqlAlchemyComplaintRepository(
                session_factory=self._session_factory
            ),
            "outbox_repo": SqlAlchemyOutboxRepository(
                session_factory=self._session_factory
            ),
        }

    def build_offer_dispatch_service(self) -> OfferDispatchService:
        """OfferDispatchService for Kafka consumer."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for offer dispatch.")
        return OfferDispatchService(
            user_repo=SqlAlchemyUserRepository(session_factory=self._session_factory),
            blogger_repo=SqlAlchemyBloggerProfileRepository(
                session_factory=self._session_factory
            ),
            order_repo=SqlAlchemyOrderRepository(session_factory=self._session_factory),
        )

    def build_admin_services(
        self,
    ) -> tuple[UserRoleService, ComplaintService, InteractionService]:
        """UserRoleService, ComplaintService, InteractionService for admin."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for admin services.")
        user_repo = SqlAlchemyUserRepository(session_factory=self._session_factory)
        complaint_repo = SqlAlchemyComplaintRepository(
            session_factory=self._session_factory
        )
        interaction_repo = SqlAlchemyInteractionRepository(
            session_factory=self._session_factory
        )
        return (
            UserRoleService(user_repo=user_repo),
            ComplaintService(complaint_repo=complaint_repo),
            InteractionService(interaction_repo=interaction_repo),
        )

    def build_outbox_deps(
        self,
    ) -> tuple[OutboxPublisher, KafkaOrderActivationPublisher | None]:
        """OutboxPublisher and optional KafkaOrderActivationPublisher for outbox processor."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for outbox.")
        order_repo = SqlAlchemyOrderRepository(session_factory=self._session_factory)
        outbox_repo = SqlAlchemyOutboxRepository(session_factory=self._session_factory)
        outbox_publisher = OutboxPublisher(
            outbox_repo=outbox_repo, order_repo=order_repo
        )
        kafka_publisher: KafkaOrderActivationPublisher | None = None
        if self._config.kafka.kafka_enabled:
            kafka_publisher = KafkaOrderActivationPublisher(
                bootstrap_servers=self._config.kafka.kafka_bootstrap_servers,
                topic=self._config.kafka.kafka_topic,
            )
        return (outbox_publisher, kafka_publisher)

    def build_instagram_verification_service(self) -> InstagramVerificationService:
        """InstagramVerificationService for webhook."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for Instagram verification.")
        user_repo = SqlAlchemyUserRepository(session_factory=self._session_factory)
        blogger_repo = SqlAlchemyBloggerProfileRepository(
            session_factory=self._session_factory
        )
        verification_repo = SqlAlchemyInstagramVerificationRepository(
            session_factory=self._session_factory
        )
        instagram_api_client = self.build_instagram_api_client()
        return InstagramVerificationService(
            user_repo=user_repo,
            blogger_repo=blogger_repo,
            verification_repo=verification_repo,
            instagram_api_client=instagram_api_client,
        )

    def build_metrics_collector(self) -> MetricsCollector:
        """Create metrics collector."""
        return MetricsCollector()

    def build_instagram_api_client(self):
        """Create Instagram Graph API client if configured."""
        if (
            not self._config.instagram.instagram_access_token
            or not self._config.instagram.instagram_access_token.strip()
        ):
            return None
        from ugc_bot.infrastructure.instagram.graph_api_client import (
            HttpInstagramGraphApiClient,
        )

        return HttpInstagramGraphApiClient(
            access_token=self._config.instagram.instagram_access_token,
            base_url=self._config.instagram.instagram_api_base_url,
        )

    def build_bot_services(self) -> dict:
        """Build all services for the bot dispatcher."""
        if not self._session_factory:
            raise ValueError("DATABASE_URL is required for bot services.")
        repos = self.build_repos()
        metrics_collector = self.build_metrics_collector()
        instagram_api_client = self.build_instagram_api_client()
        outbox_publisher = OutboxPublisher(
            outbox_repo=repos["outbox_repo"], order_repo=repos["order_repo"]
        )

        return {
            "metrics_collector": metrics_collector,
            "user_role_service": UserRoleService(
                user_repo=repos["user_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "blogger_registration_service": BloggerRegistrationService(
                user_repo=repos["user_repo"],
                blogger_repo=repos["blogger_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "advertiser_registration_service": AdvertiserRegistrationService(
                user_repo=repos["user_repo"],
                advertiser_repo=repos["advertiser_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "instagram_verification_service": InstagramVerificationService(
                user_repo=repos["user_repo"],
                blogger_repo=repos["blogger_repo"],
                verification_repo=repos["instagram_repo"],
                instagram_api_client=instagram_api_client,
                transaction_manager=self._transaction_manager,
            ),
            "order_service": OrderService(
                user_repo=repos["user_repo"],
                advertiser_repo=repos["advertiser_repo"],
                order_repo=repos["order_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "offer_dispatch_service": OfferDispatchService(
                user_repo=repos["user_repo"],
                blogger_repo=repos["blogger_repo"],
                order_repo=repos["order_repo"],
                transaction_manager=self._transaction_manager,
            ),
            "offer_response_service": OfferResponseService(
                order_repo=repos["order_repo"],
                response_repo=repos["order_response_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "interaction_service": InteractionService(
                interaction_repo=repos["interaction_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "payment_service": PaymentService(
                user_repo=repos["user_repo"],
                advertiser_repo=repos["advertiser_repo"],
                order_repo=repos["order_repo"],
                payment_repo=repos["payment_repo"],
                broadcaster=NoopOfferBroadcaster(),
                outbox_publisher=outbox_publisher,
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
            "contact_pricing_service": ContactPricingService(
                pricing_repo=repos["pricing_repo"],
                transaction_manager=self._transaction_manager,
            ),
            "profile_service": ProfileService(
                user_repo=repos["user_repo"],
                blogger_repo=repos["blogger_repo"],
                advertiser_repo=repos["advertiser_repo"],
                transaction_manager=self._transaction_manager,
            ),
            "complaint_service": ComplaintService(
                complaint_repo=repos["complaint_repo"],
                metrics_collector=metrics_collector,
                transaction_manager=self._transaction_manager,
            ),
        }
