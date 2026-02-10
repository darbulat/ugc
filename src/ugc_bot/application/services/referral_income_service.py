"""Service for calculating referral manager income."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from ugc_bot.application.ports import (
    CreatorManagerBindingRepository,
    InteractionRepository,
    OrderRepository,
    OrderResponseRepository,
    PaymentRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.domain.enums import InteractionStatus, OrderStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

FIRST_YEAR_RATE = 0.10
AFTER_FIRST_YEAR_RATE = 0.03


@dataclass(slots=True)
class ManagerStats:
    """Referral manager statistics."""

    creators_count: int
    orders_count: int
    income_current_month: float
    income_total: float


def _years_since(date: datetime, reference: datetime) -> float:
    """Return years between date and reference (can be fractional)."""

    delta = reference - date
    return delta.total_seconds() / (365.25 * 24 * 3600)


def _get_rate(
    creator_created_at: datetime, order_completed_at: datetime
) -> float:
    """Return commission rate: 10% first year, 3% after."""

    years = _years_since(creator_created_at, order_completed_at)
    return FIRST_YEAR_RATE if years < 1.0 else AFTER_FIRST_YEAR_RATE


@dataclass(slots=True)
class ReferralIncomeService:
    """Calculate referral manager income from completed orders."""

    creator_manager_binding_repo: CreatorManagerBindingRepository
    order_response_repo: OrderResponseRepository
    order_repo: OrderRepository
    payment_repo: PaymentRepository
    interaction_repo: InteractionRepository
    user_repo: UserRepository
    transaction_manager: TransactionManager | None = None

    async def get_manager_stats(
        self,
        manager_id: UUID,
        now: Optional[datetime] = None,
    ) -> ManagerStats:
        """Get manager statistics: creators, orders, income.

        Income is calculated from orders where:
        - Order status is CLOSED
        - Creator is in order_responses
        - Interaction status is OK (good feedback from advertiser)
        - platform_revenue_per_creator = payment.amount / order.bloggers_needed
        - Rate: 10% first year, 3% after (from creator registration date)
        """

        if now is None:
            now = datetime.now(timezone.utc)

        async def _run(session: object | None) -> ManagerStats:
            return await self._compute_stats(manager_id, now, session)

        return await with_optional_tx(self.transaction_manager, _run)

    async def _compute_stats(
        self,
        manager_id: UUID,
        now: datetime,
        session: object | None,
    ) -> ManagerStats:
        """Compute manager stats (runs inside transaction)."""

        bindings = list(
            await self.creator_manager_binding_repo.list_by_manager(
                manager_id, session=session
            )
        )
        creators_count = len(bindings)

        income_current_month = 0.0
        income_total = 0.0
        seen_orders: set[UUID] = set()

        for binding in bindings:
            creator_id = binding.creator_user_id
            creator = await self.user_repo.get_by_id(
                creator_id, session=session
            )
            if creator is None:
                continue

            responses = list(
                await self.order_response_repo.list_by_blogger(
                    creator_id, session=session
                )
            )

            for response in responses:
                order = await self.order_repo.get_by_id(
                    response.order_id, session=session
                )
                if order is None or order.status != OrderStatus.CLOSED:
                    continue

                payment = await self.payment_repo.get_by_order(
                    order.order_id, session=session
                )
                if payment is None:
                    continue

                interaction = await self.interaction_repo.get_by_participants(
                    order_id=order.order_id,
                    blogger_id=creator_id,
                    advertiser_id=order.advertiser_id,
                    session=session,
                )
                if (
                    interaction is None
                    or interaction.status != InteractionStatus.OK
                ):
                    continue

                completed_at = order.completed_at or order.created_at
                platform_revenue_per_creator = (
                    float(payment.amount) / order.bloggers_needed
                )
                rate = _get_rate(creator.created_at, completed_at)
                commission = platform_revenue_per_creator * rate

                income_total += commission
                seen_orders.add(order.order_id)

                if (
                    completed_at.month == now.month
                    and completed_at.year == now.year
                ):
                    income_current_month += commission

        orders_count = len(seen_orders)

        return ManagerStats(
            creators_count=creators_count,
            orders_count=orders_count,
            income_current_month=round(income_current_month, 2),
            income_total=round(income_total, 2),
        )
