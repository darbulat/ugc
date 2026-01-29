"""Tests for cancel handler."""

import pytest

from ugc_bot.bot.handlers.cancel import cancel_button, cancel_command
from tests.helpers.fakes import FakeFSMContext, FakeMessage


@pytest.mark.asyncio
async def test_cancel_command_clears_state() -> None:
    """Cancel command clears state."""

    message = FakeMessage(text="/cancel")
    state = FakeFSMContext(state="some")
    await cancel_command(message, state)

    assert state.cleared is True
    ans = message.answers[0]
    assert "Ввод отменен" in (ans if isinstance(ans, str) else ans[0])


@pytest.mark.asyncio
async def test_cancel_button_no_state() -> None:
    """Cancel button notifies when nothing to cancel."""

    message = FakeMessage(text="Отменить")
    state = FakeFSMContext(state=None)
    await cancel_button(message, state)

    ans = message.answers[0]
    assert "Нечего отменять" in (ans if isinstance(ans, str) else ans[0])
