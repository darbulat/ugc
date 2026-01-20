from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, asc
from src.infrastructure.db.models.outbox_event import OutboxEventORM, OutboxEventStatus


class OutboxEventRepository:
    """Repository for outbox event persistence operations."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, event: OutboxEventORM) -> OutboxEventORM:
        """Create a new outbox event."""
        self.session.add(event)
        return event

    def get_by_id(self, event_id: str) -> Optional[OutboxEventORM]:
        """Get event by ID."""
        return self.session.query(OutboxEventORM).filter(
            OutboxEventORM.id == event_id
        ).first()

    def get_pending_for_publishing(self, limit: int = 100) -> List[OutboxEventORM]:
        """Get pending events ready for publishing."""
        now = datetime.utcnow()
        return self.session.query(OutboxEventORM).filter(
            and_(
                OutboxEventORM.status == OutboxEventStatus.PENDING,
                or_(OutboxEventORM.next_attempt_at.is_(None),
                    OutboxEventORM.next_attempt_at <= now)
            )
        ).order_by(asc(OutboxEventORM.created_at)).limit(limit).all()

    def mark_as_sent(self, event_id: str) -> None:
        """Mark event as sent."""
        event = self.get_by_id(event_id)
        if event:
            event.status = OutboxEventStatus.SENT
            event.sent_at = datetime.utcnow()
            event.attempts += 1

    def mark_as_failed(self, event_id: str, error: str, retry_after_seconds: int = 300) -> None:
        """Mark event as failed and schedule retry."""
        event = self.get_by_id(event_id)
        if event:
            event.attempts += 1
            event.last_error = error
            event.next_attempt_at = datetime.utcnow() + timedelta(seconds=retry_after_seconds)
            if event.attempts >= 5:
                event.status = OutboxEventStatus.FAILED
