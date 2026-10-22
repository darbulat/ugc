"""Service for handling complaints."""

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import (
    ComplaintAlreadyExistsError,
    ComplaintNotFoundError,
)
from ugc_bot.application.ports import ComplaintRepository, TransactionManager
from ugc_bot.domain.entities import Complaint
from ugc_bot.domain.enums import ComplaintStatus
from ugc_bot.infrastructure.db.session import with_optional_tx

logger = logging.getLogger(__name__)


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
        file_ids: list[str] | None = None,
        *,
        session: object | None = None,
    ) -> Complaint:
        """Create a new complaint."""

        async def _run(session: object | None) -> Complaint:
            if await self.complaint_repo.exists(
                order_id, reporter_id, session=session
            ):
                raise ComplaintAlreadyExistsError(
                    "Вы уже подали жалобу по этому заказу."
                )

            complaint = Complaint(
                complaint_id=uuid4(),
                reporter_id=reporter_id,
                reported_id=reported_id,
                order_id=order_id,
                reason=reason,
                status=ComplaintStatus.PENDING,
                created_at=datetime.now(timezone.utc),
                reviewed_at=None,
                file_ids=file_ids,
            )
            await self.complaint_repo.save(complaint, session=session)

            return complaint

        if session is not None:
            return await _run(session)
        complaint = await with_optional_tx(self.transaction_manager, _run)
        self.after_complaint_commit(complaint)
        return complaint

    async def get_or_create_for_interaction(
        self,
        reporter_id: UUID,
        reported_id: UUID,
        order_id: UUID,
        reason: str,
        file_ids: list[str] | None = None,
        *,
        session: object | None = None,
    ) -> tuple[Complaint, bool]:
        """Idempotent report scoped to one creator, under caller's order lock.

        A different creator/reason is a distinct report; original rows remain
        immutable. The legacy one-report-per-order API is intentionally intact.
        """
        normalized = reason.strip()
        if not normalized:
            raise ValueError("Complaint reason is required")

        async def _run(current: object | None) -> tuple[Complaint, bool]:
            for existing in await self.complaint_repo.list_by_order(
                order_id, session=current
            ):
                if (
                    existing.reporter_id == reporter_id
                    and existing.reported_id == reported_id
                    and existing.reason.strip() == normalized
                    and tuple(existing.file_ids or ()) == tuple(file_ids or ())
                ):
                    return existing, False
            complaint = Complaint(
                complaint_id=uuid4(),
                reporter_id=reporter_id,
                reported_id=reported_id,
                order_id=order_id,
                reason=normalized,
                status=ComplaintStatus.PENDING,
                created_at=datetime.now(timezone.utc),
                reviewed_at=None,
                file_ids=file_ids,
            )
            await self.complaint_repo.save(complaint, session=current)
            return complaint, True

        if session is not None:
            return await _run(session)
        result = await with_optional_tx(self.transaction_manager, _run)
        if result[1]:
            self.after_complaint_commit(result[0])
        return result

    def after_complaint_commit(self, complaint: Complaint) -> None:
        """Publish complaint logging/metrics after the owning transaction."""
        logger.warning(
            "Complaint created",
            extra={
                "complaint_id": str(complaint.complaint_id),
                "reporter_id": str(complaint.reporter_id),
                "reported_id": str(complaint.reported_id),
                "order_id": str(complaint.order_id),
                "reason": complaint.reason,
                "event_type": "complaint.created",
            },
        )

        if self.metrics_collector:
            self.metrics_collector.record_complaint_created(
                complaint_id=str(complaint.complaint_id),
                reporter_id=str(complaint.reporter_id),
                reported_id=str(complaint.reported_id),
                order_id=str(complaint.order_id),
                reason=complaint.reason,
            )

    async def get_by_id(self, complaint_id: UUID) -> Complaint | None:
        """Get complaint by ID."""

        async def _run(session: object | None):
            return await self.complaint_repo.get_by_id(
                complaint_id, session=session
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_by_order(self, order_id: UUID) -> list[Complaint]:
        """List complaints for a specific order."""

        async def _run(session: object | None):
            return list(
                await self.complaint_repo.list_by_order(
                    order_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_by_reporter(self, reporter_id: UUID) -> list[Complaint]:
        """List complaints filed by a specific user."""

        async def _run(session: object | None):
            return list(
                await self.complaint_repo.list_by_reporter(
                    reporter_id, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def list_by_status(self, status: ComplaintStatus) -> list[Complaint]:
        """List complaints by status."""

        async def _run(session: object | None):
            return list(
                await self.complaint_repo.list_by_status(
                    status, session=session
                )
            )

        return await with_optional_tx(self.transaction_manager, _run)

    async def dismiss_complaint(self, complaint_id: UUID) -> Complaint:
        """Dismiss a complaint without taking action."""

        async def _run(session: object | None) -> Complaint:
            complaint = await self.complaint_repo.get_by_id(
                complaint_id, session=session
            )
            if complaint is None:
                raise ComplaintNotFoundError("Complaint not found.")

            now = datetime.now(timezone.utc)
            dismissed = replace(
                complaint,
                status=ComplaintStatus.DISMISSED,
                reviewed_at=now,
            )
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

        return await with_optional_tx(self.transaction_manager, _run)

    async def resolve_complaint_with_action(
        self, complaint_id: UUID
    ) -> Complaint:
        """Resolve complaint by taking action (blocking user)."""

        async def _run(session: object | None) -> Complaint:
            complaint = await self.complaint_repo.get_by_id(
                complaint_id, session=session
            )
            if complaint is None:
                raise ComplaintNotFoundError("Complaint not found.")

            now = datetime.now(timezone.utc)
            resolved = replace(
                complaint,
                status=ComplaintStatus.ACTION_TAKEN,
                reviewed_at=now,
            )
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

        return await with_optional_tx(self.transaction_manager, _run)
