"""Domain enums for the UGC bot."""

from enum import StrEnum


class MessengerType(StrEnum):
    """Supported messenger types."""

    TELEGRAM = "telegram"
    MAX = "max"
    WHATSAPP = "whatsapp"


class UserStatus(StrEnum):
    """User status for anti-fraud and access control."""

    NEW = "new"
    ACTIVE = "active"
    PAUSE = "pause"
    BLOCKED = "blocked"


class UserRole(StrEnum):
    """User role for access scenarios."""

    BLOGGER = "blogger"
    ADVERTISER = "advertiser"
    BOTH = "both"


class AudienceGender(StrEnum):
    """Audience gender filter."""

    MALE = "m"
    FEMALE = "f"
    ALL = "all"


class OrderStatus(StrEnum):
    """Order lifecycle status."""

    NEW = "new"
    ACTIVE = "active"
    CLOSED = "closed"


class InteractionStatus(StrEnum):
    """Aggregated interaction status."""

    OK = "ok"
    NO_DEAL = "no_deal"
    PENDING = "pending"
    ISSUE = "issue"


class ComplaintStatus(StrEnum):
    """Complaint review status."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    ACTION_TAKEN = "action_taken"


class PaymentStatus(StrEnum):
    """Payment status enum."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


class OutboxEventStatus(StrEnum):
    """Outbox event processing status."""

    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
