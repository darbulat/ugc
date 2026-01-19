"""Tests for cancel handler."""

import pytest

from ugc_bot.bot.handlers.cancel import cancel_button, cancel_command


class FakeMessage:
    """Minimal message stub."""

    def __init__(self, text: str | None) -> None:
        self.text = text
        self.answers: list[str] = []

    async def answer(self, text: str, reply_markup=None) -> None:  # type: ignore[no-untyped-def]
        """Capture response."""

        self.answers.append(text)


class FakeFSMContext:
    """Minimal FSM context for tests."""

    def __init__(self, state: str | None) -> None:
        self._state = state
        self.cleared = False

    async def get_state(self) -> str | None:  # type: ignore[no-untyped-def]
        """Return current state."""

        return self._state

    async def clear(self) -> None:
        """Clear current state."""

        self._state = None
        self.cleared = True


@pytest.mark.asyncio
async def test_cancel_command_clears_state() -> None:
    """Cancel command clears state."""

    message = FakeMessage(text="/cancel")
    state = FakeFSMContext(state="some")
    await cancel_command(message, state)

    assert state.cleared is True
    assert "Ввод отменен" in message.answers[0]


@pytest.mark.asyncio
async def test_cancel_button_no_state() -> None:
    """Cancel button notifies when nothing to cancel."""

    message = FakeMessage(text="Отменить")
    state = FakeFSMContext(state=None)
    await cancel_button(message, state)

    assert "Нечего отменять" in message.answers[0]
