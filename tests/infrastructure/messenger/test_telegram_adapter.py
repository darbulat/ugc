"""Tests for Telegram event adapter."""

from tests.helpers.fakes import (
    FakeContact,
    FakeLocation,
    FakeMessage,
    FakeUser,
)
from ugc_bot.application.messenger.dto import IncomingMessage
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)


def test_from_message_with_contact_sets_contact_phone() -> None:
    """When message has contact, IncomingMessage.contact_phone is set."""

    adapter = TelegramEventAdapter()
    user = FakeUser(1, "u", "User")
    message = FakeMessage(
        text=None,
        user=user,
        contact=FakeContact(phone_number="+79001234567"),
    )

    result = adapter.from_message(message)

    assert isinstance(result, IncomingMessage)
    assert result.contact_phone == "+79001234567"
    assert result.text is None


def test_from_message_without_contact_contact_phone_none() -> None:
    """When message has no contact, contact_phone is None."""

    adapter = TelegramEventAdapter()
    message = FakeMessage(text="Hello", user=FakeUser(2, "u", "U"))

    result = adapter.from_message(message)

    assert result.contact_phone is None
    assert result.text == "Hello"


def test_from_message_with_location_sets_location_lat_lon() -> None:
    """Message with location sets IncomingMessage.location_lat/location_lon."""

    adapter = TelegramEventAdapter()
    message = FakeMessage(
        text=None,
        user=FakeUser(1, "u", "U"),
        location=FakeLocation(latitude=55.75, longitude=37.62),
    )

    result = adapter.from_message(message)

    assert isinstance(result, IncomingMessage)
    assert result.location_lat == 55.75
    assert result.location_lon == 37.62
