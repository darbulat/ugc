"""Stories stay explicit and full offers fit both messenger transports."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from ugc_bot.application.messenger.dto import Keyboard, KeyboardKind
from ugc_bot.application.services.admin_notification_service import (
    _format_order_type_for_moderation,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
    _build_dispatch_criteria,
    _passes_placement_filter,
)
from ugc_bot.bot.telegram.handlers.my_orders import _format_order_type
from ugc_bot.bot.telegram.handlers.offer_responses import _format_ugc_type
from ugc_bot.domain.entities import Order
from ugc_bot.domain.enums import OrderStatus, OrderType, WorkFormat
from ugc_bot.kafka_consumer import _send_offer_via_client


def order():
    return Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.STORIES,
        product_link="https://example.test/product",
        offer_text="Brief",
        barter_description=None,
        price=100,
        bloggers_needed=20,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        filter_by_placement=True,
        product_photo_file_id="order-image:" + str(uuid4()),
    )


@pytest.mark.parametrize(
    "locale,label",
    [
        ("ru", "Сторис"),
        ("en", "Stories"),
        ("kk", "Сторис"),
        ("be", "Сторыс"),
        ("uz", "Stories"),
    ],
)
@pytest.mark.asyncio
async def test_stories_label_reaches_offer_order_and_contact(locale, label):
    texts = BotTextsService(bot_texts_repo=Mock())
    service = OfferDispatchService(*(Mock() for _ in range(5)))
    value = order()
    formatted = await service.format_offer(value, "active", locale, texts)
    assert label in formatted
    translations = await texts.get_many(["order_type_stories"], locale)
    assert _format_order_type(value, translations) == label
    assert _format_ugc_type(value, translations) == label
    assert _format_order_type_for_moderation(value) == "Сторис"


def test_stories_placement_filter_requires_account_publishing():
    value = order()
    criteria = _build_dispatch_criteria(value)
    assert not _passes_placement_filter(
        Mock(work_format=WorkFormat.UGC_ONLY), value, criteria
    )
    assert _passes_placement_filter(
        Mock(work_format=WorkFormat.ADS_IN_ACCOUNT), value, criteria
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("with_photo", [False, True])
@pytest.mark.asyncio
async def test_long_offer_preserves_all_text_and_response_keyboard(
    platform, with_photo
):
    value = order()
    if not with_photo:
        value = replace(value, product_photo_file_id=None)
    text = "Начало 😀<&\n" + "текст 😀" * 1800 + "\nКонец"
    accepted = []

    async def photo(**kwargs):
        assert len(kwargs["caption"].encode("utf-16-le")) // 2 <= 1024
        accepted.append(("photo", kwargs["caption"], kwargs["keyboard"]))

    async def message(**kwargs):
        assert len(kwargs["text"].encode("utf-16-le")) // 2 <= 4000
        accepted.append(("text", kwargs["text"], kwargs["keyboard"]))

    client = Mock(
        send_photo=AsyncMock(side_effect=photo),
        send_text=AsyncMock(side_effect=message),
    )
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=[])
    result = await _send_offer_via_client(
        "1",
        client,
        text,
        keyboard,
        value,
        Mock(user_id=uuid4()),
        1,
        0,
        Mock(),
        None,
        "dlq",
        platform,
    )
    assert result is True
    assert "".join(part[1] for part in accepted) == text
    assert accepted[-1][2] is keyboard
    assert all(part[2] is None for part in accepted[:-1])
    assert sum(part[0] == "photo" for part in accepted) == int(with_photo)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("failed_text_part", [1, 2])
@pytest.mark.asyncio
async def test_offer_retry_resumes_after_accepted_photo(
    platform, failed_text_part
):
    value = order()
    text = "😀" * 3000
    accepted = []
    failed = False
    text_attempts = 0

    async def photo(**kwargs):
        accepted.append(kwargs["caption"])

    async def message(**kwargs):
        nonlocal failed, text_attempts
        text_attempts += 1
        if not failed and text_attempts == failed_text_part:
            failed = True
            raise RuntimeError("explicit test rejection")
        accepted.append(kwargs["text"])

    client = Mock(
        send_photo=AsyncMock(side_effect=photo),
        send_text=AsyncMock(side_effect=message),
    )
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=[])
    result = await _send_offer_via_client(
        "1",
        client,
        text,
        keyboard,
        value,
        Mock(user_id=uuid4()),
        2,
        0,
        Mock(),
        None,
        "dlq",
        platform,
    )
    assert result is True
    assert client.send_photo.await_count == 1
    assert "".join(accepted) == text
    assert client.send_text.call_args.kwargs["keyboard"] is keyboard


@pytest.mark.parametrize(
    "text", ["x" * 1024, "x" * 1025, "😀" * 512, "😀" * 513]
)
def test_photo_caption_boundary_keeps_codepoints_and_all_text(text):
    from ugc_bot.kafka_consumer import _offer_message_parts

    parts = _offer_message_parts(text, photo=True)
    assert "".join(parts) == text
    assert len(parts[0].encode("utf-16-le")) // 2 <= 1024
    assert all(len(part.encode("utf-16-le")) // 2 <= 4000 for part in parts)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.asyncio
async def test_unacknowledged_photo_retains_at_least_once_delivery_boundary(
    platform,
):
    """An acceptance without acknowledgement cannot be deduplicated locally."""
    accepted = []

    async def photo(**kwargs):
        accepted.append(kwargs["caption"])
        if len(accepted) == 1:
            raise TimeoutError(
                "Remote accepted the photo, acknowledgement lost"
            )

    client = Mock(
        send_photo=AsyncMock(side_effect=photo), send_text=AsyncMock()
    )
    result = await _send_offer_via_client(
        "1",
        client,
        "Brief",
        Keyboard(kind=KeyboardKind.INLINE, rows=[]),
        order(),
        Mock(user_id=uuid4()),
        2,
        0,
        Mock(),
        None,
        "dlq",
        platform,
    )
    assert result is True
    assert accepted == ["Brief", "Brief"]
    assert client.send_text.await_count == 0
