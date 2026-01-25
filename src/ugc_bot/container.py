"""Shared dependency container for entrypoints."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig
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
    create_session_factory,
)
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher


class Container:
    """Centralized factory for repos and services used across entrypoints."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session_factory = (
            create_session_factory(config.database_url) if config.database_url else None
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
        if not self._config.database_url:
            raise ValueError("DATABASE_URL is required for admin.")
        return create_engine(self._config.database_url, pool_pre_ping=True)

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
        if self._config.kafka_enabled:
            kafka_publisher = KafkaOrderActivationPublisher(
                bootstrap_servers=self._config.kafka_bootstrap_servers,
                topic=self._config.kafka_topic,
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
        instagram_api_client = None
        if self._config.instagram_access_token:
            from ugc_bot.infrastructure.instagram.graph_api_client import (
                HttpInstagramGraphApiClient,
            )

            instagram_api_client = HttpInstagramGraphApiClient(
                access_token=self._config.instagram_access_token,
                base_url=self._config.instagram_api_base_url,
            )
        return InstagramVerificationService(
            user_repo=user_repo,
            blogger_repo=blogger_repo,
            verification_repo=verification_repo,
            instagram_api_client=instagram_api_client,
        )
