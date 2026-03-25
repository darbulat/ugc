"""Tests for bot custom filters (TextEqualsKey)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers.fakes import FakeMessage
from ugc_bot.bot.telegram.filters import TextEqualsKey


@pytest.mark.asyncio
async def test_text_equals_key_true_when_text_matches() -> None:
    """TextEqualsKey returns True when event.text matches service.get(key)."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="Expected Text")
    event = FakeMessage(text="Expected Text")
    data = {
        "bot_texts_service": service,
        "default_locale": "ru",
    }
    filt = TextEqualsKey("btn_creator")
    result = await filt(event, data=data)
    assert result is True
    service.get.assert_awaited_once_with("btn_creator", "ru")


@pytest.mark.asyncio
async def test_text_equals_key_false_when_text_differs() -> None:
    """TextEqualsKey returns False when event.text does not match."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="Expected")
    event = FakeMessage(text="Other")
    data = {"bot_texts_service": service}
    filt = TextEqualsKey("key")
    result = await filt(event, data=data)
    assert result is False


@pytest.mark.asyncio
async def test_text_equals_key_false_when_no_service() -> None:
    """TextEqualsKey returns False when bot_texts_service missing in data."""
    event = FakeMessage(text="Any")
    data = {}
    filt = TextEqualsKey("key")
    result = await filt(event, data=data)
    assert result is False


@pytest.mark.asyncio
async def test_text_equals_key_uses_args_data_when_len_args_gt_1() -> None:
    """TextEqualsKey uses args[1] as data when len(args) > 1."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="From args")
    event = FakeMessage(text="From args")
    data = {"bot_texts_service": service, "default_locale": "en"}
    filt = TextEqualsKey("k")
    result = await filt(event, None, data)
    assert result is True
    service.get.assert_awaited_once_with("k", "en")


@pytest.mark.asyncio
async def test_text_equals_key_uses_config_locale_when_no_default_locale() -> (
    None
):
    """TextEqualsKey uses config.market.default_locale when locale absent."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="OK")
    config = MagicMock()
    config.market.default_locale = "en"
    event = FakeMessage(text="OK")
    data = {"bot_texts_service": service, "config": config}
    filt = TextEqualsKey("key")
    result = await filt(event, data=data)
    assert result is True
    service.get.assert_awaited_once_with("key", "en")


@pytest.mark.asyncio
async def test_text_equals_key_default_locale_ru_when_no_config() -> None:
    """TextEqualsKey falls back to 'ru' when no config and no default_locale."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="Text")
    event = FakeMessage(text="Text")
    data = {"bot_texts_service": service}
    filt = TextEqualsKey("key")
    result = await filt(event, data=data)
    assert result is True
    service.get.assert_awaited_once_with("key", "ru")


@pytest.mark.asyncio
async def test_text_equals_key_strips_whitespace() -> None:
    """TextEqualsKey compares stripped event.text and service.get result."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="  Label  ")
    event = FakeMessage(text="  Label  ")
    data = {"bot_texts_service": service}
    filt = TextEqualsKey("key")
    result = await filt(event, data=data)
    assert result is True


@pytest.mark.asyncio
async def test_text_equals_key_none_text_treated_as_empty() -> None:
    """TextEqualsKey treats event.text None as empty string."""
    service = AsyncMock()
    service.get = AsyncMock(return_value="")
    event = FakeMessage(text=None)
    data = {"bot_texts_service": service}
    filt = TextEqualsKey("key")
    result = await filt(event, data=data)
    assert result is True
