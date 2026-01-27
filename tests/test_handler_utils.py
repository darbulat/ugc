"""Tests for handler utilities."""

import pytest

from ugc_bot.bot.handlers.utils import RateLimiter, send_with_retry


def test_rate_limiter_allows_within_limit() -> None:
    """Allow requests within the limit."""

    limiter = RateLimiter(limit=2, window_seconds=10.0)
    assert limiter.allow("key") is True
    assert limiter.allow("key") is True
    assert limiter.allow("key") is False


@pytest.mark.asyncio
async def test_send_with_retry_success() -> None:
    """Return True on successful send."""

    class DummyBot:
        def __init__(self) -> None:
            self.calls = 0

        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.calls += 1

    bot = DummyBot()
    ok = await send_with_retry(
        bot,
        chat_id=1,
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is True
    assert bot.calls == 1


@pytest.mark.asyncio
async def test_send_with_retry_failure() -> None:
    """Return False after retries exhausted."""

    class DummyBot:
        async def send_message(self, chat_id: int, text: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            raise RuntimeError("fail")

    ok = await send_with_retry(
        DummyBot(),
        chat_id=1,
        text="hi",
        retries=2,
        delay_seconds=0.0,
        logger=__import__("logging").getLogger("test"),
    )
    assert ok is False
