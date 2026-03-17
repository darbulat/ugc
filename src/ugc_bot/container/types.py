"""Type definitions for container and service factories."""

from typing import Any, TypedDict

from ugc_bot.application.ports import CountryRepository, LanguageRepository
from ugc_bot.application.services.exchange_rate_service import (
    ExchangeRateService,
)
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.contact_pricing_service import (
    ContactPricingService,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.instagram_verification_service import (
    InstagramVerificationService,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.manager_service import ManagerService
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
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService


class BotServices(TypedDict):
    """Typed structure for bot dispatcher services and dependencies."""

    metrics_collector: Any
    content_moderation_service: ContentModerationService
    user_role_service: UserRoleService
    blogger_registration_service: BloggerRegistrationService
    advertiser_registration_service: AdvertiserRegistrationService
    instagram_verification_service: InstagramVerificationService
    order_service: OrderService
    offer_dispatch_service: OfferDispatchService
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
