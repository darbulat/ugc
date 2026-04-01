"""SQLAlchemy escrow hold repository."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import EscrowHoldRepository
from ugc_bot.domain.entities import EscrowHold
from ugc_bot.domain.enums import EscrowStatus
from ugc_bot.infrastructure.db.models import EscrowHoldModel
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyEscrowHoldRepository(EscrowHoldRepository):
    """SQLAlchemy-backed escrow hold repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def get_by_id(
        self, escrow_id: UUID, session: object | None = None
    ) -> Optional[EscrowHold]:
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(EscrowHoldModel).where(
                    EscrowHoldModel.escrow_id == escrow_id
                )
            )
            row = result.scalar_one_or_none()
            return _to_escrow_entity(row) if row else None

    async def get_by_interaction(
        self, interaction_id: UUID, session: object | None = None
    ) -> Optional[EscrowHold]:
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(EscrowHoldModel).where(
                    EscrowHoldModel.interaction_id == interaction_id
                )
            )
            row = result.scalar_one_or_none()
            return _to_escrow_entity(row) if row else None

    async def get_unassigned_for_order(
        self, order_id: UUID, session: object | None = None
    ) -> Optional[EscrowHold]:
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(EscrowHoldModel)
                .where(
                    EscrowHoldModel.order_id == order_id,
                    EscrowHoldModel.status == EscrowStatus.HELD,
                    EscrowHoldModel.interaction_id.is_(None),
                )
                .limit(1)
            )
            row = result.scalar_one_or_none()
            return _to_escrow_entity(row) if row else None

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[EscrowHold]:
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(EscrowHoldModel).where(
                    EscrowHoldModel.order_id == order_id
                )
            )
            return [_to_escrow_entity(r) for r in result.scalars()]

    async def list_by_payment(
        self, payment_id: UUID, session: object | None = None
    ) -> list[EscrowHold]:
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            result = await db_session.execute(
                select(EscrowHoldModel).where(
                    EscrowHoldModel.payment_id == payment_id
                )
            )
            return [_to_escrow_entity(r) for r in result.scalars()]

    async def save(
        self, hold: EscrowHold, session: object | None = None
    ) -> None:
        model = _to_escrow_model(hold)
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.merge(model)


def _to_escrow_entity(model: EscrowHoldModel) -> EscrowHold:
    """Map escrow hold ORM model to domain entity."""
    return EscrowHold(
        escrow_id=model.escrow_id,
        payment_id=model.payment_id,
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        interaction_id=model.interaction_id,
        status=model.status,
        amount=Decimal(str(model.amount)),
        currency=model.currency,
        released_at=model.released_at,
        refunded_at=model.refunded_at,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_escrow_model(hold: EscrowHold) -> EscrowHoldModel:
    """Map domain escrow hold entity to ORM model."""
    return EscrowHoldModel(
        escrow_id=hold.escrow_id,
        payment_id=hold.payment_id,
        order_id=hold.order_id,
        blogger_id=hold.blogger_id,
        interaction_id=hold.interaction_id,
        status=hold.status,
        amount=hold.amount,
        currency=hold.currency,
        released_at=hold.released_at,
        refunded_at=hold.refunded_at,
        created_at=hold.created_at,
        updated_at=hold.updated_at,
    )
