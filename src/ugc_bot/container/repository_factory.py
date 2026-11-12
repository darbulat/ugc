"""Factory for creating repository instances."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.infrastructure.db.dispatch_control import SqlDispatchControl
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
from ugc_bot.infrastructure.db.repositories.campaign_review import (
    SqlAlchemyCampaignReviewRepository,
)
from ugc_bot.infrastructure.db.repositories.campaign_summary import (
    SqlAlchemyCampaignSummaryRepository,
)
from ugc_bot.infrastructure.db.repositories.campaigns import (
    SqlAlchemyCampaignRepository,
)
from ugc_bot.infrastructure.db.repositories.collaborations import (
    SqlAlchemyCollaborationRepository,
)
from ugc_bot.infrastructure.db.repositories.entitlements import (
    SqlAlchemyClientEntitlementRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    SqlAlchemyFinancialPolicyRepository,
)
from ugc_bot.infrastructure.db.repositories.identity_history import (
    SqlAlchemyCreatorIdentityHistoryRepository,
)
from ugc_bot.infrastructure.db.repositories.legacy_financial_cases import (
    SqlAlchemyLegacyFinancialCaseRepository,
)
from ugc_bot.infrastructure.db.repositories.order_intake import (
    SqlAlchemyOrderIntakeRepository,
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyFinancialDeliveryRepository,
)
from ugc_bot.infrastructure.db.repositories.paid_selection import (
    SqlAlchemyPaidSelectionRepository,
)
from ugc_bot.infrastructure.db.repositories.partner_view import (
    SqlAlchemyPartnerViewRepository,
)
from ugc_bot.infrastructure.db.repositories.rate_overrides import (
    SqlAlchemyRateOverrideRepository,
)
from ugc_bot.infrastructure.db.repositories.selection_view import (
    SqlAlchemySelectionViewRepository,
)
from ugc_bot.infrastructure.db.repositories.social import (
    SqlAlchemySocialAccountRepository,
)
from ugc_bot.infrastructure.db.repositories.work_entitlements import (
    SqlAlchemyWorkEntitlementRepository,
)


def _build_instagram_verification_repo(
    session_factory: async_sessionmaker[AsyncSession],
    redis_url: str | None = None,
) -> SqlAlchemyInstagramVerificationRepository:
    """Keep code consumption inside the SQL identity-confirmation transaction.

    The Redis argument remains accepted for existing factory callers. Pending
    Redis codes are not copied or treated as SQL confirmation evidence.
    """
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
        redis_url: Legacy setting; verification facts always use SQL.

    Returns:
        Dict of repository name to repository instance.
    """
    history_repo = SqlAlchemyCreatorIdentityHistoryRepository(session_factory)
    campaign_repo = SqlAlchemyCampaignRepository()
    return {
        "order_intake_repo": SqlAlchemyOrderIntakeRepository(),
        "collaboration_repo": SqlAlchemyCollaborationRepository(),
        "creator_identity_history_repo": history_repo,
        "client_entitlement_repo": SqlAlchemyClientEntitlementRepository(),
        "work_entitlement_repo": SqlAlchemyWorkEntitlementRepository(),
        "financial_ledger_repo": SqlAlchemyFinancialLedgerRepository(),
        "rate_override_repo": SqlAlchemyRateOverrideRepository(),
        "campaign_repo": campaign_repo,
        "campaign_review_repo": SqlAlchemyCampaignReviewRepository(
            campaign_repo
        ),
        "partner_view_repo": SqlAlchemyPartnerViewRepository(),
        "financial_item_repo": SqlAlchemyFinancialItemRepository(),
        "paid_selection_repo": SqlAlchemyPaidSelectionRepository(),
        "selection_view_repo": SqlAlchemySelectionViewRepository(),
        "campaign_summary_repo": SqlAlchemyCampaignSummaryRepository(),
        "financial_delivery_repo": SqlAlchemyFinancialDeliveryRepository(
            session_factory
        ),
        "financial_policy_repo": SqlAlchemyFinancialPolicyRepository(),
        "legacy_financial_case_repo": SqlAlchemyLegacyFinancialCaseRepository(
            session_factory
        ),
        "user_repo": SqlAlchemyUserRepository(session_factory=session_factory),
        "blogger_repo": SqlAlchemyBloggerProfileRepository(
            session_factory=session_factory
        ),
        "social_account_repo": SqlAlchemySocialAccountRepository(
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
        "dispatch_control": SqlDispatchControl(),
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
