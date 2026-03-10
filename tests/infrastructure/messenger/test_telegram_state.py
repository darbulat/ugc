"""Tests for AiogramStateStore."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.infrastructure.messenger.telegram.state import AiogramStateStore


@pytest.fixture
def fake_fsm_context() -> MagicMock:
    """Fake aiogram FSMContext."""
    ctx = MagicMock()
    ctx.get_state = AsyncMock(return_value="SomeState:waiting")
    ctx.set_state = AsyncMock()
    ctx.clear = AsyncMock()
    ctx.update_data = AsyncMock()
    ctx.get_data = AsyncMock(return_value={"key": "value"})
    return ctx


@pytest.mark.asyncio
async def test_get_state_returns_current_state(
    fake_fsm_context: MagicMock,
) -> None:
    """get_state delegates to FSMContext.get_state."""
    store = AiogramStateStore(fake_fsm_context)
    result = await store.get_state()
    assert result == "SomeState:waiting"
    fake_fsm_context.get_state.assert_called_once()


@pytest.mark.asyncio
async def test_get_state_returns_none_when_no_state(
    fake_fsm_context: MagicMock,
) -> None:
    """get_state returns None when FSMContext returns None."""
    fake_fsm_context.get_state = AsyncMock(return_value=None)
    store = AiogramStateStore(fake_fsm_context)
    result = await store.get_state()
    assert result is None


@pytest.mark.asyncio
async def test_set_state_none_clears_context(
    fake_fsm_context: MagicMock,
) -> None:
    """set_state(None) calls FSMContext.clear() and returns early."""
    store = AiogramStateStore(fake_fsm_context)
    await store.set_state(None)
    fake_fsm_context.clear.assert_called_once()
    fake_fsm_context.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_set_state_string_sets_state(
    fake_fsm_context: MagicMock,
) -> None:
    """set_state with a string delegates to FSMContext.set_state."""
    store = AiogramStateStore(fake_fsm_context)
    await store.set_state("NewState:step")
    fake_fsm_context.set_state.assert_called_once_with("NewState:step")
    fake_fsm_context.clear.assert_not_called()


@pytest.mark.asyncio
async def test_update_data_delegates(fake_fsm_context: MagicMock) -> None:
    """update_data passes kwargs to FSMContext.update_data."""
    store = AiogramStateStore(fake_fsm_context)
    await store.update_data(order_id="abc", step=2)
    fake_fsm_context.update_data.assert_called_once_with(order_id="abc", step=2)


@pytest.mark.asyncio
async def test_get_data_returns_data(fake_fsm_context: MagicMock) -> None:
    """get_data delegates to FSMContext.get_data."""
    store = AiogramStateStore(fake_fsm_context)
    result = await store.get_data()
    assert result == {"key": "value"}
    fake_fsm_context.get_data.assert_called_once()


@pytest.mark.asyncio
async def test_clear_delegates(fake_fsm_context: MagicMock) -> None:
    """clear delegates to FSMContext.clear."""
    store = AiogramStateStore(fake_fsm_context)
    await store.clear()
    fake_fsm_context.clear.assert_called_once()
