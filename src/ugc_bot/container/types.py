"""Type definitions for container and service factories."""

from typing import Any, NotRequired, TypedDict

from ugc_bot.application.ports import CountryRepository, LanguageRepository
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
from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.correction_service import CorrectionService
from ugc_bot.application.services.correction_view_service import (
    CorrectionViewService,
)
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.exchange_rate_service import (
    ExchangeRateService,
)
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.application.services.messenger_linking_service import (
    MessengerLinkingService,
)
from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseService,
)
from ugc_bot.application.services.order_intake_service import OrderIntakeService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.partner_view_service import PartnerViewService
from ugc_bot.application.services.payment_service import PaymentService
from ugc_bot.application.services.payout_service import PayoutService
from ugc_bot.application.services.payout_view_service import PayoutViewService
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.rate_override_service import (
    RateOverrideService,
)
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.selection_view_service import (
    SelectionViewService,
)
from ugc_bot.application.services.social_account_service import (
    SocialAccountService,
)
from ugc_bot.application.services.support_service import SupportService
from ugc_bot.application.services.user_role_service import UserRoleService


class BotServices(TypedDict):
    """Typed structure for bot dispatcher services and dependencies."""

    checkout_service: NotRequired[Any]
    legacy_financial_case_service: Any
    metrics_collector: Any
    content_moderation_service: ContentModerationService
    user_role_service: UserRoleService
    financial_review_service: NotRequired[Any]
    manual_grant_service: NotRequired[Any]
    manual_grant_sweep: NotRequired[Any]
    debt_recovery_service: NotRequired[Any]
    partner_admin_service: NotRequired[Any]
    replacement_service: NotRequired[Any]
    partner_view_service: PartnerViewService | None
    selection_maturity_service: NotRequired[Any]
    selection_view_service: SelectionViewService | None
    campaign_summary_service: CampaignSummaryService | None
    campaign_analytics_service: NotRequired[Any]
    accompaniment_refund_service: NotRequired[Any]
    campaign_submission_service: NotRequired[Any]
    campaign_moderation_service: NotRequired[Any]
    campaign_response_service: NotRequired[Any]
    campaign_capacity_service: NotRequired[Any]
    campaign_delivery_service: NotRequired[Any]
    campaign_service: CampaignFoundationService | None
    campaign_review_service: CampaignReviewService | None
    campaign_audience_service: CampaignAudienceService | None
    payout_service: PayoutService | None
    correction_service: CorrectionService | None
    correction_view_service: CorrectionViewService | None
    payout_view_service: PayoutViewService | None
    messenger_linking_service: MessengerLinkingService | None
    rate_override_service: RateOverrideService | None
    blogger_registration_service: BloggerRegistrationService
    advertiser_registration_service: AdvertiserRegistrationService
    instagram_verification_service: InstagramVerificationService
    social_account_service: SocialAccountService | None
    collaboration_service: CollaborationService | None
    creator_identity_history_service: CreatorIdentityHistoryService | None
    subscription_service: NotRequired[Any]
    order_intake_service: OrderIntakeService | None
    order_service: OrderService
    offer_dispatch_service: OfferDispatchService
    blogger_rating_service: BloggerRatingService
    offer_response_service: OfferResponseService
    interaction_service: InteractionService
    payment_service: PaymentService
    contact_pricing_service: ContactPricingService
    profile_service: ProfileService
    complaint_service: ComplaintService
    nps_service: NpsService
    referral_service: ReferralService
    referral_income_service: ReferralIncomeService
    issue_lock_manager: Any
    offer_response_rate_limiter: Any
    geocode_public_rate_limiter: Any
    order_repo: Any
    offer_dispatch_repo: Any
    interaction_repo: Any
    user_repo: Any
    user_referral_binding_repo: Any
    user_referral_pending_repo: Any
    payout_request_repo: Any
    outbox_publisher: OutboxPublisher
    transaction_manager: Any
    max_order_price: float
    allowed_blogger_counts: frozenset[int]
    payment_currency: str
    currency_symbol: str
    default_locale: str
    bot_texts_service: BotTextsService
    country_repo: CountryRepository
    language_repo: LanguageRepository
    manager_service: ManagerService
    manager_order_repo: Any
    exchange_rate_service: ExchangeRateService | None
    support_service: SupportService
