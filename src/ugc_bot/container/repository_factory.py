"""Factory for creating repository instances."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyBloggerRatingRepository,
    SqlAlchemyBotTextsRepository,
    SqlAlchemyComplaintRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyCountryRepository,
    SqlAlchemyInstagramStatsRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyLanguageRepository,
    SqlAlchemyManagerOrderRepository,
    SqlAlchemyNpsRepository,
    SqlAlchemyOfferDispatchRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyPayoutRequestRepository,
    SqlAlchemyReferralIncomeEntryRepository,
    SqlAlchemySupportMessageRepository,
    SqlAlchemyUserReferralBindingRepository,
    SqlAlchemyUserReferralPendingRepository,
    SqlAlchemyUserRepository,
    SqlReferralOrderIncomeLoader,
)

logger = logging.getLogger(__name__)


def _build_instagram_verification_repo(
    session_factory: async_sessionmaker[AsyncSession],
    redis_url: str | None = None,
):
    """Build Instagram verification repository (Redis or SQL)."""
    if redis_url:
        try:
            from ugc_bot.infrastructure.redis_verification import (
                RedisInstagramVerificationRepository,
            )

            logger.info("Using Redis for Instagram verification codes")
            return RedisInstagramVerificationRepository(redis_url=redis_url)
        except ImportError:  # pragma: no cover
            logger.debug(
                "redis package not installed, using SQL for verification codes"
            )
    return SqlAlchemyInstagramVerificationRepository(
        session_factory=session_factory
    )


def build_repos(
    session_factory: async_sessionmaker[AsyncSession],
    redis_url: str | None = None,
) -> dict[str, object]:
    """Build all repositories for the application.

    Args:
        session_factory: Async session factory from create_session_factory.
        redis_url: Optional Redis URL for Redis-backed repositories.

    Returns:
        Dict of repository name to repository instance.
    """
    return {
        "user_repo": SqlAlchemyUserRepository(session_factory=session_factory),
        "blogger_repo": SqlAlchemyBloggerProfileRepository(
            session_factory=session_factory
        ),
        "blogger_rating_repo": SqlAlchemyBloggerRatingRepository(
            session_factory=session_factory
        ),
        "advertiser_repo": SqlAlchemyAdvertiserProfileRepository(
            session_factory=session_factory
        ),
        "instagram_repo": _build_instagram_verification_repo(
            session_factory, redis_url
        ),
        "instagram_stats_repo": SqlAlchemyInstagramStatsRepository(
            session_factory=session_factory
        ),
        "order_repo": SqlAlchemyOrderRepository(
            session_factory=session_factory
        ),
        "offer_dispatch_repo": SqlAlchemyOfferDispatchRepository(
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
        "bot_texts_repo": SqlAlchemyBotTextsRepository(
            session_factory=session_factory
        ),
        "complaint_repo": SqlAlchemyComplaintRepository(
            session_factory=session_factory
        ),
        "outbox_repo": SqlAlchemyOutboxRepository(
            session_factory=session_factory
        ),
        "nps_repo": SqlAlchemyNpsRepository(session_factory=session_factory),
        "user_referral_binding_repo": (
            SqlAlchemyUserReferralBindingRepository(
                session_factory=session_factory
            )
        ),
        "user_referral_pending_repo": SqlAlchemyUserReferralPendingRepository(
            session_factory=session_factory
        ),
        "payout_request_repo": SqlAlchemyPayoutRequestRepository(
            session_factory=session_factory
        ),
        "referral_order_income_loader": SqlReferralOrderIncomeLoader(
            session_factory=session_factory
        ),
        "country_repo": SqlAlchemyCountryRepository(
            session_factory=session_factory
        ),
        "language_repo": SqlAlchemyLanguageRepository(
            session_factory=session_factory
        ),
        "manager_order_repo": SqlAlchemyManagerOrderRepository(
            session_factory=session_factory
        ),
        "referral_income_entry_repo": SqlAlchemyReferralIncomeEntryRepository(
            session_factory=session_factory
        ),
        "support_message_repo": SqlAlchemySupportMessageRepository(
            session_factory=session_factory
        ),
    }
