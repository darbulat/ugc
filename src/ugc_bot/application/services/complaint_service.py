"""Service for handling complaints."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncContextManager, Optional, Protocol
from uuid import UUID, uuid4

from ugc_bot.application.ports import ComplaintRepository
from ugc_bot.domain.entities import Complaint
from ugc_bot.domain.enums import ComplaintStatus

logger = logging.getLogger(__name__)


class TransactionManager(Protocol):
    """Protocol for database transaction handling."""

    def transaction(self) -> AsyncContextManager[Any]:
        """Return a context manager for a transaction."""


@dataclass(slots=True)
class ComplaintService:
    """Handle complaint creation and management."""

    complaint_repo: ComplaintRepository
    metrics_collector: Optional[Any] = None
    transaction_manager: TransactionManager | None = None

    async def create_complaint(
        self,
        reporter_id: UUID,
        reported_id: UUID,
        order_id: UUID,
        reason: str,
    ) -> Complaint:
        """Create a new complaint."""

        if self.transaction_manager is None:
            if await self.complaint_repo.exists(order_id, reporter_id):
                raise ValueError("Вы уже подали жалобу по этому заказу.")
        else:
            async with self.transaction_manager.transaction() as session:
                if await self.complaint_repo.exists(
                    order_id, reporter_id, session=session
                ):
                    raise ValueError("Вы уже подали жалобу по этому заказу.")

        complaint = Complaint(
            complaint_id=uuid4(),
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=order_id,
            reason=reason,
            status=ComplaintStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            reviewed_at=None,
        )
        if self.transaction_manager is None:
            await self.complaint_repo.save(complaint)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.complaint_repo.save(complaint, session=session)

        logger.warning(
            "Complaint created",
            extra={
                "complaint_id": str(complaint.complaint_id),
                "reporter_id": str(reporter_id),
                "reported_id": str(reported_id),
                "order_id": str(order_id),
                "reason": reason,
                "event_type": "complaint.created",
            },
        )

        if self.metrics_collector:
            self.metrics_collector.record_complaint_created(
                complaint_id=str(complaint.complaint_id),
                reporter_id=str(reporter_id),
                reported_id=str(reported_id),
                order_id=str(order_id),
                reason=reason,
            )

        return complaint

    async def get_by_id(self, complaint_id: UUID) -> Complaint | None:
        """Get complaint by ID."""

        if self.transaction_manager is None:
            return await self.complaint_repo.get_by_id(complaint_id)
        async with self.transaction_manager.transaction() as session:
            return await self.complaint_repo.get_by_id(complaint_id, session=session)

    async def list_by_order(self, order_id: UUID) -> list[Complaint]:
        """List complaints for a specific order."""

        if self.transaction_manager is None:
            return list(await self.complaint_repo.list_by_order(order_id))
        async with self.transaction_manager.transaction() as session:
            return list(
                await self.complaint_repo.list_by_order(order_id, session=session)
            )

    async def list_by_reporter(self, reporter_id: UUID) -> list[Complaint]:
        """List complaints filed by a specific user."""

        if self.transaction_manager is None:
            return list(await self.complaint_repo.list_by_reporter(reporter_id))
        async with self.transaction_manager.transaction() as session:
            return list(
                await self.complaint_repo.list_by_reporter(reporter_id, session=session)
            )

    async def list_by_status(self, status: ComplaintStatus) -> list[Complaint]:
        """List complaints by status."""

        if self.transaction_manager is None:
            return list(await self.complaint_repo.list_by_status(status))
        async with self.transaction_manager.transaction() as session:
            return list(
                await self.complaint_repo.list_by_status(status, session=session)
            )

    async def dismiss_complaint(self, complaint_id: UUID) -> Complaint:
        """Dismiss a complaint without taking action."""

        if self.transaction_manager is None:
            complaint = await self.complaint_repo.get_by_id(complaint_id)
        else:
            async with self.transaction_manager.transaction() as session:
                complaint = await self.complaint_repo.get_by_id(
                    complaint_id, session=session
                )
        if complaint is None:
            raise ValueError("Complaint not found.")

        dismissed = Complaint(
            complaint_id=complaint.complaint_id,
            reporter_id=complaint.reporter_id,
            reported_id=complaint.reported_id,
            order_id=complaint.order_id,
            reason=complaint.reason,
            status=ComplaintStatus.DISMISSED,
            created_at=complaint.created_at,
            reviewed_at=datetime.now(timezone.utc),
        )
        if self.transaction_manager is None:
            await self.complaint_repo.save(dismissed)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.complaint_repo.save(dismissed, session=session)

        logger.info(
            "Complaint dismissed",
            extra={
                "complaint_id": str(complaint.complaint_id),
                "reporter_id": str(complaint.reporter_id),
                "reported_id": str(complaint.reported_id),
                "order_id": str(complaint.order_id),
                "event_type": "complaint.dismissed",
            },
        )

        if self.metrics_collector:
            self.metrics_collector.record_complaint_status_change(
                complaint_id=str(complaint.complaint_id),
                old_status=complaint.status.value,
                new_status=ComplaintStatus.DISMISSED.value,
            )

        return dismissed

    async def resolve_complaint_with_action(self, complaint_id: UUID) -> Complaint:
        """Resolve complaint by taking action (blocking user)."""

        if self.transaction_manager is None:
            complaint = await self.complaint_repo.get_by_id(complaint_id)
        else:
            async with self.transaction_manager.transaction() as session:
                complaint = await self.complaint_repo.get_by_id(
                    complaint_id, session=session
                )
        if complaint is None:
            raise ValueError("Complaint not found.")

        resolved = Complaint(
            complaint_id=complaint.complaint_id,
            reporter_id=complaint.reporter_id,
            reported_id=complaint.reported_id,
            order_id=complaint.order_id,
            reason=complaint.reason,
            status=ComplaintStatus.ACTION_TAKEN,
            created_at=complaint.created_at,
            reviewed_at=datetime.now(timezone.utc),
        )
        if self.transaction_manager is None:
            await self.complaint_repo.save(resolved)
        else:
            async with self.transaction_manager.transaction() as session:
                await self.complaint_repo.save(resolved, session=session)

        logger.warning(
            "Complaint resolved with action",
            extra={
                "complaint_id": str(complaint.complaint_id),
                "reporter_id": str(complaint.reporter_id),
                "reported_id": str(complaint.reported_id),
                "order_id": str(complaint.order_id),
                "reason": complaint.reason,
                "event_type": "complaint.action_taken",
            },
        )

        if self.metrics_collector:
            self.metrics_collector.record_complaint_status_change(
                complaint_id=str(complaint.complaint_id),
                old_status=complaint.status.value,
                new_status=ComplaintStatus.ACTION_TAKEN.value,
            )

        return resolved
