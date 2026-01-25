"""Tests for logging setup."""

import json
import logging
import os

from ugc_bot.logging_setup import JSONFormatter, configure_logging


def test_configure_logging_sets_level() -> None:
    """Configure logging without errors."""

    configure_logging("INFO")
    logger = logging.getLogger("ugc_bot")
    logger.info("test log")


def test_json_formatter_includes_message_and_extra() -> None:
    """Format log records as JSON with extras."""

    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )
    record.extra = {"request_id": "abc123"}

    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello"
    assert payload["request_id"] == "abc123"


def test_configure_logging_json_format_env() -> None:
    """Respect LOG_FORMAT env for JSON logging."""

    os.environ["LOG_FORMAT"] = "json"
    try:
        configure_logging("INFO", json_format=None)
        logger = logging.getLogger("ugc_bot.json")
        logger.info("json log")
    finally:
        os.environ.pop("LOG_FORMAT", None)
