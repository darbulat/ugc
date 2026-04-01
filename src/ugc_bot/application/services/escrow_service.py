"""Service for escrow hold management."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import OrderCreationError
from ugc_bot.application.ports import EscrowHoldRepository, TransactionManager
from ugc_bot.domain.entities import EscrowHold, Order, Payment
from ugc_bot.domain.enums import EscrowStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS: dict[EscrowStatus, set[EscrowStatus]] = {
    EscrowStatus.HELD: {
        EscrowStatus.RELEASED,
        EscrowStatus.REFUNDED,
        EscrowStatus.DISPUTED,
        EscrowStatus.CANCELLED,
    },
    EscrowStatus.DISPUTED: {
        EscrowStatus.RELEASED,
        EscrowStatus.REFUNDED,
    },
}


def _check_transition(current: EscrowStatus, target: EscrowStatus) -> None:
    allowed = _VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise OrderCreationError(
            f"Invalid escrow transition: {current.value} -> {target.value}"
        )


@dataclass(slots=True)
class EscrowService:
    """Manages per-blogger escrow holds within paid orders."""

    escrow_repo: EscrowHoldRepository
    transaction_manager: TransactionManager | None = None

    async def create_holds_for_order(
        self,
        payment: Payment,
        order: Order,
        session: object | None = None,
    ) -> list[EscrowHold]:
        """Create escrow holds for each blogger slot in an order.

        Called during payment confirmation. Creates `bloggers_needed` holds,
        each with amount = order.price. The blogger_id is set to the
        advertiser's ID as a placeholder until a blogger accepts.
        """
        now = datetime.now(timezone.utc)
        holds: list[EscrowHold] = []
        for _ in range(order.bloggers_needed):
            hold = EscrowHold(
                escrow_id=uuid4(),
                payment_id=payment.payment_id,
                order_id=order.order_id,
                blogger_id=order.advertiser_id,
                status=EscrowStatus.HELD,
                amount=Decimal(str(order.price)),
                currency=order.currency,
                created_at=now,
            )
            await self.escrow_repo.save(hold, session=session)
            holds.append(hold)
        logger.info(
            "Escrow holds created",
            extra={
                "order_id": str(order.order_id),
                "holds_count": len(holds),
                "amount_per_hold": str(order.price),
            },
        )
        return holds

    async def assign_interaction(
        self,
        order_id: UUID,
        blogger_id: UUID,
        interaction_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Assign an unassigned HELD escrow hold to an interaction.

        Called when a blogger accepts an offer and an Interaction is created.
        """

        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_unassigned_for_order(
                order_id, session=s
            )
            if hold is None:
                logger.warning(
                    "No unassigned escrow hold for order %s", order_id
                )
                return None
            updated = replace(
                hold,
                interaction_id=interaction_id,
                blogger_id=blogger_id,
                updated_at=datetime.now(timezone.utc),
            )
            await self.escrow_repo.save(updated, session=s)
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def release_hold(
        self,
        interaction_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Release escrow hold when interaction completes successfully."""

        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_by_interaction(
                interaction_id, session=s
            )
            if hold is None:
                return None
            _check_transition(hold.status, EscrowStatus.RELEASED)
            now = datetime.now(timezone.utc)
            updated = replace(
                hold,
                status=EscrowStatus.RELEASED,
                released_at=now,
                updated_at=now,
            )
            await self.escrow_repo.save(updated, session=s)
            logger.info(
                "Escrow released",
                extra={
                    "escrow_id": str(hold.escrow_id),
                    "interaction_id": str(interaction_id),
                },
            )
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def dispute_hold(
        self,
        interaction_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Mark escrow hold as disputed when interaction has issues."""

        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_by_interaction(
                interaction_id, session=s
            )
            if hold is None:
                return None
            _check_transition(hold.status, EscrowStatus.DISPUTED)
            updated = replace(
                hold,
                status=EscrowStatus.DISPUTED,
                updated_at=datetime.now(timezone.utc),
            )
            await self.escrow_repo.save(updated, session=s)
            logger.info(
                "Escrow disputed",
                extra={
                    "escrow_id": str(hold.escrow_id),
                    "interaction_id": str(interaction_id),
                },
            )
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def refund_hold(
        self,
        escrow_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Refund escrow hold (admin action or NO_DEAL resolution)."""

        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_by_id(escrow_id, session=s)
            if hold is None:
                return None
            _check_transition(hold.status, EscrowStatus.REFUNDED)
            now = datetime.now(timezone.utc)
            updated = replace(
                hold,
                status=EscrowStatus.REFUNDED,
                refunded_at=now,
                updated_at=now,
            )
            await self.escrow_repo.save(updated, session=s)
            logger.info(
                "Escrow refunded",
                extra={"escrow_id": str(escrow_id)},
            )
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def refund_hold_by_interaction(
        self,
        interaction_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Refund escrow hold found by interaction_id."""

        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_by_interaction(
                interaction_id, session=s
            )
            if hold is None:
                return None
            _check_transition(hold.status, EscrowStatus.REFUNDED)
            now = datetime.now(timezone.utc)
            updated = replace(
                hold,
                status=EscrowStatus.REFUNDED,
                refunded_at=now,
                updated_at=now,
            )
            await self.escrow_repo.save(updated, session=s)
            logger.info(
                "Escrow refunded by interaction",
                extra={
                    "escrow_id": str(hold.escrow_id),
                    "interaction_id": str(interaction_id),
                },
            )
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def cancel_hold_by_interaction(
        self,
        interaction_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Cancel escrow hold when interaction is deleted/cancelled."""

        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_by_interaction(
                interaction_id, session=s
            )
            if hold is None:
                return None
            _check_transition(hold.status, EscrowStatus.CANCELLED)
            updated = replace(
                hold,
                status=EscrowStatus.CANCELLED,
                updated_at=datetime.now(timezone.utc),
            )
            await self.escrow_repo.save(updated, session=s)
            logger.info(
                "Escrow cancelled",
                extra={
                    "escrow_id": str(hold.escrow_id),
                    "interaction_id": str(interaction_id),
                },
            )
            return updated

        return await with_optional_tx(self.transaction_manager, _run)

    async def admin_force_release(
        self,
        escrow_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Admin force-releases an escrow hold."""
        return await self._admin_transition(
            escrow_id, EscrowStatus.RELEASED, session
        )

    async def admin_force_refund(
        self,
        escrow_id: UUID,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        """Admin force-refunds an escrow hold."""
        return await self._admin_transition(
            escrow_id, EscrowStatus.REFUNDED, session
        )

    async def _admin_transition(
        self,
        escrow_id: UUID,
        target: EscrowStatus,
        session: object | None = None,
    ) -> Optional[EscrowHold]:
        async def _run(s: object | None) -> Optional[EscrowHold]:
            hold = await self.escrow_repo.get_by_id(escrow_id, session=s)
            if hold is None:
                return None
            _check_transition(hold.status, target)
            now = datetime.now(timezone.utc)
            updated = replace(
                hold,
                status=target,
                released_at=now
                if target == EscrowStatus.RELEASED
                else hold.released_at,
                refunded_at=now
                if target == EscrowStatus.REFUNDED
                else hold.refunded_at,
                updated_at=now,
            )
            await self.escrow_repo.save(updated, session=s)
            logger.info(
                "Admin escrow %s",
                target.value,
                extra={"escrow_id": str(escrow_id)},
            )
            return updated

        return await with_optional_tx(self.transaction_manager, _run)
