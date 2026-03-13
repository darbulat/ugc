"""Tests for logging setup."""

import json
import logging

import pytest

from ugc_bot.logging_setup import (
    NOISY_LOGGERS,
    EnvLevelFilter,
    GroupCoordinatorErrorToWarningFilter,
    HealthMetricsFilter,
    JSONFormatter,
    configure_logging,
    suppress_noisy_loggers,
)


def test_suppress_noisy_loggers_sets_warning_level() -> None:
    """suppress_noisy_loggers sets WARNING level for all noisy loggers."""
    suppress_noisy_loggers()
    for name in NOISY_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_configure_logging_sets_level() -> None:
    """Configure logging without errors."""

    configure_logging("INFO")
    logger = logging.getLogger("ugc_bot")
    logger.info("test log")


def test_configure_logging_json_format_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configure logging with JSON format enabled."""

    monkeypatch.setenv("LOG_FORMAT", "json")
    configure_logging("DEBUG")
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler.formatter, JSONFormatter)


def test_json_formatter_includes_extra_fields() -> None:
    """JSON formatter includes extra attributes."""

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-123"
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello"
    assert payload["request_id"] == "req-123"


def test_json_formatter_with_extra_dict() -> None:
    """JSON formatter merges record.extra dict."""

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.extra = {"user_id": "user-1"}
    payload = json.loads(formatter.format(record))
    assert payload["user_id"] == "user-1"


def test_env_level_filter_respects_log_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """EnvLevelFilter drops records below LOG_LEVEL."""

    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    flt = EnvLevelFilter()

    info_rec = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=(),
        exc_info=None,
    )
    warn_rec = logging.LogRecord(
        name="t",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="x",
        args=(),
        exc_info=None,
    )

    assert flt.filter(info_rec) is False
    assert flt.filter(warn_rec) is True


def test_health_metrics_filter_blocks_health_access_logs() -> None:
    """HealthMetricsFilter blocks uvicorn.access logs for /health."""
    flt = HealthMetricsFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - "GET /health HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is False


def test_health_metrics_filter_blocks_metrics_access_logs() -> None:
    """HealthMetricsFilter blocks uvicorn.access logs for /metrics."""
    flt = HealthMetricsFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - "GET /metrics HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is False


def test_health_metrics_filter_blocks_telegram_webhook_access_logs() -> None:
    """HealthMetricsFilter blocks uvicorn.access for POST /webhook/telegram."""
    flt = HealthMetricsFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - "POST /webhook/telegram HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is False


def test_health_metrics_filter_blocks_instagram_webhook_access_logs() -> None:
    """HealthMetricsFilter blocks uvicorn.access for /webhook/instagram."""
    flt = HealthMetricsFilter()
    for method, msg in (
        ("GET", '127.0.0.1 - "GET /webhook/instagram HTTP/1.1" 200'),
        ("POST", '127.0.0.1 - "POST /webhook/instagram HTTP/1.1" 200'),
    ):
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        assert (
            flt.filter(record) is False
        ), f"{method} /webhook/instagram should be filtered"


def test_health_metrics_filter_allows_other_access_logs() -> None:
    """HealthMetricsFilter allows uvicorn.access logs for other paths."""
    flt = HealthMetricsFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='127.0.0.1 - "GET /api/orders HTTP/1.1" 200',
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is True


def test_group_coordinator_error_downgraded_to_warning() -> None:
    """GroupCoordinatorErrorToWarningFilter downgrades ERROR to WARNING."""
    flt = GroupCoordinatorErrorToWarningFilter()
    record = logging.LogRecord(
        name="aiokafka.consumer.group_coordinator",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Group Coordinator Request failed: GroupCoordinatorNotAvailable",
        args=(),
        exc_info=None,
    )
    flt.filter(record)
    assert record.levelno == logging.WARNING
    assert record.levelname == "WARNING"


def test_group_coordinator_filter_ignores_other_loggers() -> None:
    """GroupCoordinatorErrorToWarningFilter does not modify other loggers."""
    flt = GroupCoordinatorErrorToWarningFilter()
    record = logging.LogRecord(
        name="aiokafka.consumer.consumer",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Some other error",
        args=(),
        exc_info=None,
    )
    flt.filter(record)
    assert record.levelno == logging.ERROR
    assert record.levelname == "ERROR"


def test_health_metrics_filter_allows_non_access_logs() -> None:
    """HealthMetricsFilter allows non-uvicorn.access logs."""
    flt = HealthMetricsFilter()
    record = logging.LogRecord(
        name="ugc_bot.app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Health check passed",
        args=(),
        exc_info=None,
    )
    assert flt.filter(record) is True
