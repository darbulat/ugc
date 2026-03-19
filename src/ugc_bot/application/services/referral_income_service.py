"""Backward-compatible facade for the decomposed referral income modules.

The original monolithic ReferralIncomeService has been split into:
- referral_commission.py — pure functions and dataclasses
- referral_stats_service.py — ReferralStatsService (read-only stats)
- referral_income_recorder.py — ReferralIncomeRecorder (write entries)

This module provides ReferralIncomeService as a facade that composes
both services, preserving the original API for existing callers.

New code should import from the specific modules directly.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from ugc_bot.application.ports import (
    ContactPricingRepository,
    InteractionRepository,
    OfferDispatchRepository,
    OrderRepository,
    PaymentRepository,
    PayoutRequestRepository,
    ReferralIncomeEntryRepository,
    ReferralOrderIncomeRowLoader,
    TransactionManager,
    UserReferralBindingRepository,
    UserRepository,
)
from ugc_bot.application.services.referral_commission import (
    AFTER_FIRST_YEAR_RATE,
    FIRST_YEAR_RATE,
    MultiCurrencyReferralStats,
    UserReferralStats,
)
from ugc_bot.application.services.referral_income_recorder import (
    ReferralIncomeRecorder,
)
from ugc_bot.application.services.referral_stats_service import (
    ReferralStatsService,
)
from ugc_bot.domain.entities import Order

__all__ = [
    "AFTER_FIRST_YEAR_RATE",
    "FIRST_YEAR_RATE",
    "MultiCurrencyReferralStats",
    "ReferralIncomeRecorder",
    "ReferralIncomeService",
    "ReferralStatsService",
    "UserReferralStats",
]


@dataclass(slots=True)
class ReferralIncomeService:
    """Facade composing stats and recording services.

    Prefer importing ReferralStatsService or ReferralIncomeRecorder
    directly in new code.
    """

    user_referral_binding_repo: UserReferralBindingRepository
    offer_dispatch_repo: OfferDispatchRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    interaction_repo: InteractionRepository
    user_repo: UserRepository
    payout_request_repo: PayoutRequestRepository
    transaction_manager: TransactionManager | None = None
    referral_order_income_loader: ReferralOrderIncomeRowLoader | None = None
    referral_income_entry_repo: ReferralIncomeEntryRepository | None = None
    contact_pricing_repo: ContactPricingRepository | None = None

    def _stats(self) -> ReferralStatsService:
        return ReferralStatsService(
            user_referral_binding_repo=(self.user_referral_binding_repo),
            offer_dispatch_repo=self.offer_dispatch_repo,
            order_repo=self.order_repo,
            payment_repo=self.payment_repo,
            interaction_repo=self.interaction_repo,
            user_repo=self.user_repo,
            payout_request_repo=self.payout_request_repo,
            transaction_manager=self.transaction_manager,
            referral_order_income_loader=(self.referral_order_income_loader),
            referral_income_entry_repo=(self.referral_income_entry_repo),
        )

    def _recorder(self) -> ReferralIncomeRecorder:
        assert self.referral_income_entry_repo is not None
        assert self.contact_pricing_repo is not None
        return ReferralIncomeRecorder(
            user_referral_binding_repo=(self.user_referral_binding_repo),
            user_repo=self.user_repo,
            referral_income_entry_repo=(self.referral_income_entry_repo),
            contact_pricing_repo=self.contact_pricing_repo,
            payment_repo=self.payment_repo,
        )

    # --- Stats delegation ---

    async def get_user_referral_stats(
        self,
        user_id: UUID,
        now: Optional[datetime] = None,
        stats_limit: Optional[int] = None,
    ) -> UserReferralStats:
        return await self._stats().get_user_referral_stats(
            user_id, now=now, stats_limit=stats_limit
        )

    async def get_referral_balances_batch(
        self,
        user_ids: List[UUID],
        now: Optional[datetime] = None,
        session: object | None = None,
    ) -> Dict[UUID, tuple[float, float]]:
        return await self._stats().get_referral_balances_batch(
            user_ids, now=now, session=session
        )

    async def get_multicurrency_stats(
        self, referrer_user_id: UUID
    ) -> MultiCurrencyReferralStats:
        return await self._stats().get_multicurrency_stats(referrer_user_id)

    async def count_completed_orders_for_user(
        self,
        user_id: UUID,
        session: object | None = None,
    ) -> int:
        return await self._stats().count_completed_orders_for_user(
            user_id, session=session
        )

    async def count_completed_orders_by_user_ids(
        self,
        user_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, int]:
        return await self._stats().count_completed_orders_by_user_ids(
            user_ids, session=session
        )

    # --- Recording delegation ---

    async def record_creator_referral_income(
        self,
        order: Order,
        creator_id: UUID,
        advertiser_country_code: str,
        session: object | None = None,
    ) -> None:
        return await self._recorder().record_creator_referral_income(
            order=order,
            creator_id=creator_id,
            advertiser_country_code=advertiser_country_code,
            session=session,
        )

    async def record_advertiser_referral_income(
        self,
        order: Order,
        advertiser_id: UUID,
        advertiser_country_code: str,
        session: object | None = None,
    ) -> None:
        return await self._recorder().record_advertiser_referral_income(
            order=order,
            advertiser_id=advertiser_id,
            advertiser_country_code=advertiser_country_code,
            session=session,
        )
