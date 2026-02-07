"""Tests for exception hooks."""

import asyncio
import sys

import pytest

from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)


def test_install_exception_hooks_sets_excepthook() -> None:
    """install_exception_hooks overrides sys.excepthook."""
    original = sys.excepthook
    try:
        install_exception_hooks("test-service")
        assert sys.excepthook is not original
    finally:
        sys.excepthook = original


def test_excepthook_logs_then_delegates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unhandled exception is logged via our excepthook."""
    original = sys.excepthook
    try:
        install_exception_hooks("test-service")
        exc = ValueError("test error")
        sys.excepthook(ValueError, exc, exc.__traceback__)
        assert "Unhandled exception" in caplog.text
        assert any(
            getattr(r, "service", None) == "test-service"
            for r in caplog.records
        )
    finally:
        sys.excepthook = original


@pytest.mark.asyncio
async def test_install_asyncio_exception_handler_sets_handler() -> None:
    """install_asyncio_exception_handler sets loop exception handler."""
    loop = asyncio.get_running_loop()
    original = loop.get_exception_handler()
    try:
        install_asyncio_exception_handler("test-service")
        assert loop.get_exception_handler() is not original
    finally:
        loop.set_exception_handler(original)


@pytest.mark.asyncio
async def test_asyncio_handler_logs_on_unretrieved_task_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unretrieved task exception triggers handler which logs."""
    caplog.set_level("ERROR")
    install_asyncio_exception_handler("test-service")

    async def _failing_task() -> None:
        raise RuntimeError("task failed")

    asyncio.create_task(_failing_task())
    await asyncio.sleep(0.15)
    assert "test-service" in caplog.text or "task failed" in caplog.text
