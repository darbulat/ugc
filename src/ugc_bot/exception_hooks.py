"""Exception hooks for unhandled errors in CLI services.

Ensures unhandled exceptions are logged consistently (JSON format in production)
before the process exits, enabling Loki-based alerting.
"""

import asyncio
import logging
import sys
from types import TracebackType

logger = logging.getLogger(__name__)


def _make_excepthook(service_name: str):
    """Build sys.excepthook that logs then re-raises."""

    def _excepthook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        tb: TracebackType | None,
    ) -> None:
        logger.exception(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, tb),
            extra={"service": service_name},
        )
        sys.__excepthook__(exc_type, exc_value, tb)

    return _excepthook


def _make_asyncio_exception_handler(service_name: str):
    """Build asyncio exception handler for unhandled task exceptions."""

    def _handler(
        loop: asyncio.AbstractEventLoop,
        context: dict[str, object],
    ) -> None:
        exc = context.get("exception")
        message = context.get("message", "Unhandled exception in async task")
        if isinstance(exc, BaseException):
            logger.exception(
                str(message),
                exc_info=(type(exc), exc, exc.__traceback__),
                extra={"service": service_name},
            )
        else:
            logger.error(
                message,
                extra={
                    "service": service_name,
                    "context": {k: str(v) for k, v in context.items()},
                },
            )

    return _handler


def install_exception_hooks(service_name: str) -> None:
    """Install sys.excepthook for unhandled synchronous exceptions.

    Call this after configure_logging() in CLI service entry points.
    """
    sys.excepthook = _make_excepthook(service_name)


def install_asyncio_exception_handler(service_name: str) -> None:
    """Install asyncio exception handler for unhandled task exceptions.

    Must be called from within async code (e.g. at start of run_consumer).
    """
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_make_asyncio_exception_handler(service_name))
