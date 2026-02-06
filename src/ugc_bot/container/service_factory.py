"""Factory for creating application services."""

from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.fsm_draft_service import FsmDraftService
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
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.kafka.publisher import KafkaOrderActivationPublisher


def build_offer_dispatch_service(repos, transaction_manager):
    """Build OfferDispatchService for Kafka consumer."""
    return OfferDispatchService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        order_repo=repos["order_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        transaction_manager=transaction_manager,
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


def build_bot_services(
    config: AppConfig,
    repos,
    transaction_manager,
    metrics_collector,
    instagram_api_client,
    outbox_publisher,
    issue_lock_manager,
):
    """Build all services and repos for the bot dispatcher."""
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
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "advertiser_registration_service": AdvertiserRegistrationService(
            user_repo=repos["user_repo"],
            advertiser_repo=repos["advertiser_repo"],
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
            metrics_collector=metrics_collector,
            transaction_manager=transaction_manager,
        ),
        "offer_dispatch_service": OfferDispatchService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            order_repo=repos["order_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            transaction_manager=transaction_manager,
        ),
        "offer_response_service": OfferResponseService(
            order_repo=repos["order_repo"],
            response_repo=repos["order_response_repo"],
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
        "fsm_draft_service": FsmDraftService(
            draft_repo=repos["draft_repo"],
            transaction_manager=transaction_manager,
        ),
        "nps_service": NpsService(
            nps_repo=repos["nps_repo"],
            transaction_manager=transaction_manager,
        ),
        "issue_lock_manager": issue_lock_manager,
        "order_repo": repos["order_repo"],
        "order_response_repo": repos["order_response_repo"],
        "interaction_repo": repos["interaction_repo"],
    }
