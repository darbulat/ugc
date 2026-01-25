"""Tests for logging setup."""

import logging

from ugc_bot.logging_setup import configure_logging


def test_configure_logging_sets_level() -> None:
    """Configure logging without errors."""

    configure_logging("INFO")
    logger = logging.getLogger("ugc_bot")
    logger.info("test log")
