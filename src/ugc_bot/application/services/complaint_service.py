"""Service for handling complaints."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from ugc_bot.application.ports import ComplaintRepository
from ugc_bot.domain.entities import Complaint
from ugc_bot.domain.enums import ComplaintStatus


@dataclass(slots=True)
class ComplaintService:
    """Handle complaint creation and management."""

    complaint_repo: ComplaintRepository

    def create_complaint(
        self,
        reporter_id: UUID,
        reported_id: UUID,
        order_id: UUID,
        reason: str,
    ) -> Complaint:
        """Create a new complaint."""

        # Check if reporter already filed a complaint for this order
        if self.complaint_repo.exists(order_id, reporter_id):
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
        self.complaint_repo.save(complaint)
        return complaint

    def get_by_id(self, complaint_id: UUID) -> Complaint | None:
        """Get complaint by ID."""

        return self.complaint_repo.get_by_id(complaint_id)

    def list_by_order(self, order_id: UUID) -> list[Complaint]:
        """List complaints for a specific order."""

        return list(self.complaint_repo.list_by_order(order_id))

    def list_by_reporter(self, reporter_id: UUID) -> list[Complaint]:
        """List complaints filed by a specific user."""

        return list(self.complaint_repo.list_by_reporter(reporter_id))
