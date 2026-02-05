"""Factory for creating repository instances."""

from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyComplaintRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyFsmDraftRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyNpsRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderResponseRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
)


def build_repos(session_factory):
    """Build all SQLAlchemy repositories for the application.

    Args:
        session_factory: Async session factory from create_session_factory.

    Returns:
        Dict of repository name to repository instance.
    """
    return {
        "user_repo": SqlAlchemyUserRepository(session_factory=session_factory),
        "blogger_repo": SqlAlchemyBloggerProfileRepository(
            session_factory=session_factory
        ),
        "advertiser_repo": SqlAlchemyAdvertiserProfileRepository(
            session_factory=session_factory
        ),
        "instagram_repo": SqlAlchemyInstagramVerificationRepository(
            session_factory=session_factory
        ),
        "order_repo": SqlAlchemyOrderRepository(
            session_factory=session_factory
        ),
        "order_response_repo": SqlAlchemyOrderResponseRepository(
            session_factory=session_factory
        ),
        "interaction_repo": SqlAlchemyInteractionRepository(
            session_factory=session_factory
        ),
        "payment_repo": SqlAlchemyPaymentRepository(
            session_factory=session_factory
        ),
        "pricing_repo": SqlAlchemyContactPricingRepository(
            session_factory=session_factory
        ),
        "complaint_repo": SqlAlchemyComplaintRepository(
            session_factory=session_factory
        ),
        "outbox_repo": SqlAlchemyOutboxRepository(
            session_factory=session_factory
        ),
        "draft_repo": SqlAlchemyFsmDraftRepository(
            session_factory=session_factory
        ),
        "nps_repo": SqlAlchemyNpsRepository(session_factory=session_factory),
    }
