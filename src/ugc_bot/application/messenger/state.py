"""State storage abstraction for conversational flows."""

from typing import Any, Protocol


class StateStore(Protocol):
    """Port for storing conversational state and data."""

    async def get_state(self) -> str | None:
        """Return current state name."""

    async def set_state(self, state: str | None) -> None:
        """Set current state name (None clears)."""

    async def update_data(self, **kwargs: Any) -> None:
        """Update state data with provided kwargs."""

    async def get_data(self) -> dict[str, Any]:
        """Return state data."""

    async def clear(self) -> None:
        """Clear state and data."""
