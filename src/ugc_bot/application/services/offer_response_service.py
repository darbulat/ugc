"""Service for handling offer responses."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from ugc_bot.application.errors import (
    OrderCreationError,
    OrderNotActiveError,
    OrderNotFoundError,
    PaidSelectionResponseError,
)
from ugc_bot.application.paid_selection_ports import SelectionInterest
from ugc_bot.application.ports import (
    ManagerOrderRepository,
    OfferDispatchRepository,
    OrderRepository,
    TransactionManager,
    UserRepository,
)
from ugc_bot.application.services.paid_selection_interest import (
    PaidSelectionInterestService,
)
from ugc_bot.domain.entities import OfferDispatch, Order
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class OfferResponseResult:
    """Result of a successful offer response flow."""

    order: Order
    response: OfferDispatch
    response_count: int
    order_closed: bool
    completed_at: Optional[datetime]
    accepted: bool  # True = within limit; False = overflow (analytics/reserve)
    manager_id: UUID | None = None
    delivery_queued: bool = False
    selection_assignment_id: UUID | None = None


@dataclass(slots=True)
class OfferResponseService:
    """Handle blogger responses to offers."""

    order_repo: OrderRepository
    dispatch_repo: OfferDispatchRepository
    manager_order_repo: ManagerOrderRepository | None = None
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None
    user_repo: UserRepository | None = None
    referral_income_service: Optional[Any] = None
    paid_selection_service: PaidSelectionInterestService | None = None

    async def respond(self, order_id: UUID, blogger_id: UUID) -> OfferDispatch:
        """Record response and return the updated dispatch."""

        result = await self.respond_and_finalize(order_id, blogger_id)
        return result.response

    async def list_by_order(self, order_id: UUID) -> list[OfferDispatch]:
        """List dispatches (responses) for an order within a transaction."""

        async def _run(session: object | None):
            return list(
                await self.dispatch_repo.list_responses_by_order(
                    order_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_by_blogger(
        self, blogger_id: UUID, in_offer_only: bool = False
    ) -> list[OfferDispatch]:
        """List dispatches where blogger responded (accepted is not null).

        Args:
            blogger_id: Blogger user id.
            in_offer_only: When True, return only dispatches with in_offer=True.
        """

        async def _run(session: object | None):
            return list(
                await self.dispatch_repo.list_responses_by_blogger(
                    blogger_id, session=session, in_offer_only=in_offer_only
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def count_by_order(self, order_id: UUID) -> int:
        """Count dispatches for an order."""

        async def _run(session: object | None):
            return await self.dispatch_repo.count_by_order(
                order_id, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def _get_round_robin_manager(
        self,
        order: Order,
        session: object | None,
    ) -> UUID | None:
        """Pick next manager via round-robin, or None."""
        if self.manager_order_repo is None:
            return None
        managers = await self.manager_order_repo.list_by_order(
            order.order_id, session=session
        )
        if not managers:
            return None
        return managers[order.last_round_robin_index % len(managers)].user_id

    async def _record_advertiser_referral(
        self,
        order: Order,
        advertiser_id: UUID,
        session: object | None,
    ) -> None:
        """Record advertiser referral income if applicable."""
        assert self.user_repo is not None
        advertiser = await self.user_repo.get_by_id(
            advertiser_id, session=session
        )
        if advertiser and advertiser.country:
            svc: Any = self.referral_income_service
            await svc.record_advertiser_referral_income(
                order=order,
                advertiser_id=advertiser_id,
                advertiser_country_code=advertiser.country,
                session=session,
            )

    async def respond_and_finalize(
        self, order_id: UUID, blogger_id: UUID
    ) -> OfferResponseResult:
        """Record response (accepted/in_offer) and update order in one tx."""

        if self.transaction_manager is None:
            raise ValueError(
                "OfferResponseService needs transaction_manager for atomic ops."
            )

        if self.paid_selection_service is not None:
            try:
                interest = await self.paid_selection_service.respond(
                    order_id, blogger_id
                )
            except ValueError as exc:
                raise PaidSelectionResponseError(str(exc)) from exc
            if interest is not None:
                return await self._paid_result(interest)

        return await self._respond_legacy(order_id, blogger_id)

    async def _respond_legacy(
        self, order_id: UUID, blogger_id: UUID
    ) -> OfferResponseResult:
        assert self.transaction_manager is not None
        now = datetime.now(timezone.utc)
        async with self.transaction_manager.transaction() as session:
            order = await self.order_repo.get_by_id_for_update(
                order_id, session=session
            )
            if order is None:
                raise OrderNotFoundError("Order not found.")
            if order.financial_version is not None:
                raise OrderCreationError("paid_selection_runtime_unavailable")
            accepted_count = await self.dispatch_repo.count_accepted_by_order(
                order_id, session=session
            )
            order_closed_or_inactive = order.status != OrderStatus.ACTIVE
            if (
                order_closed_or_inactive
                and accepted_count < order.bloggers_needed
            ):
                raise OrderNotActiveError("Order is not active.")
            if await self.dispatch_repo.exists_responded(
                order_id, blogger_id, session=session
            ):
                raise OrderCreationError("You already responded to this order.")

            within_limit = accepted_count < order.bloggers_needed
            manager_id = await self._get_round_robin_manager(order, session)

            await self.dispatch_repo.record_response(
                order_id,
                blogger_id,
                accepted=True,
                in_offer=within_limit,
                session=session,
                manager_id=manager_id,
            )

            if within_limit:
                response_count = accepted_count + 1
                updated = _update_order_after_response(
                    order, response_count, now=now
                )
            else:
                updated = order
                response_count = accepted_count

            # Increment round robin index if manager assigned
            if manager_id is not None:
                updated = replace(
                    updated,
                    last_round_robin_index=order.last_round_robin_index + 1,
                    updated_at=now,
                )

            if updated is not order:
                await self.order_repo.save(updated, session=session)

            if (
                updated.status == OrderStatus.CLOSED
                and self.referral_income_service
                and self.user_repo is not None
            ):
                await self._record_advertiser_referral(
                    updated, order.advertiser_id, session
                )

        if self.metrics_collector:
            self.metrics_collector.record_blogger_response(
                order_id=str(order_id),
                blogger_id=str(blogger_id),
            )

        order_closed = updated.status == OrderStatus.CLOSED
        response = OfferDispatch(
            order_id=order_id,
            blogger_id=blogger_id,
            created_at=now,
            updated_at=now,
            accepted=True,
            in_offer=within_limit,
            manager_id=manager_id,
        )
        return OfferResponseResult(
            order=updated,
            response=response,
            response_count=response_count,
            order_closed=order_closed,
            completed_at=updated.completed_at,
            accepted=within_limit,
            manager_id=manager_id,
        )

    async def _paid_result(
        self, interest: SelectionInterest
    ) -> OfferResponseResult:
        assert self.transaction_manager is not None
        assert self.paid_selection_service is not None
        async with self.transaction_manager.transaction() as session:
            order = await self.order_repo.get_by_id(
                interest.order_id, session=session
            )
            if order is None:
                raise OrderNotFoundError("Order not found.")
            count = await self.paid_selection_service.repository.count_accepted(
                interest.order_id, session=session
            )
        return OfferResponseResult(
            order=order,
            response=OfferDispatch(
                order_id=interest.order_id,
                blogger_id=interest.creator_id,
                created_at=interest.confirmed_at,
                updated_at=interest.confirmed_at,
                accepted=True,
                in_offer=interest.accepted,
                manager_id=interest.manager_id,
            ),
            response_count=count,
            order_closed=False,
            completed_at=None,
            accepted=interest.accepted,
            manager_id=interest.manager_id,
            delivery_queued=interest.accepted,
            selection_assignment_id=interest.assignment_id,
        )


def _update_order_after_response(
    order: Order, response_count: int, now: datetime
) -> Order:
    """Return updated order after a response is accepted."""

    new_status = (
        OrderStatus.CLOSED
        if response_count >= order.bloggers_needed
        else order.status
    )
    completed_at = (
        now if response_count >= order.bloggers_needed else order.completed_at
    )
    return replace(
        order,
        status=new_status,
        completed_at=completed_at,
        updated_at=now,
    )
