"""Metrics collector for tracking KPI metrics."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Prometheus metrics - module level for shared registry
_BLOGGER_REGISTRATIONS = Counter(
    "ugc_blogger_registrations_total",
    "Total number of blogger registrations",
)
_ADVERTISER_REGISTRATIONS = Counter(
    "ugc_advertiser_registrations_total",
    "Total number of advertiser registrations",
)
_ORDERS_CREATED = Counter(
    "ugc_orders_created_total",
    "Total number of orders created",
)
_ORDERS_PAID = Counter(
    "ugc_orders_paid_total",
    "Total number of orders paid",
)
_PAYMENT_FAILED = Counter(
    "ugc_payment_failed_total",
    "Total number of failed payments",
)
_BLOGGER_RESPONSES = Counter(
    "ugc_blogger_responses_total",
    "Total number of blogger responses to orders",
)
_CONTACTS_SENT = Counter(
    "ugc_contacts_sent_total",
    "Total number of contacts sent to advertisers",
)
_USERS_BLOCKED = Counter(
    "ugc_users_blocked_total",
    "Total number of blocked users",
)
_COMPLAINTS_CREATED = Counter(
    "ugc_complaints_created_total",
    "Total number of complaints created",
)
_COMPLAINT_STATUS_CHANGES = Counter(
    "ugc_complaint_status_changes_total",
    "Total number of complaint status changes",
)
_INTERACTION_ISSUES = Counter(
    "ugc_interaction_issues_total",
    "Total number of interaction issues",
)
_FEEDBACK_POSTPONEMENTS = Counter(
    "ugc_feedback_postponements_total",
    "Total number of feedback postponements",
)
_ERRORS = Counter(
    "ugc_errors_total",
    "Total number of application errors",
)
_ORDER_PAYMENT_DURATION = Histogram(
    "ugc_order_payment_duration_seconds",
    "Time from order creation to payment",
    buckets=(60, 300, 900, 3600, 86400),
)
_CONTACTS_DURATION = Histogram(
    "ugc_contacts_duration_seconds",
    "Time from order creation to contacts sent",
    buckets=(60, 300, 900, 3600, 86400),
)
_REQUEST_LATENCY = Histogram(
    "ugc_request_latency_seconds",
    "Request/operation latency",
    ["operation", "success"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)


@dataclass(slots=True)
class MetricsCollector:
    """Collector for KPI metrics.

    Tracks business and technical metrics via Prometheus counters/histograms
    and structured logging. Metrics are exposed at /metrics for Prometheus.
    """

    def record_blogger_registration(self, user_id: str) -> None:
        """Record blogger registration."""
        _BLOGGER_REGISTRATIONS.inc()
        logger.info(
            "Metric: Blogger registration",
            extra={
                "metric_type": "blogger_registration",
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_advertiser_registration(self, user_id: str) -> None:
        """Record advertiser registration."""
        _ADVERTISER_REGISTRATIONS.inc()
        logger.info(
            "Metric: Advertiser registration",
            extra={
                "metric_type": "advertiser_registration",
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_order_created(
        self,
        order_id: str,
        advertiser_id: str,
        price: float,
        bloggers_needed: int,
    ) -> None:
        """Record order creation."""
        _ORDERS_CREATED.inc()
        logger.info(
            "Metric: Order created",
            extra={
                "metric_type": "order_created",
                "order_id": order_id,
                "advertiser_id": advertiser_id,
                "price": price,
                "bloggers_needed": bloggers_needed,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_order_paid(
        self,
        order_id: str,
        payment_id: str,
        amount: float,
        time_to_payment_seconds: Optional[float] = None,
    ) -> None:
        """Record order payment."""
        _ORDERS_PAID.inc()
        if time_to_payment_seconds is not None:
            _ORDER_PAYMENT_DURATION.observe(time_to_payment_seconds)
        extra = {
            "metric_type": "order_paid",
            "order_id": order_id,
            "payment_id": payment_id,
            "amount": amount,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if time_to_payment_seconds is not None:
            extra["time_to_payment_seconds"] = time_to_payment_seconds

        logger.info("Metric: Order paid", extra=extra)

    def record_payment_failed(
        self,
        order_id: str,
        reason: str,
    ) -> None:
        """Record failed payment."""
        _PAYMENT_FAILED.inc()
        logger.warning(
            "Metric: Payment failed",
            extra={
                "metric_type": "payment_failed",
                "order_id": order_id,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_blogger_response(
        self,
        order_id: str,
        blogger_id: str,
    ) -> None:
        """Record blogger response to order."""
        _BLOGGER_RESPONSES.inc()
        logger.info(
            "Metric: Blogger response",
            extra={
                "metric_type": "blogger_response",
                "order_id": order_id,
                "blogger_id": blogger_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_contacts_sent(
        self,
        order_id: str,
        blogger_id: str,
        advertiser_id: str,
        time_to_contacts_seconds: Optional[float] = None,
    ) -> None:
        """Record contacts sent to advertiser."""
        _CONTACTS_SENT.inc()
        if time_to_contacts_seconds is not None:
            _CONTACTS_DURATION.observe(time_to_contacts_seconds)
        extra: dict[str, str | float] = {
            "metric_type": "contacts_sent",
            "order_id": order_id,
            "blogger_id": blogger_id,
            "advertiser_id": advertiser_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if time_to_contacts_seconds is not None:
            extra["time_to_contacts_seconds"] = float(time_to_contacts_seconds)

        logger.info("Metric: Contacts sent", extra=extra)

    def record_user_blocked(
        self,
        user_id: str,
        reason: str,
    ) -> None:
        """Record user blocking."""
        _USERS_BLOCKED.inc()
        logger.warning(
            "Metric: User blocked",
            extra={
                "metric_type": "user_blocked",
                "user_id": user_id,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_complaint_created(
        self,
        complaint_id: str,
        reporter_id: str,
        reported_id: str,
        order_id: str,
        reason: str,
    ) -> None:
        """Record complaint creation."""
        _COMPLAINTS_CREATED.inc()
        logger.warning(
            "Metric: Complaint created",
            extra={
                "metric_type": "complaint_created",
                "complaint_id": complaint_id,
                "reporter_id": reporter_id,
                "reported_id": reported_id,
                "order_id": order_id,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_complaint_status_change(
        self,
        complaint_id: str,
        old_status: str,
        new_status: str,
    ) -> None:
        """Record complaint status change."""
        _COMPLAINT_STATUS_CHANGES.inc()
        logger.info(
            "Metric: Complaint status changed",
            extra={
                "metric_type": "complaint_status_changed",
                "complaint_id": complaint_id,
                "old_status": old_status,
                "new_status": new_status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_interaction_issue(
        self,
        interaction_id: str,
        order_id: str,
        blogger_id: str,
        advertiser_id: str,
    ) -> None:
        """Record interaction with ISSUE status."""
        _INTERACTION_ISSUES.inc()
        logger.warning(
            "Metric: Interaction issue",
            extra={
                "metric_type": "interaction_issue",
                "interaction_id": interaction_id,
                "order_id": order_id,
                "blogger_id": blogger_id,
                "advertiser_id": advertiser_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_feedback_postponement(
        self,
        interaction_id: str,
        postpone_count: int,
    ) -> None:
        """Record feedback postponement."""
        _FEEDBACK_POSTPONEMENTS.inc()
        logger.info(
            "Metric: Feedback postponement",
            extra={
                "metric_type": "feedback_postponement",
                "interaction_id": interaction_id,
                "postpone_count": postpone_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_request_latency(
        self,
        operation: str,
        duration_seconds: float,
        success: bool = True,
    ) -> None:
        """Record request/operation latency."""
        success_label = "true" if success else "false"
        _REQUEST_LATENCY.labels(
            operation=operation,
            success=success_label,
        ).observe(duration_seconds)
        logger.info(
            "Metric: Request latency",
            extra={
                "metric_type": "request_latency",
                "operation": operation,
                "duration_seconds": duration_seconds,
                "success": success,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    def record_error(
        self,
        error_type: str,
        error_message: str,
        user_id: str,
    ) -> None:
        """Record application or unexpected error."""
        _ERRORS.inc()
        logger.warning(
            "Metric: Error occurred",
            extra={
                "metric_type": "error",
                "error_type": error_type,
                "error_message": error_message,
                "user_id": user_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
