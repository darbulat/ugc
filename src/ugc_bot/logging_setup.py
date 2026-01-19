"""Logging configuration helpers."""

import logging


def configure_logging(log_level: str) -> None:
    """Configure root logging for the application."""

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
