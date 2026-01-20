from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from enum import Enum
import json
from uuid import uuid4


class OutboxEventStatus(str, Enum):
    """Status of an outbox event."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


@dataclass
class OutboxEvent:
    """Domain entity for outbox event."""
    event_type: str
    payload: dict[str, Any]
    status: OutboxEventStatus = OutboxEventStatus.PENDING
    attempts: int = 0
    next_attempt_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    id: str = field(default_factory=lambda: str(uuid4()))

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "event_type": self.event_type,
            "payload": json.dumps(self.payload),
            "status": self.status.value,
            "attempts": self.attempts,
            "next_attempt_at": self.next_attempt_at,
            "last_error": self.last_error,
            "created_at": self.created_at,
            "sent_at": self.sent_at,
        }
