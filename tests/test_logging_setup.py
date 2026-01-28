"""Tests for logging setup."""

import json
import logging

import pytest

from ugc_bot.logging_setup import EnvLevelFilter, JSONFormatter, configure_logging


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


def test_env_level_filter_respects_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
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
