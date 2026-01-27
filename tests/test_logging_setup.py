"""Tests for logging setup."""

import json
import logging

import pytest

from ugc_bot.logging_setup import JSONFormatter, configure_logging


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
