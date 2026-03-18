"""SQLAlchemy repository implementations.

Re-exports all repository classes for backward-compatible imports:
    from ugc_bot.infrastructure.db.repositories import SqlAlchemyUserRepository
"""

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

from ugc_bot.infrastructure.db.repositories._shared import (
    _geometry_to_wkt,  # noqa: F401
    _get_async_session,  # noqa: F401
    _require_session,  # noqa: F401
    _resolve_session,  # noqa: F401
    _wkt_to_geometry_element,  # noqa: F401
)
from ugc_bot.infrastructure.db.repositories.instagram import (
    SqlAlchemyInstagramStatsRepository,
    SqlAlchemyInstagramVerificationRepository,
)
from ugc_bot.infrastructure.db.repositories.interactions import (
    SqlAlchemyInteractionRepository,
    SqlAlchemyOfferDispatchRepository,
)
from ugc_bot.infrastructure.db.repositories.orders import (
    SqlAlchemyContactPricingRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyPaymentRepository,
    _to_order_entity,  # noqa: F401
    _to_order_model,  # noqa: F401
)
from ugc_bot.infrastructure.db.repositories.outbox import (
    SqlAlchemyOutboxRepository,
)
from ugc_bot.infrastructure.db.repositories.platform import (
    SqlAlchemyBotTextsRepository,
    SqlAlchemyCountryRepository,
    SqlAlchemyLanguageRepository,
)
from ugc_bot.infrastructure.db.repositories.profiles import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    _to_blogger_profile_entity,  # noqa: F401
    _to_blogger_profile_model,  # noqa: F401
)
from ugc_bot.infrastructure.db.repositories.referrals import (
    SqlAlchemyPayoutRequestRepository,
    SqlAlchemyReferralIncomeEntryRepository,
    SqlAlchemyUserReferralBindingRepository,
    SqlAlchemyUserReferralPendingRepository,
    SqlReferralOrderIncomeLoader,
)
from ugc_bot.infrastructure.db.repositories.support import (
    SqlAlchemyComplaintRepository,
    SqlAlchemyManagerOrderRepository,
    SqlAlchemyNpsRepository,
)
from ugc_bot.infrastructure.db.repositories.user import (
    SqlAlchemyUserRepository,
    _to_user_entity,  # noqa: F401
    _to_user_model,  # noqa: F401
)

__all__ = [
    "AsyncSession",
    "SqlAlchemyAdvertiserProfileRepository",
    "SqlAlchemyBloggerProfileRepository",
    "SqlAlchemyBotTextsRepository",
    "SqlAlchemyComplaintRepository",
    "SqlAlchemyContactPricingRepository",
    "SqlAlchemyCountryRepository",
    "SqlAlchemyInstagramStatsRepository",
    "SqlAlchemyInstagramVerificationRepository",
    "SqlAlchemyInteractionRepository",
    "SqlAlchemyLanguageRepository",
    "SqlAlchemyManagerOrderRepository",
    "SqlAlchemyNpsRepository",
    "SqlAlchemyOfferDispatchRepository",
    "SqlAlchemyOrderRepository",
    "SqlAlchemyOutboxRepository",
    "SqlAlchemyPaymentRepository",
    "SqlAlchemyPayoutRequestRepository",
    "SqlAlchemyReferralIncomeEntryRepository",
    "SqlAlchemyUserReferralBindingRepository",
    "SqlAlchemyUserReferralPendingRepository",
    "SqlAlchemyUserRepository",
    "SqlReferralOrderIncomeLoader",
]
