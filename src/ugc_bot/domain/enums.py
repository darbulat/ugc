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
    BOT_BLOCKED = "bot_blocked"
    DELETED = "deleted"


class AudienceGender(StrEnum):
    """Audience gender filter."""

    MALE = "m"
    FEMALE = "f"
    ALL = "all"


class BloggerGender(StrEnum):
    """Blogger's own gender."""

    MALE = "m"
    FEMALE = "f"


class WorkFormat(StrEnum):
    """Creator work format with brands."""

    ADS_IN_ACCOUNT = "ads_in_account"
    UGC_ONLY = "ugc_only"


class OrderType(StrEnum):
    """Order type: UGC only or UGC + placement."""

    UGC_ONLY = "ugc_only"
    UGC_PLUS_PLACEMENT = "ugc_plus_placement"


class OrderStatus(StrEnum):
    """Order lifecycle status."""

    NEW = "new"
    PENDING_MODERATION = "pending_moderation"
    ACTIVE = "active"
    CLOSED = "closed"
    DELETED = "deleted"


class InteractionStatus(StrEnum):
    """Aggregated interaction status."""

    OK = "ok"
    NO_DEAL = "no_deal"
    PENDING = "pending"
    ISSUE = "issue"
    DELETED = "deleted"


class ComplaintStatus(StrEnum):
    """Complaint review status."""

    PENDING = "pending"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"
    ACTION_TAKEN = "action_taken"
    DELETED = "deleted"


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


class ReferralIncomeType(StrEnum):
    """Type of referral income entry."""

    CREATOR = "creator"
    ADVERTISER = "advertiser"


class PayoutRequestStatus(StrEnum):
    """Payout request status for referral managers."""

    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    DELETED = "deleted"


class RejectionReason(StrEnum):
    """Reason for rejecting an offer."""

    LOW_PRICE = "low_price"
    WRONG_FORMAT = "wrong_format"
    UNINTERESTING_PRODUCT = "uninteresting_product"
    NO_TIME = "no_time"
    ALREADY_WORKING_WITH_BRAND = "already_working"
