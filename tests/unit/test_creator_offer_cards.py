from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image

from ugc_bot.application.creator_offer_cards import (
    CALLBACK_PREFIX,
    NEUTRAL_COVER,
    render_public_offer,
    render_saved_offer,
)
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.bot.creator_offer_card_flow import CreatorOfferCardFlow
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.infrastructure.messenger.telegram.offer_cover import (
    neutral_offer_cover,
)
from ugc_bot.kafka_consumer import _send_public_offer


@pytest.fixture
def order():
    return Order(
        uuid4(),
        uuid4(),
        OrderType.UGC_PLUS_PLACEMENT,
        "https://secret-product.example.com",
        "Brand name, original briefing and specifications",
        None,
        3000,
        10,
        OrderStatus.ACTIVE,
        datetime.now(timezone.utc),
        product_photo_file_id="private-brand-image",
        brief_link="https://secret-brief.example.com",
        creator_offer_card={
            "title": "Привычки в кадре",
            "task": "Покажи, как следишь за сном",
            "deadline": "До 7 дней после согласования",
            "usage": "Соцсети и реклама",
            "contact": "@client_work",
        },
    )


@pytest.fixture
def creator():
    return User(
        uuid4(),
        MessengerType.TELEGRAM,
        "Creator",
        UserStatus.ACTIVE,
        0,
        datetime.now(timezone.utc),
        telegram_id="100",
        max_chat_id="200",
    )


def test_first_card_only_exposes_approved_public_fields(order):
    public = render_public_offer(order, "ru")
    assert "3\u202f000 ₽" in public.text
    assert "До 7 дней" in public.text
    assert "Соцсети и реклама" in public.text
    for view in ("open", "brief", "safe", "confirm"):
        card = render_public_offer(order, "ru", view)
        assert "secret-" not in card.text
        assert "Brand name" not in card.text
        assert "client_work" not in card.text
        assert not any(
            button.url for row in card.keyboard.rows for button in row
        )
    saved = render_saved_offer(order, "ru")
    assert {row[0].url for row in saved.keyboard.rows} == {
        "https://t.me/client_work",
        order.product_link,
        order.brief_link,
    }


@pytest.mark.parametrize("bad_task", ["https://brand.ru", "💡" * 110])
def test_unapproved_or_overlong_card_is_rejected(order, bad_task):
    with pytest.raises(ValueError):
        render_public_offer(
            replace(
                order,
                creator_offer_card={
                    **order.creator_offer_card,
                    "task": bad_task,
                },
            ),
            "ru",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [False, True])
async def test_new_offer_uses_one_channel_and_neutral_photo(
    order, creator, timeout
):
    adapter = AsyncMock()
    backup = AsyncMock()
    dispatch = AsyncMock()
    if timeout:
        adapter.send_offer_card.side_effect = TimeoutError
    else:
        adapter.send_offer_card.return_value = "456"
    outcome = await _send_public_offer(
        order,
        creator,
        [("100", adapter, "telegram"), ("200", backup, "max")],
        dispatch,
        "ru",
    )
    assert adapter.send_offer_card.await_count == 1
    assert adapter.send_offer_card.call_args.args[2] == NEUTRAL_COVER
    backup.send_offer_card.assert_not_called()
    if timeout:
        assert outcome is None
        dispatch.record_offer_sent.assert_not_called()
    else:
        assert outcome is True
        assert (
            dispatch.record_offer_sent.call_args.kwargs["message_id"] == "456"
        )


@pytest.mark.asyncio
async def test_offer_navigation_and_confirmation_edit_original_message(
    order, creator
):
    bot = AsyncMock()
    transport = TelegramMessengerClient(bot)
    repository = AsyncMock()
    repository.get_by_id.return_value = order
    dispatch = AsyncMock()
    dispatch.offer_dispatch_repo.creator_card_matches = AsyncMock(
        return_value=True
    )
    dispatch.offer_dispatch_repo.list_responses_by_blogger = AsyncMock(
        return_value=[]
    )
    dispatch.offer_dispatch_repo.mark_creator_card_updated = AsyncMock()
    responses = AsyncMock()
    responses.respond_and_finalize.return_value = SimpleNamespace(
        accepted=True,
        delivery_queued=True,
        order=order,
    )
    users = AsyncMock()
    users.get_user.return_value = creator
    profiles = AsyncMock()
    profiles.get_blogger_profile.return_value = SimpleNamespace(confirmed=True)
    flow = CreatorOfferCardFlow(
        repository,
        dispatch,
        responses,
        users,
        profiles,
        AsyncMock(),
        transport,
        "ru",
    )
    incoming = IncomingCallback(
        "query",
        "100",
        IncomingUser("100", MessengerType.TELEGRAM),
        message_id="456",
    )
    for action in ("brief", "confirm", "done"):
        await flow.handle(
            replace(
                incoming, data=f"{CALLBACK_PREFIX}{action}:{order.order_id}"
            )
        )
    assert bot.edit_message_caption.await_count == 3
    assert all(
        call.kwargs["message_id"] == 456
        for call in bot.edit_message_caption.await_args_list
    )
    assert (
        "Отклик сохранён"
        in bot.edit_message_caption.call_args.kwargs["caption"]
    )
    assert (
        bot.edit_message_caption.call_args.kwargs["reply_markup"]
        .inline_keyboard[0][0]
        .url
        == "https://t.me/client_work"
    )
    bot.send_message.assert_not_called()
    responses.respond_and_finalize.assert_awaited_once()
    dispatch.offer_dispatch_repo.mark_creator_card_updated.assert_awaited_once()


def test_cover_decodes_as_jpeg():
    picture = Image.open(BytesIO(neutral_offer_cover()))
    assert picture.format == "JPEG"
    assert picture.width > picture.height
    picture.verify()
