"""Domain enums for the UGC bot."""

from enum import StrEnum


class MessengerType(StrEnum):
    """Supported messenger types."""

    TELEGRAM = "telegram"
    MAX = "max"
    WHATSAPP = "whatsapp"


class UserRole(StrEnum):
    """User roles in the system."""

    BLOGGER = "blogger"
    ADVERTISER = "advertiser"
    BOTH = "both"


class UserStatus(StrEnum):
    """User status for anti-fraud and access control."""

    NEW = "new"
    ACTIVE = "active"
    PAUSE = "pause"
    BLOCKED = "blocked"


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
