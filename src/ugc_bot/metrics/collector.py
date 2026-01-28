"""Metrics collector for tracking KPI metrics."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class MetricsCollector:
    """Collector for KPI metrics.

    This collector tracks business and technical metrics by logging them
    in structured format. Metrics can be extracted from logs for analysis
    or exported to Prometheus in the future.
    """

    def record_blogger_registration(self, user_id: str) -> None:
        """Record blogger registration."""
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
