"""Safe frozen contact rendering and default-off production worker factory."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.unit.test_notice_delivery_container import config
from ugc_bot.application.services.paid_selection_delivery import (
    PaidSelectionDelivery,
    _message,
)
from ugc_bot.container import Container
from ugc_bot.infrastructure.messenger import notice_receipts


def source(locale="ru", **changes):
    return SimpleNamespace(
        instagram_url="https://instagram.com/creator/",
        contact=SimpleNamespace(locale=locale),
        creator_contact=dict(
            username="Creator", telegram="@creator", phone="+7 000 000 0000"
        )
        | changes,
    )


@pytest.mark.parametrize(
    "locale,title,phone",
    [
        ("ru", "Креатор подтвердил интерес", "Телефон"),
        ("en", "Creator confirmed interest", "Phone"),
        ("kk", "Креатор қызығушылық танытты", "Телефон"),
        ("be", "Крэатар пацвердзіў цікавасць", "Тэлефон"),
        ("uz", "Kreator qiziqishini tasdiqladi", "Telefon"),
        ("unsupported", "Креатор подтвердил интерес", "Телефон"),
    ],
)
def test_contact_text_uses_actual_supported_locale(locale, title, phone):
    text = _message(source(locale))
    assert title in text and phone + ": +7" in text
    assert (
        "Telegram: @creator" in text
        and "https://instagram.com/creator/" in text
    )


@pytest.mark.parametrize(
    "value", ["bad\ncontact", "bad\x00contact", "x" * 201, 5]
)
def test_contact_control_text_fails_before_transport(value):
    with pytest.raises(ValueError, match="selection_contact_render_invalid"):
        _message(source(username=value))


@pytest.mark.parametrize(
    "url",
    [
        "http://instagram.com/user",
        "https://evil.test/user",
        "https://instagram.com@evil.test/user",
        "https://instagram.com/user?redirect=evil",
        "https://instagram.com/user#fragment",
        "https://instagram.com:444/user",
    ],
)
def test_only_safe_verified_instagram_profile_urls_are_rendered(url):
    current = source()
    current.instagram_url = url
    with pytest.raises(ValueError, match="selection_instagram_url_invalid"):
        _message(current)


def test_factory_default_off_constructs_no_transport_or_repository(monkeypatch):
    container = Container(config())
    monkeypatch.setattr(
        notice_receipts,
        "TelegramNoticeReceipts",
        Mock(side_effect=AssertionError("disabled")),
    )
    assert container.build_paid_selection_delivery(object()) is None


def test_factory_uses_actual_sql_clock_and_one_shot_transport():
    from ugc_bot.infrastructure.db.repositories.paid_selection_delivery import (
        SqlAlchemyPaidSelectionDeliveryRepository,
    )

    container = Container(config(enabled=True, max_token="synthetic-max"))
    bot, session = object(), object()
    worker = container.build_paid_selection_delivery(bot, max_session=session)
    assert isinstance(worker, PaidSelectionDelivery)
    assert isinstance(
        worker.repository, SqlAlchemyPaidSelectionDeliveryRepository
    )
    assert worker.transactions is container.transaction_manager
    assert worker.transport.transports["telegram"].bot is bot
    assert worker.transport.transports["max"].session is session
    assert worker.clock.now().tzinfo is not None


def test_enabled_factory_requires_database_before_transport():
    container = Container(config(enabled=True, database=""))
    with pytest.raises(ValueError, match="DATABASE_URL"):
        container.build_paid_selection_delivery(object())


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, True, 1001])
async def test_bad_batch_bounds_fail_before_opening_a_transaction(limit):
    worker = PaidSelectionDelivery(None, None, None, None)
    with pytest.raises(ValueError, match="selection_delivery_limit_invalid"):
        await worker.run_once(limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("lease", [0, True, -1])
async def test_bad_lease_bounds_fail_before_opening_a_transaction(lease):
    worker = PaidSelectionDelivery(None, None, None, None, lease_seconds=lease)
    with pytest.raises(ValueError, match="selection_delivery_lease_invalid"):
        await worker.prepare(None)


def test_direct_factory_also_obeys_default_off():
    from ugc_bot.container.paid_selection_delivery_factory import (
        build_paid_selection_delivery,
    )

    assert build_paid_selection_delivery(config(), None, object()) is None
