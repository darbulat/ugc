"""SQLAlchemy complaint, NPS, and manager order repositories."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import (
    ComplaintRepository,
    ManagerOrderRepository,
    NpsRepository,
)
from ugc_bot.domain.entities import Complaint, ManagerOrder
from ugc_bot.domain.enums import ComplaintStatus
from ugc_bot.infrastructure.db.models import (
    ComplaintModel,
    ManagerOrderModel,
    NpsResponseModel,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


@dataclass(slots=True)
class SqlAlchemyComplaintRepository(ComplaintRepository):
    """SQLAlchemy-backed complaint repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, complaint: Complaint, session: object | None = None
    ) -> None:
        """Persist complaint."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = _to_complaint_model(complaint)
            await db_session.merge(model)

    async def get_by_id(
        self, complaint_id: UUID, session: object | None = None
    ) -> Optional[Complaint]:
        """Get complaint by ID."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ComplaintModel).where(
                    ComplaintModel.complaint_id == complaint_id
                )
            )
            result = exec_result.scalar_one_or_none()
            return _to_complaint_entity(result) if result else None

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints for a specific order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ComplaintModel).where(
                    ComplaintModel.order_id == order_id
                )
            )
            results = exec_result.scalars()
            return [_to_complaint_entity(item) for item in results]

    async def list_by_reporter(
        self, reporter_id: UUID, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints filed by a specific user."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ComplaintModel).where(
                    ComplaintModel.reporter_id == reporter_id
                )
            )
            results = exec_result.scalars()
            return [_to_complaint_entity(item) for item in results]

    async def exists(
        self, order_id: UUID, reporter_id: UUID, session: object | None = None
    ) -> bool:
        """Check if reporter already filed a complaint for this order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count(ComplaintModel.complaint_id)).where(
                    ComplaintModel.order_id == order_id,
                    ComplaintModel.reporter_id == reporter_id,
                )
            )
            count = exec_result.scalar()
            return (count or 0) > 0

    async def list_by_status(
        self, status: ComplaintStatus, session: object | None = None
    ) -> Iterable[Complaint]:
        """List complaints by status."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ComplaintModel).where(ComplaintModel.status == status)
            )
            results = exec_result.scalars()
            return [_to_complaint_entity(item) for item in results]


@dataclass(slots=True)
class SqlAlchemyNpsRepository(NpsRepository):
    """SQLAlchemy-backed NPS repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self,
        user_id: UUID,
        score: int,
        comment: Optional[str] = None,
        session: object | None = None,
    ) -> None:
        """Save NPS score for a user."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = NpsResponseModel(
                user_id=user_id,
                score=score,
                comment=comment,
            )
            db_session.add(model)

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if user already gave NPS."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(NpsResponseModel)
                .where(NpsResponseModel.user_id == user_id)
            )
            count = exec_result.scalar_one()
            return int(count) > 0


@dataclass(slots=True)
class SqlAlchemyManagerOrderRepository(ManagerOrderRepository):
    """SQLAlchemy-backed manager order repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> list[ManagerOrder]:
        """List manager assignments for an order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ManagerOrderModel)
                .where(ManagerOrderModel.order_id == order_id)
                .order_by(
                    ManagerOrderModel.created_at.asc(),
                    ManagerOrderModel.user_id.asc(),
                )
            )
            results = exec_result.scalars().all()
            return [_to_manager_order_entity(m) for m in results]

    async def list_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> list[ManagerOrder]:
        """List order assignments for a manager."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ManagerOrderModel)
                .where(ManagerOrderModel.user_id == user_id)
                .order_by(ManagerOrderModel.created_at.desc())
            )
            results = exec_result.scalars().all()
            return [_to_manager_order_entity(m) for m in results]

    async def list_order_ids_by_user(
        self,
        user_id: UUID,
        limit: int = 20,
        offset: int = 0,
        session: object | None = None,
    ) -> list[UUID]:
        """List order IDs assigned to a manager with pagination."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(ManagerOrderModel.order_id)
                .where(ManagerOrderModel.user_id == user_id)
                .order_by(ManagerOrderModel.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            return list(exec_result.scalars().all())

    async def count_by_user(
        self, user_id: UUID, session: object | None = None
    ) -> int:
        """Count orders assigned to a manager."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(ManagerOrderModel)
                .where(ManagerOrderModel.user_id == user_id)
            )
            result = exec_result.scalar_one()
            return int(result)

    async def save(
        self, manager_order: ManagerOrder, session: object | None = None
    ) -> None:
        """Persist manager-order assignment."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            model = ManagerOrderModel(
                user_id=manager_order.user_id,
                order_id=manager_order.order_id,
                created_at=manager_order.created_at,
                updated_at=manager_order.updated_at,
            )
            await db_session.merge(model)

    async def delete_by_order(
        self, order_id: UUID, session: object | None = None
    ) -> None:
        """Delete all manager assignments for an order."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            await db_session.execute(
                delete(ManagerOrderModel).where(
                    ManagerOrderModel.order_id == order_id
                )
            )

    async def exists_for_user(
        self, user_id: UUID, session: object | None = None
    ) -> bool:
        """Check if manager has any order assignments."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            exec_result = await db_session.execute(
                select(func.count())
                .select_from(ManagerOrderModel)
                .where(ManagerOrderModel.user_id == user_id)
            )
            result = exec_result.scalar_one()
            return int(result) > 0


def _to_complaint_entity(model: ComplaintModel) -> Complaint:
    """Map complaint ORM model to domain entity."""
    return Complaint(
        complaint_id=model.complaint_id,
        reporter_id=model.reporter_id,
        reported_id=model.reported_id,
        order_id=model.order_id,
        reason=model.reason,
        status=model.status,
        created_at=model.created_at,
        updated_at=getattr(model, "updated_at", model.created_at),
        reviewed_at=model.reviewed_at,
        file_ids=getattr(model, "file_ids", None),
    )


def _to_complaint_model(complaint: Complaint) -> ComplaintModel:
    """Map complaint domain entity to ORM model."""
    return ComplaintModel(
        complaint_id=complaint.complaint_id,
        reporter_id=complaint.reporter_id,
        reported_id=complaint.reported_id,
        order_id=complaint.order_id,
        reason=complaint.reason,
        status=complaint.status,
        created_at=complaint.created_at,
        updated_at=complaint.updated_at or complaint.created_at,
        reviewed_at=complaint.reviewed_at,
        file_ids=complaint.file_ids,
    )


def _to_manager_order_entity(model: ManagerOrderModel) -> ManagerOrder:
    """Map manager order ORM model to domain entity."""
    return ManagerOrder(
        user_id=model.user_id,
        order_id=model.order_id,
        created_at=model.created_at,
        updated_at=getattr(model, "updated_at", None),
    )
