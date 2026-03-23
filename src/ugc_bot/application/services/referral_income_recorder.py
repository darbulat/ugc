"""Service for recording referral income entries."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID, uuid4

from ugc_bot.application.ports import (
    ContactPricingRepository,
    PaymentRepository,
    ReferralIncomeEntryRepository,
    UserReferralBindingRepository,
    UserRepository,
)
from ugc_bot.application.services.referral_commission import resolve_rate
from ugc_bot.domain.entities import Order, ReferralIncomeEntry
from ugc_bot.domain.enums import ReferralIncomeType

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReferralIncomeRecorder:
    """Record referral income entries for creators and advertisers."""

    user_referral_binding_repo: UserReferralBindingRepository
    user_repo: UserRepository
    referral_income_entry_repo: ReferralIncomeEntryRepository
    contact_pricing_repo: ContactPricingRepository
    payment_repo: PaymentRepository

    async def record_creator_referral_income(
        self,
        order: Order,
        creator_id: UUID,
        advertiser_country_code: str,
        session: object | None = None,
    ) -> None:
        """Record referral income for a creator's referrer (if any)."""
        binding = await self.user_referral_binding_repo.get_by_referred_user(
            creator_id, session=session
        )
        if binding is None:
            return

        already_recorded = await self.referral_income_entry_repo.exists(
            order.order_id,
            binding.referrer_user_id,
            creator_id,
            ReferralIncomeType.CREATOR,
            session=session,
        )
        if already_recorded:
            return

        country = advertiser_country_code.lower()
        pricing = await self.contact_pricing_repo.get_by_bloggers_count(
            order.bloggers_needed,
            country_code=country,
            session=session,
        )
        if pricing is None:
            logger.warning(
                "No pricing for bloggers_needed=%d country=%s",
                order.bloggers_needed,
                advertiser_country_code,
            )
            return

        payment = await self.payment_repo.get_by_order(
            order.order_id, session=session
        )
        if payment is None:
            logger.warning(
                "No payment for order_id=%s (creator referral income skipped)",
                order.order_id,
            )
            return

        creator = await self.user_repo.get_by_id(creator_id, session=session)
        if creator is None:
            return

        if order.bloggers_needed <= 0:
            return
        platform_revenue = Decimal(str(payment.amount)) / order.bloggers_needed
        rate = resolve_rate(creator, order)
        commission = (platform_revenue * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        entry = ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=binding.referrer_user_id,
            referred_user_id=creator_id,
            order_id=order.order_id,
            income_type=ReferralIncomeType.CREATOR,
            currency=pricing.currency,
            platform_revenue=platform_revenue,
            commission_rate=rate,
            commission_amount=commission,
            created_at=datetime.now(timezone.utc),
        )
        await self.referral_income_entry_repo.save(entry, session=session)

    async def record_advertiser_referral_income(
        self,
        order: Order,
        advertiser_id: UUID,
        advertiser_country_code: str,
        session: object | None = None,
    ) -> None:
        """Record referral income for an advertiser's referrer."""
        binding = await self.user_referral_binding_repo.get_by_referred_user(
            advertiser_id, session=session
        )
        if binding is None:
            return

        already_recorded = await self.referral_income_entry_repo.exists(
            order.order_id,
            binding.referrer_user_id,
            advertiser_id,
            ReferralIncomeType.ADVERTISER,
            session=session,
        )
        if already_recorded:
            return

        country = advertiser_country_code.lower()
        pricing = await self.contact_pricing_repo.get_by_bloggers_count(
            order.bloggers_needed,
            country_code=country,
            session=session,
        )
        if pricing is None:
            logger.warning(
                "No pricing for bloggers_needed=%d country=%s",
                order.bloggers_needed,
                advertiser_country_code,
            )
            return

        payment = await self.payment_repo.get_by_order(
            order.order_id, session=session
        )
        if payment is None:
            logger.warning(
                "No payment for order_id=%s (advertiser referral skipped)",
                order.order_id,
            )
            return

        advertiser = await self.user_repo.get_by_id(
            advertiser_id, session=session
        )
        if advertiser is None:
            return

        platform_revenue = Decimal(str(payment.amount))
        rate = resolve_rate(advertiser, order)
        commission = (platform_revenue * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        entry = ReferralIncomeEntry(
            entry_id=uuid4(),
            referrer_user_id=binding.referrer_user_id,
            referred_user_id=advertiser_id,
            order_id=order.order_id,
            income_type=ReferralIncomeType.ADVERTISER,
            currency=pricing.currency,
            platform_revenue=platform_revenue,
            commission_rate=rate,
            commission_amount=commission,
            created_at=datetime.now(timezone.utc),
        )
        await self.referral_income_entry_repo.save(entry, session=session)
