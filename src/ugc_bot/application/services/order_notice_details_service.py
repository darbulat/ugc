"""Read saved quotes for order cards and published offers."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.order_intake_ports import OrderIntakeRepository
from ugc_bot.application.order_notice_details_ports import (
    OrderNoticeDetailsRepository,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyReader,
    FinancialPolicyService,
)
from ugc_bot.domain.entities import Order
from ugc_bot.domain.financial import utc


@dataclass
class OrderNoticeDetailsService:
    repository: OrderNoticeDetailsRepository
    transactions: TransactionManager

    async def for_order(self, order: Order) -> dict | None:
        async with self.transactions.transaction() as session:
            return await self.repository.load(order.order_id, session=session)


@dataclass
class CustomerOfferService:
    repository: OrderNoticeDetailsRepository
    intake: OrderIntakeRepository
    policies: FinancialPolicyReader
    gate: FinancialPolicyService
    transactions: TransactionManager
    clock: Clock

    async def load(self, current: dict) -> dict | None:
        user_id: UUID = current["user_id"]
        async with self.transactions.transaction() as session:
            if current.get("order_id"):
                saved = await self.repository.load(
                    current["order_id"], session=session
                )
                if saved and saved["user_id"] == user_id:
                    return saved | {"saved": True}
                # An existing legacy order has no new quote. Do not imply that
                # a current public tariff changes this customer's old order.
                return None
            client = await self.intake.lock_client(user_id, session=session)
            if (
                not client
                or client.status != "active"
                or not client.is_advertiser
            ):
                return None
            now = utc(self.clock.now())
            for version in await self.intake.policy_versions(
                now, session=session
            ):
                try:
                    policy = await self.policies.load(version, session=session)
                    approved = self.gate.validate_for_capture(
                        policy=policy,
                        client_id=user_id,
                        order_created_at=now,
                        financial_version=version,
                        selection_due_at=now + timedelta(seconds=1),
                        currency=client.currency,
                        captured_at=now,
                    )
                except ValueError:
                    continue
                return dict(
                    saved=False,
                    position_count=10,
                    selection_unit_minor=approved.selection_minor,
                    selection_base_minor=10 * approved.selection_minor,
                    accompaniment_unit_minor=approved.accompaniment_minor,
                    currency=client.currency,
                )
            return None
