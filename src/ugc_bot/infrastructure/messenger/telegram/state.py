"""Aiogram-backed state store implementation."""

from typing import Any

from aiogram.fsm.context import FSMContext

from ugc_bot.application.messenger.state import StateStore


class AiogramStateStore(StateStore):
    """State store wrapper for aiogram FSMContext."""

    def __init__(self, state: FSMContext) -> None:
        """Initialize with aiogram FSMContext."""
        self._state = state

    async def get_state(self) -> str | None:
        """Return current state name."""
        return await self._state.get_state()

    async def set_state(self, state: str | None) -> None:
        """Set current state name (None clears)."""
        if state is None:
            await self._state.clear()
            return
        await self._state.set_state(state)

    async def update_data(self, **kwargs: Any) -> None:
        """Update state data with provided kwargs."""
        await self._state.update_data(**kwargs)

    async def get_data(self) -> dict[str, Any]:
        """Return state data."""
        return await self._state.get_data()

    async def clear(self) -> None:
        """Clear state and data."""
        await self._state.clear()
