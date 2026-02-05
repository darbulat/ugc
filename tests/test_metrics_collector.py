"""Tests for metrics collector."""

from unittest.mock import patch

import pytest

from ugc_bot.metrics.collector import MetricsCollector


@pytest.fixture
def metrics_collector():
    """Create a metrics collector instance."""
    return MetricsCollector()


@pytest.fixture
def mock_logger():
    """Mock logger for testing."""
    with patch("ugc_bot.metrics.collector.logger") as mock:
        yield mock


class TestMetricsCollector:
    """Test metrics collector methods."""

    def test_record_blogger_registration(self, metrics_collector, mock_logger):
        """Test blogger registration metric."""
        user_id = "550e8400-e29b-41d4-a716-446655440000"
        metrics_collector.record_blogger_registration(user_id)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Blogger registration"
        assert call_args[1]["extra"]["metric_type"] == "blogger_registration"
        assert call_args[1]["extra"]["user_id"] == user_id

    def test_record_advertiser_registration(
        self, metrics_collector, mock_logger
    ):
        """Test advertiser registration metric."""
        user_id = "660e8400-e29b-41d4-a716-446655440001"
        metrics_collector.record_advertiser_registration(user_id)

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Advertiser registration"
        assert call_args[1]["extra"]["metric_type"] == "advertiser_registration"
        assert call_args[1]["extra"]["user_id"] == user_id

    def test_record_order_created(self, metrics_collector, mock_logger):
        """Test order creation metric."""
        order_id = "770e8400-e29b-41d4-a716-446655440002"
        advertiser_id = "880e8400-e29b-41d4-a716-446655440003"
        price = 15000.0
        bloggers_needed = 3

        metrics_collector.record_order_created(
            order_id=order_id,
            advertiser_id=advertiser_id,
            price=price,
            bloggers_needed=bloggers_needed,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Order created"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "order_created"
        assert extra["order_id"] == order_id
        assert extra["advertiser_id"] == advertiser_id
        assert extra["price"] == price
        assert extra["bloggers_needed"] == bloggers_needed

    def test_record_order_paid_with_time(self, metrics_collector, mock_logger):
        """Test order paid metric with time to payment."""
        order_id = "990e8400-e29b-41d4-a716-446655440004"
        payment_id = "aa0e8400-e29b-41d4-a716-446655440005"
        amount = 15000.0
        time_to_payment = 3600.5

        metrics_collector.record_order_paid(
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
            time_to_payment_seconds=time_to_payment,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Order paid"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "order_paid"
        assert extra["order_id"] == order_id
        assert extra["payment_id"] == payment_id
        assert extra["amount"] == amount
        assert extra["time_to_payment_seconds"] == time_to_payment

    def test_record_order_paid_without_time(
        self, metrics_collector, mock_logger
    ):
        """Test order paid metric without time to payment."""
        order_id = "bb0e8400-e29b-41d4-a716-446655440006"
        payment_id = "cc0e8400-e29b-41d4-a716-446655440007"
        amount = 20000.0

        metrics_collector.record_order_paid(
            order_id=order_id,
            payment_id=payment_id,
            amount=amount,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert "time_to_payment_seconds" not in extra

    def test_record_payment_failed(self, metrics_collector, mock_logger):
        """Test payment failed metric."""
        order_id = "dd0e8400-e29b-41d4-a716-446655440008"
        reason = "Insufficient funds"

        metrics_collector.record_payment_failed(
            order_id=order_id, reason=reason
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "Metric: Payment failed"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "payment_failed"
        assert extra["order_id"] == order_id
        assert extra["reason"] == reason

    def test_record_blogger_response(self, metrics_collector, mock_logger):
        """Test blogger response metric."""
        order_id = "ee0e8400-e29b-41d4-a716-446655440009"
        blogger_id = "ff0e8400-e29b-41d4-a716-446655440010"

        metrics_collector.record_blogger_response(
            order_id=order_id,
            blogger_id=blogger_id,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Blogger response"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "blogger_response"
        assert extra["order_id"] == order_id
        assert extra["blogger_id"] == blogger_id

    def test_record_contacts_sent_with_time(
        self, metrics_collector, mock_logger
    ):
        """Test contacts sent metric with time."""
        order_id = "110e8400-e29b-41d4-a716-446655440011"
        blogger_id = "220e8400-e29b-41d4-a716-446655440012"
        advertiser_id = "330e8400-e29b-41d4-a716-446655440013"
        time_to_contacts = 7200.0

        metrics_collector.record_contacts_sent(
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
            time_to_contacts_seconds=time_to_contacts,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Contacts sent"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "contacts_sent"
        assert extra["order_id"] == order_id
        assert extra["blogger_id"] == blogger_id
        assert extra["advertiser_id"] == advertiser_id
        assert extra["time_to_contacts_seconds"] == float(time_to_contacts)

    def test_record_contacts_sent_without_time(
        self, metrics_collector, mock_logger
    ):
        """Test contacts sent metric without time."""
        order_id = "440e8400-e29b-41d4-a716-446655440014"
        blogger_id = "550e8400-e29b-41d4-a716-446655440015"
        advertiser_id = "660e8400-e29b-41d4-a716-446655440016"

        metrics_collector.record_contacts_sent(
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert "time_to_contacts_seconds" not in extra

    def test_record_user_blocked(self, metrics_collector, mock_logger):
        """Test user blocked metric."""
        user_id = "770e8400-e29b-41d4-a716-446655440017"
        reason = "Multiple complaints"

        metrics_collector.record_user_blocked(user_id=user_id, reason=reason)

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "Metric: User blocked"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "user_blocked"
        assert extra["user_id"] == user_id
        assert extra["reason"] == reason

    def test_record_complaint_created(self, metrics_collector, mock_logger):
        """Test complaint created metric."""
        complaint_id = "880e8400-e29b-41d4-a716-446655440018"
        reporter_id = "990e8400-e29b-41d4-a716-446655440019"
        reported_id = "aa0e8400-e29b-41d4-a716-446655440020"
        order_id = "bb0e8400-e29b-41d4-a716-446655440021"
        reason = "Fraud"

        metrics_collector.record_complaint_created(
            complaint_id=complaint_id,
            reporter_id=reporter_id,
            reported_id=reported_id,
            order_id=order_id,
            reason=reason,
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "Metric: Complaint created"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "complaint_created"
        assert extra["complaint_id"] == complaint_id
        assert extra["reporter_id"] == reporter_id
        assert extra["reported_id"] == reported_id
        assert extra["order_id"] == order_id
        assert extra["reason"] == reason

    def test_record_complaint_status_change(
        self, metrics_collector, mock_logger
    ):
        """Test complaint status change metric."""
        complaint_id = "cc0e8400-e29b-41d4-a716-446655440022"
        old_status = "PENDING"
        new_status = "DISMISSED"

        metrics_collector.record_complaint_status_change(
            complaint_id=complaint_id,
            old_status=old_status,
            new_status=new_status,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Complaint status changed"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "complaint_status_changed"
        assert extra["complaint_id"] == complaint_id
        assert extra["old_status"] == old_status
        assert extra["new_status"] == new_status

    def test_record_interaction_issue(self, metrics_collector, mock_logger):
        """Test interaction issue metric."""
        interaction_id = "dd0e8400-e29b-41d4-a716-446655440023"
        order_id = "ee0e8400-e29b-41d4-a716-446655440024"
        blogger_id = "ff0e8400-e29b-41d4-a716-446655440025"
        advertiser_id = "110e8400-e29b-41d4-a716-446655440026"

        metrics_collector.record_interaction_issue(
            interaction_id=interaction_id,
            order_id=order_id,
            blogger_id=blogger_id,
            advertiser_id=advertiser_id,
        )

        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args
        assert call_args[0][0] == "Metric: Interaction issue"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "interaction_issue"
        assert extra["interaction_id"] == interaction_id
        assert extra["order_id"] == order_id
        assert extra["blogger_id"] == blogger_id
        assert extra["advertiser_id"] == advertiser_id

    def test_record_feedback_postponement(self, metrics_collector, mock_logger):
        """Test feedback postponement metric."""
        interaction_id = "220e8400-e29b-41d4-a716-446655440027"
        postpone_count = 2

        metrics_collector.record_feedback_postponement(
            interaction_id=interaction_id,
            postpone_count=postpone_count,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Feedback postponement"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "feedback_postponement"
        assert extra["interaction_id"] == interaction_id
        assert extra["postpone_count"] == postpone_count

    def test_record_request_latency(self, metrics_collector, mock_logger):
        """Test request latency metric."""
        operation = "order_creation"
        duration = 0.5
        success = True

        metrics_collector.record_request_latency(
            operation=operation,
            duration_seconds=duration,
            success=success,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        assert call_args[0][0] == "Metric: Request latency"
        extra = call_args[1]["extra"]
        assert extra["metric_type"] == "request_latency"
        assert extra["operation"] == operation
        assert extra["duration_seconds"] == float(duration)
        assert extra["success"] == success

    def test_record_request_latency_failed(
        self, metrics_collector, mock_logger
    ):
        """Test request latency metric for failed operation."""
        operation = "payment_processing"
        duration = 1.2
        success = False

        metrics_collector.record_request_latency(
            operation=operation,
            duration_seconds=duration,
            success=success,
        )

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args
        extra = call_args[1]["extra"]
        assert extra["success"] is False
