"""Unified worker: runs all background schedulers in one process."""

import asyncio
import logging
from typing import Any, Awaitable, Callable

from ugc_bot.application.messenger.dto import Invoice, Keyboard

logger = logging.getLogger(__name__)


class _NoCloseMessengerClient:
    """Wraps a messenger client; makes close() a no-op.

    Used to prevent feedback_scheduler.run_loop's finally block from closing
    the shared Bot session while other schedulers are still running.
    The real session is closed by worker.main() after all tasks complete.
    """

    def __init__(self, delegate: Any) -> None:
        self._d = delegate

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if keyboard is not None:
            kwargs["keyboard"] = keyboard
        if parse_mode is not None:
            kwargs["parse_mode"] = parse_mode
        if disable_preview is not None:
            kwargs["disable_preview"] = disable_preview
        await self._d.send_text(**kwargs)

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        await self._d.send_photo(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            keyboard=keyboard,
            parse_mode=parse_mode,
        )

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        await self._d.edit_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            keyboard=keyboard,
            parse_mode=parse_mode,
        )

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        await self._d.edit_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            keyboard=keyboard,
        )

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        await self._d.answer_callback(
            callback_id=callback_id,
            text=text,
            show_alert=show_alert,
        )

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        await self._d.send_invoice(chat_id=chat_id, invoice=invoice)

    async def close(self) -> None:
        """No-op: the shared Bot session is closed by worker.main()."""


async def _run_with_restart(
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    restart_delay: float = 5.0,
) -> None:
    """Run coro_factory() in an infinite loop; restart after exceptions.

    Only BaseException (e.g. CancelledError on shutdown) escapes this loop.
    That correctly propagates cancellation through asyncio.gather.
    """
    while True:
        try:
            await coro_factory()
        except Exception:
            logger.exception(
                "Scheduler %s crashed, restarting in %.0fs", name, restart_delay
            )
            await asyncio.sleep(restart_delay)
