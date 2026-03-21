"""Tests for unified worker entry point."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_no_close_messenger_client_close_is_noop() -> None:
    """_NoCloseMessengerClient.close() does not call delegate.close()."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.close()

    delegate.close.assert_not_called()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_text() -> None:
    """_NoCloseMessengerClient delegates send_text to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_text(chat_id="123", text="hello")

    delegate.send_text.assert_called_once_with(
        chat_id="123",
        text="hello",
        keyboard=None,
        parse_mode=None,
        disable_preview=None,
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_send_text_optional_kwargs() -> None:
    """_NoCloseMessengerClient forwards optional send_text kwargs."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    keyboard = MagicMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_text(
        chat_id="123",
        text="hello",
        keyboard=keyboard,
        parse_mode="HTML",
        disable_preview=True,
    )

    delegate.send_text.assert_called_once_with(
        chat_id="123",
        text="hello",
        keyboard=keyboard,
        parse_mode="HTML",
        disable_preview=True,
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_photo() -> None:
    """_NoCloseMessengerClient delegates send_photo to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_photo(chat_id="123", file_id="file1", caption="cap")

    delegate.send_photo.assert_called_once_with(
        chat_id="123",
        file_id="file1",
        caption="cap",
        keyboard=None,
        parse_mode=None,
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_edit_text() -> None:
    """_NoCloseMessengerClient delegates edit_text to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.edit_text(
        chat_id="123", message_id="m1", text="new", keyboard=MagicMock()
    )

    delegate.edit_text.assert_called_once()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_edit_reply_markup() -> None:
    """_NoCloseMessengerClient delegates edit_reply_markup."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.edit_reply_markup(
        chat_id="123", message_id="m1", keyboard=MagicMock()
    )

    delegate.edit_reply_markup.assert_called_once()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_answer_callback() -> None:
    """_NoCloseMessengerClient delegates answer_callback."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.answer_callback(callback_id="cb1", text="ok", show_alert=True)

    delegate.answer_callback.assert_called_once_with(
        callback_id="cb1", text="ok", show_alert=True
    )


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_invoice() -> None:
    """_NoCloseMessengerClient delegates send_invoice to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    invoice = MagicMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_invoice(chat_id="123", invoice=invoice)

    delegate.send_invoice.assert_called_once_with(
        chat_id="123", invoice=invoice
    )


@pytest.mark.asyncio
async def test_run_with_restart_restarts_on_exception() -> None:
    """_run_with_restart re-runs coro_factory after an exception."""
    from ugc_bot.worker import _run_with_restart

    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("transient error")
        # Second call exits the infinite loop via CancelledError (BaseException)
        raise asyncio.CancelledError

    with (
        patch("ugc_bot.worker.asyncio.sleep", new=AsyncMock()),
        pytest.raises(asyncio.CancelledError),
    ):
        await _run_with_restart("test", flaky, restart_delay=0)

    assert call_count == 2
