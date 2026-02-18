"""Logging configuration helpers."""

import json
import logging
import os
from typing import Any

NOISY_LOGGERS: tuple[str, ...] = (
    "aiokafka",
    "aiokafka.consumer.group_coordinator",
    "aiokafka.consumer.consumer",
    "aiogram.event",
    "aiosqlite",
    "urllib3",
    "httpx",
)


def suppress_noisy_loggers(level: int = logging.WARNING) -> None:
    """Set third-party noisy loggers to WARNING to reduce log noise."""
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


class EnvLevelFilter(logging.Filter):
    """Filter log records below LOG_LEVEL env threshold.

    Used by Uvicorn --log-config for JSON formatter respecting LOG_LEVEL.
    """

    def __init__(
        self, env_var: str = "LOG_LEVEL", default: str = "INFO"
    ) -> None:
        super().__init__()
        raw = os.getenv(env_var, default).strip().upper()
        self._min_level = logging._nameToLevel.get(raw, logging.INFO)

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True if record should be logged."""

        return record.levelno >= self._min_level


class GroupCoordinatorErrorToWarningFilter(logging.Filter):
    """Downgrade GroupCoordinatorNotAvailableError from ERROR to WARNING.

    This transient error often occurs at startup before Kafka broker is ready
    and triggers false alerts. Converting to WARNING prevents alert noise.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Return True, optionally downgrading ERROR to WARNING."""
        if (
            record.name == "aiokafka.consumer.group_coordinator"
            and record.levelno == logging.ERROR
            and "GroupCoordinator" in record.getMessage()
        ):
            record.levelno = logging.WARNING
            record.levelname = "WARNING"
        return True


class HealthMetricsFilter(logging.Filter):
    """Filter out access logs for /health, /metrics, webhooks.

    Reduces log noise from health checks, Prometheus, Telegram and Instagram.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False for /health, /metrics and webhook paths."""
        if record.name != "uvicorn.access":
            return True
        msg = record.getMessage()
        if "POST /webhook/telegram HTTP/1.1" in msg:
            return False
        if " /webhook/instagram " in msg:
            return False
        return " /health" not in msg and " /metrics" not in msg


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging in production."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""

        log_data: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add extra fields from record
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_data.update(record.extra)
        else:
            # Extract extra fields from record attributes
            for key, value in record.__dict__.items():
                if key not in {
                    "name",
                    "msg",
                    "args",
                    "created",
                    "filename",
                    "funcName",
                    "levelname",
                    "levelno",
                    "lineno",
                    "module",
                    "msecs",
                    "message",
                    "pathname",
                    "process",
                    "processName",
                    "relativeCreated",
                    "thread",
                    "threadName",
                    "exc_info",
                    "exc_text",
                    "stack_info",
                }:
                    log_data[key] = value

        return json.dumps(log_data, ensure_ascii=False, default=str)


def configure_logging(log_level: str, json_format: bool | None = None) -> None:
    """Configure root logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_format: If True, JSON. If None, auto-detect from LOG_FORMAT.
    """

    if json_format is None:
        json_format = os.getenv("LOG_FORMAT", "").lower() == "json"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler
    handler = logging.StreamHandler()
    handler.setLevel(log_level)
    handler.addFilter(GroupCoordinatorErrorToWarningFilter())

    if json_format:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s - %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    suppress_noisy_loggers()
