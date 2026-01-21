"""Logging configuration helpers."""

import json
import logging
import os
from typing import Any


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
        json_format: If True, use JSON format. If None, auto-detect from LOG_FORMAT env var.
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

    if json_format:
        formatter: logging.Formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s - %(message)s"
        )

    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
