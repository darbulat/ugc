from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import EditMessageCaption, SendPhoto
from PIL import Image

from ugc_bot.admin.app import OrderAdmin, _creator_card_edit_data
from ugc_bot.application.creator_offer_cards import (
    CALLBACK_PREFIX,
    NEUTRAL_COVER,
    render_public_offer,
    render_saved_offer,
    validate_public_offer,
)
from ugc_bot.application.errors import (
    OrderCreationError,
    PaidSelectionResponseError,
)
from ugc_bot.application.messenger.dto import IncomingCallback, IncomingUser
from ugc_bot.bot.creator_offer_card_flow import CreatorOfferCardFlow
from ugc_bot.bot.max.handlers.offer_responses import (
    handle_creator_offer_card as handle_max_creator_offer,
)
from ugc_bot.bot.telegram.handlers.creator_invites import invitation_text
from ugc_bot.bot.telegram.handlers.offer_responses import (
    handle_creator_offer_card as handle_telegram_creator_offer,
)
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    RejectionReason,
    UserStatus,
)
from ugc_bot.infrastructure.messenger.max.client import MaxMessengerClient
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
)
from ugc_bot.infrastructure.messenger.telegram.offer_cover import (
    neutral_offer_cover,
)
from ugc_bot.kafka_consumer import (
    _dispatch_ready,
    _send_offer_to_blogger,
    _send_offers,
    _send_public_offer,
)


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


@pytest.mark.parametrize("role", ["client", "manager"])
def test_selected_communicator_is_independent_of_notification_recipients(
    order, role
):
    values = {
        **order.creator_offer_card,
        "sender_name": "UseMyContent",
        "communication_role": role,
        "client_contact": "@client_account",
        "manager_contact": "@manager_account",
        # A stale legacy value must never override the selected role.
        "contact": "@another_account",
    }
    configured = replace(order, creator_offer_card=values)
    public = render_public_offer(configured, "ru")
    assert "<b>Заказчик</b> · UseMyContent" in public.text
    assert "_account" not in public.text
    saved = render_saved_offer(configured, "ru")
    assert saved.keyboard.rows[0][0].url == f"https://t.me/{role}_account"
    normalized = validate_public_offer(values, ready=True)
    assert normalized["contact"] == f"@{role}_account"
    assert normalized["communication_role"] == role


def test_missing_manager_contact_cannot_expose_the_client_contact(order):
    values = {
        **order.creator_offer_card,
        "communication_role": "manager",
        "client_contact": "@private_client",
    }
    saved = render_saved_offer(replace(order, creator_offer_card=values), "ru")
    assert all(
        "t.me" not in button.url
        for row in saved.keyboard.rows
        for button in row
    )
    with pytest.raises(ValueError, match="выбранного ответственного"):
        validate_public_offer(values, ready=True)
    assert "contact" not in validate_public_offer(values)


def test_invalid_communication_role_is_rejected(order):
    with pytest.raises(ValueError, match="кто общается"):
        validate_public_offer(
            {**order.creator_offer_card, "communication_role": "everyone"}
        )


def test_admin_switches_contact_and_preserves_both_role_settings(order):
    form = {
        f"creator_card_{key}": value
        for key, value in {
            **order.creator_offer_card,
            "sender_name": "UseMyContent",
            "communication_role": "client",
            "client_contact": "@client_account",
            "manager_contact": "@manager_account",
        }.items()
    }
    client = _creator_card_edit_data(order, {}, form, activating=True)[
        "creator_offer_card"
    ]
    assert client["contact"] == "@client_account"
    assert client["sender_name"] == "UseMyContent"
    form["creator_card_communication_role"] = "manager"
    manager = _creator_card_edit_data(order, {}, form, activating=True)[
        "creator_offer_card"
    ]
    assert manager["contact"] == "@manager_account"
    assert manager["client_contact"] == "@client_account"
    assert manager["manager_contact"] == "@manager_account"


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


def test_manual_invite_never_uses_private_text_of_public_order(order):
    text, _ = invitation_text(
        {
            "order_id": order.order_id,
            "creator_offer_card": order.creator_offer_card,
            "offer_text": "Private full briefing",
            "geography": "Private location",
            "instagram": "creator_demo",
        },
        "invite",
    )
    assert "Привычки в кадре" in text
    assert "Private" not in text
    assert "client_work" not in text


@pytest.fixture
def offer_session(order, creator):
    messenger = AsyncMock()
    orders = AsyncMock()
    orders.get_by_id.return_value = order
    dispatch = AsyncMock()
    receipts = AsyncMock()
    dispatch.offer_dispatch_repo = receipts
    receipts.creator_card_matches.return_value = True
    receipts.recover_creator_card_receipt.return_value = False
    receipts.list_responses_by_blogger.return_value = []
    responses = AsyncMock()
    users = AsyncMock()
    users.get_user.return_value = creator
    users.get_user_by_id.return_value = replace(
        creator,
        user_id=order.advertiser_id,
        telegram_id="980",
        max_chat_id="981",
        language="ru",
    )
    profiles = AsyncMock()
    profiles.get_blogger_profile.return_value = SimpleNamespace(
        confirmed=True,
        instagram_url="https://instagram.com/example_creator",
        phone="+70000000000",
    )
    texts = AsyncMock()
    texts.get.side_effect = lambda key, locale: key
    flow = CreatorOfferCardFlow(
        orders, dispatch, responses, users, profiles, texts, messenger, "ru"
    )
    return SimpleNamespace(
        flow=flow,
        receipts=receipts,
        messenger=messenger,
        response=responses,
        interactions=AsyncMock(),
        alternative=AsyncMock(),
    )


def click(order, action="done", channel=MessengerType.TELEGRAM):
    return IncomingCallback(
        callback_id="callback",
        chat_id="100" if channel == MessengerType.TELEGRAM else "200",
        user=IncomingUser("100", channel),
        message_id="456",
        data=f"{CALLBACK_PREFIX}{action}:{order.order_id}",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("problem", "error"),
    [
        ("malformed", "err_order_invalid_id"),
        ("legacy", "msg_order_closed"),
        ("paused", "msg_offer_response_blocked"),
        ("another_cards_receipt", "msg_order_closed"),
        ("another_chat", "msg_order_closed"),
        ("unconfirmed_profile", "msg_confirm_instagram_first"),
        ("flood", "msg_too_many_requests"),
    ],
)
async def test_rejected_callback_cannot_reveal_contacts(
    order, creator, offer_session, problem, error
):
    harness = offer_session
    callback = click(order)
    match problem:
        case "malformed":
            callback = replace(
                callback, data=f"{CALLBACK_PREFIX}done:not-an-id"
            )
        case "legacy":
            harness.flow.orders.get_by_id.return_value = replace(
                order, creator_offer_card=None
            )
        case "paused":
            harness.flow.users.get_user.return_value = replace(
                creator, status=UserStatus.PAUSE
            )
        case "another_cards_receipt":
            harness.receipts.creator_card_matches.return_value = False
        case "another_chat":
            callback = replace(callback, chat_id="-1000000000000")
        case "unconfirmed_profile":
            harness.flow.profiles.get_blogger_profile.return_value.confirmed = (
                False
            )
        case "flood":
            harness.flow.rate_limiter = AsyncMock()
            harness.flow.rate_limiter.allow_async.return_value = False
    await harness.flow.handle(callback)
    harness.messenger.answer_callback.assert_awaited_once_with(
        callback_id=callback.callback_id, text=error
    )
    harness.response.respond_and_finalize.assert_not_awaited()
    harness.messenger.edit_offer_card.assert_not_awaited()
    if problem == "another_chat":
        harness.receipts.recover_creator_card_receipt.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "action", "caption"),
    [
        ("closed", "brief", "Набор завершён"),
        ("accepted", "done", "Отклик сохранён"),
        ("accepted", "open", "Отклик сохранён"),
        ("reserve", "done", "Ты в листе ожидания"),
        ("skipped", "done", "Оффер пропущен"),
        ("new", "s_time", "Оффер пропущен"),
    ],
)
async def test_terminal_card_does_not_repeat_a_response(
    order, creator, offer_session, state, action, caption
):
    harness = offer_session
    if state == "closed":
        harness.flow.orders.get_by_id.return_value = replace(
            order, dispatch_stopped=True
        )
    if state in {"accepted", "reserve", "skipped"}:
        harness.receipts.list_responses_by_blogger.return_value = [
            SimpleNamespace(
                order_id=order.order_id,
                accepted=state != "skipped",
                in_offer=state == "accepted",
            )
        ]
    await harness.flow.handle(click(order, action))
    harness.response.respond_and_finalize.assert_not_awaited()
    (chat_id, message_id, card) = (
        harness.messenger.edit_offer_card.call_args.args
    )
    assert (chat_id, message_id) == ("100", "456")
    assert caption in card.text
    if state != "accepted":
        assert card.keyboard is None
    if action == "s_time":
        harness.flow.dispatch.record_skip.assert_awaited_once_with(
            order.order_id,
            creator.user_id,
            channel=MessengerType.TELEGRAM,
            rejection_reason=RejectionReason.NO_TIME,
            only_unanswered=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["paid_error", "expired", "reserve", "edit_timeout"]
)
async def test_failed_or_unavailable_response_stays_in_same_card(
    order, offer_session, reason
):
    harness = offer_session
    callback = click(order)
    method = harness.response.respond_and_finalize
    method.return_value = SimpleNamespace(
        order=order,
        accepted=reason == "edit_timeout",
        delivery_queued=True,
    )
    if reason == "paid_error":
        method.side_effect = PaidSelectionResponseError("changed")
    elif reason == "expired":
        method.side_effect = OrderCreationError("expired")
    elif reason == "edit_timeout":
        harness.messenger.edit_offer_card.side_effect = TimeoutError()
    await harness.flow.handle(callback)
    assert harness.messenger.answer_callback.await_count == 1
    if reason in {"paid_error", "edit_timeout"}:
        harness.receipts.mark_creator_card_updated.assert_not_awaited()
    if reason in {"expired", "reserve"}:
        card = harness.messenger.edit_offer_card.call_args.args[2]
        assert card.keyboard is None
        assert (
            "Набор завершён" if reason == "expired" else "Ты в листе ожидания"
        ) in card.text
    harness.messenger.send_offer_card.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform", [MessengerType.TELEGRAM, MessengerType.MAX]
)
async def test_direct_response_notifies_the_preferred_address_once(
    order, creator, offer_session, platform
):
    harness = offer_session
    flow = harness.flow
    callback = click(order, channel=platform)
    flow.users.get_user_by_id.return_value = replace(
        flow.users.get_user_by_id.return_value, messenger_type=platform
    )
    harness.response.respond_and_finalize.return_value = SimpleNamespace(
        order=order, accepted=True, delivery_queued=False, manager_id=None
    )
    if platform == MessengerType.MAX:
        await handle_max_creator_offer(
            callback,
            {
                "order_repo": flow.orders,
                "offer_dispatch_service": flow.dispatch,
                "offer_response_service": flow.responses,
                "user_role_service": flow.users,
                "profile_service": flow.profiles,
                "bot_texts_service": flow.texts,
                "state_store": AsyncMock(),
                "messenger_client": flow.messenger,
                "telegram_messenger_client": harness.alternative,
                "interaction_service": harness.interactions,
            },
        )
    else:
        await handle_telegram_creator_offer(
            SimpleNamespace(),
            AsyncMock(),
            flow.orders,
            flow.dispatch,
            flow.responses,
            flow.users,
            flow.profiles,
            flow.texts,
            harness.interactions,
            offer_response_rate_limiter=None,
            messenger_client=flow.messenger,
            event_adapter=SimpleNamespace(from_callback=lambda raw: callback),
            max_messenger_client=harness.alternative,
        )
    harness.messenger.edit_offer_card.assert_awaited_once()
    harness.messenger.send_offer_card.assert_awaited_once()
    address, card, cover = harness.messenger.send_offer_card.call_args.args
    assert address == ("980" if platform == MessengerType.TELEGRAM else "981")
    assert "Новый отклик" in card.text
    assert cover is None
    assert [button.url for row in card.keyboard.rows for button in row] == [
        "https://instagram.com/example_creator"
    ]
    harness.alternative.send_offer_card.assert_not_awaited()
    harness.interactions.reactivate_or_create_for_contacts_sent.assert_awaited_once_with(
        order_id=order.order_id,
        blogger_id=creator.user_id,
        advertiser_id=order.advertiser_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem", ["bad_profile", "no_destination", "delivery_unknown"]
)
async def test_direct_response_does_not_record_contacts_that_were_not_delivered(
    order, creator, offer_session, problem
):
    harness = offer_session
    if problem == "bad_profile":
        harness.flow.profiles.get_blogger_profile.return_value.instagram_url = (
            "javascript:example"
        )
    elif problem == "no_destination":
        harness.flow.users.get_user_by_id.return_value = replace(
            creator, telegram_id=None, max_chat_id=None
        )
    else:
        harness.messenger.send_offer_card.side_effect = TimeoutError()
    await harness.flow.finish_direct(
        click(order), order, creator, harness.interactions, harness.alternative
    )
    harness.messenger.edit_offer_card.assert_awaited_once()
    if problem == "delivery_unknown":
        harness.messenger.send_offer_card.assert_awaited_once()
    else:
        harness.messenger.send_offer_card.assert_not_awaited()
    harness.alternative.send_offer_card.assert_not_awaited()
    harness.interactions.reactivate_or_create_for_contacts_sent.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(MessengerType))
@pytest.mark.parametrize("failed_recipient", [None, "client", "manager"])
async def test_direct_response_copies_manager_independently_of_client_failure(
    order, creator, offer_session, platform, failed_recipient
):
    harness = offer_session
    client = harness.flow.users.get_user_by_id.return_value
    manager = replace(
        client,
        user_id=uuid4(),
        telegram_id="990",
        max_chat_id="991",
        language="en",
    )
    harness.flow.users.get_user_by_id.side_effect = [client, manager]
    transport = (
        harness.messenger
        if platform == MessengerType.TELEGRAM
        else harness.alternative
    )
    transport.send_offer_card.side_effect = [
        TimeoutError() if failed_recipient == "client" else "client-receipt",
        TimeoutError() if failed_recipient == "manager" else "manager-receipt",
    ]
    await harness.flow.finish_direct(
        click(order, channel=platform),
        order,
        creator,
        harness.interactions,
        harness.alternative,
        manager_id=manager.user_id,
    )
    calls = transport.send_offer_card.await_args_list
    assert [call.args[0] for call in calls] == ["980", "990"]
    assert "Новый отклик" in calls[0].args[1].text
    assert "New response" in calls[1].args[1].text
    assert (
        harness.interactions.reactivate_or_create_for_contacts_sent.await_count
        == (0 if failed_recipient == "client" else 1)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("same_user", [True, False])
async def test_direct_copy_deduplicates_a_shared_user_or_destination(
    order, creator, offer_session, same_user
):
    harness = offer_session
    client = harness.flow.users.get_user_by_id.return_value
    manager = replace(client, user_id=client.user_id if same_user else uuid4())
    harness.flow.users.get_user_by_id.side_effect = [client, manager]
    await harness.flow.finish_direct(
        click(order),
        order,
        creator,
        harness.interactions,
        harness.alternative,
        manager_id=manager.user_id,
    )
    harness.messenger.send_offer_card.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cover", [None, NEUTRAL_COVER, "approved-upload"])
async def test_telegram_card_has_one_message_and_a_provider_receipt(
    order, cover
):
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 12
    bot.send_photo.return_value.message_id = 34
    transport = TelegramMessengerClient(bot)
    receipt = await transport.send_offer_card(
        "100", render_public_offer(order, "ru"), cover
    )
    assert receipt == ("12" if cover is None else "34")
    if cover is None:
        bot.send_message.assert_awaited_once()
        bot.send_photo.assert_not_awaited()
    else:
        bot.send_message.assert_not_awaited()
        bot.send_photo.assert_awaited_once()
        photo = bot.send_photo.call_args.kwargs["photo"]
        assert (photo.filename if cover == NEUTRAL_COVER else photo) == (
            "ugc-offer.jpg" if cover == NEUTRAL_COVER else cover
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("idempotent", [True, False])
async def test_telegram_edit_accepts_an_already_updated_message(
    order, idempotent
):
    bot = AsyncMock()
    transport = TelegramMessengerClient(bot)
    edited = render_saved_offer(order, "ru")
    bot.edit_message_caption.side_effect = TelegramBadRequest(
        method=EditMessageCaption(chat_id=100, message_id=1),
        message="message is not modified"
        if idempotent
        else "message to edit not found",
    )
    if idempotent:
        await transport.edit_offer_card("100", "1", edited)
    else:
        with pytest.raises(TelegramBadRequest):
            await transport.edit_offer_card("100", "1", edited)
    bot.send_message.assert_not_awaited()
    bot.send_photo.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_receipt", [True, False])
async def test_max_uses_one_provider_attempt_and_edits_in_place(
    order, monkeypatch, provider_receipt
):
    transport = MaxMessengerClient("fake", AsyncMock())
    request = AsyncMock(
        return_value={"message": {"body": {"mid": "receipt"}}}
        if provider_receipt
        else {}
    )
    monkeypatch.setattr(transport, "_request", request)
    card = render_public_offer(order, "ru")
    if provider_receipt:
        assert (
            await transport.send_offer_card("100", card, NEUTRAL_COVER)
            == "receipt"
        )
    else:
        with pytest.raises(ValueError, match="receipt_unavailable"):
            await transport.send_offer_card("100", card, NEUTRAL_COVER)
    request.assert_awaited_once()
    assert request.call_args.kwargs["attempts"] == 1
    assert request.call_args.args[2]["format"] == "html"
    await transport.edit_offer_card("100", "receipt", card)
    assert request.call_args.args[:2] == ("PUT", "/messages")
    assert request.call_args.kwargs["params"] == {"message_id": "receipt"}


@pytest.mark.asyncio
@pytest.mark.parametrize("rejection", ["rate_limited", "not_found"])
async def test_dispatch_retries_only_safe_provider_responses(
    order, creator, monkeypatch, rejection
):
    telegram, backup, dispatch = AsyncMock(), AsyncMock(), AsyncMock()
    backup.send_offer_card.return_value = "from-max"
    photo = SendPhoto(chat_id=100, photo="approved-upload")
    if rejection == "rate_limited":
        telegram.send_offer_card.side_effect = [
            TelegramRetryAfter(
                method=photo, message="slow down", retry_after=1
            ),
            "from-telegram",
        ]
    else:
        telegram.send_offer_card.side_effect = TelegramBadRequest(
            method=photo, message="chat not found"
        )
    monkeypatch.setattr("ugc_bot.kafka_consumer.asyncio.sleep", AsyncMock())
    result = await _send_offer_to_blogger(
        creator,
        order,
        "active",
        {"telegram": telegram, "max": backup},
        dispatch,
        1,
        0,
        None,
        "dlq",
    )
    assert result is True
    dispatch.record_offer_sent.assert_awaited_once()
    assert dispatch.record_offer_sent.call_args.kwargs["channel"] == (
        MessengerType.TELEGRAM
        if rejection == "rate_limited"
        else MessengerType.MAX
    )
    assert telegram.send_offer_card.await_count == (
        2 if rejection == "rate_limited" else 1
    )
    assert backup.send_offer_card.await_count == (
        0 if rejection == "rate_limited" else 1
    )


def test_dispatch_refuses_unready_or_closed_public_card(order):
    assert _dispatch_ready(order, 1)
    assert not _dispatch_ready(replace(order, status=OrderStatus.CLOSED), 1)
    assert not _dispatch_ready(replace(order, creator_offer_card={}), 1)


def test_anonymous_barter_and_contact_field_are_independently_validated(order):
    values = {
        **order.creator_offer_card,
        "brand": "Одобренный бренд",
        "barter": "Тестовый продукт",
        "photo": "approved",
    }
    barter = replace(order, price=0, creator_offer_card=values)
    card = render_public_offer(barter, "ru")
    assert "Бартер" in card.text and "Тестовый продукт" in card.text
    assert "Одобренный бренд" in card.text
    assert scan_private_contact(card) is False
    mixed = replace(order, price=120.55, creator_offer_card=values)
    assert "120,55" in render_public_offer(mixed, "ru").text
    assert "Тестовый продукт" in render_public_offer(mixed, "ru").text
    with pytest.raises(ValueError, match="рабочий Telegram"):
        render_public_offer(
            replace(
                order,
                creator_offer_card={**values, "contact": "someone.example"},
            ),
            "ru",
        )
    assert (
        "Одобренный бренд"
        in invitation_text(
            {
                "order_id": order.order_id,
                "creator_offer_card": values,
                "instagram": "username",
            },
            "payload",
        )[0]
    )


def scan_private_contact(card):
    return "client_work" in card.text or any(
        btn.url is not None for row in card.keyboard.rows for btn in row
    )


def test_draft_can_enable_new_card_but_active_legacy_order_cannot(order):
    form = {
        "creator_card_enable": "yes",
        "creator_card_title": "Съёмка",
        "creator_card_task": "Снять ролик",
        "creator_card_deadline": "Неделя",
        "creator_card_usage": "Соцсети",
    }
    legacy = replace(order, creator_offer_card=None)
    assert _creator_card_edit_data(legacy, {}, form, activating=False) == {}
    draft = replace(legacy, status=OrderStatus.NEW)
    data = _creator_card_edit_data(draft, {}, form, activating=True)
    assert data["creator_offer_card"] == {
        "title": "Съёмка",
        "task": "Снять ролик",
        "deadline": "Неделя",
        "usage": "Соцсети",
    }


@pytest.mark.parametrize(
    "private_link", ["name with spaces", "https://example.com:invalid"]
)
def test_saved_offer_omits_unusable_links_and_has_contact_fallback(
    order, private_link
):
    saved = render_saved_offer(
        replace(
            order,
            product_link=private_link,
            brief_link="",
            creator_offer_card={**order.creator_offer_card, "contact": ""},
        ),
        "ru",
    )
    assert saved.keyboard is None
    assert "Заказчик напишет первым" in saved.text


@pytest.mark.asyncio
async def test_worker_respects_claims_and_records_definite_failure(
    order, creator
):
    worker, telegram = AsyncMock(), AsyncMock()
    order_owner = replace(creator, user_id=order.advertiser_id)
    awaiting_review = replace(order, creator_offer_card={})
    worker.get_order_and_advertiser.return_value = (
        awaiting_review,
        order_owner,
    )
    await _send_offers(
        order.order_id,
        {"telegram": telegram},
        worker,
        None,
        "dlq",
        1,
        0,
        dispatch_run=1,
    )
    worker.dispatch.assert_not_awaited()

    rejected = replace(
        creator, user_id=uuid4(), telegram_id="101", max_chat_id=None
    )
    uncertain = replace(
        creator, user_id=uuid4(), telegram_id="102", max_chat_id=None
    )
    worker.get_order_and_advertiser.return_value = (order, order_owner)
    worker.dispatch.return_value = [creator, rejected, uncertain]
    worker.prepare_dispatch_audience.return_value = [
        creator,
        rejected,
        uncertain,
    ]
    worker.claim_dispatch_recipient.side_effect = ["skip", "claimed", "claimed"]
    telegram.send_offer_card.side_effect = [
        TelegramBadRequest(
            method=SendPhoto(chat_id=101, photo="test"),
            message="chat not found",
        ),
        TimeoutError(),
    ]
    await _send_offers(
        order.order_id,
        {"telegram": telegram},
        worker,
        None,
        "dlq",
        1,
        0,
        dispatch_run=1,
    )

    assert [
        call.args[0] for call in telegram.send_offer_card.await_args_list
    ] == ["101", "102"]
    worker.reject_dispatch_recipient.assert_awaited_once_with(
        order.order_id, rejected.user_id, 1
    )
    worker.record_offer_sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_created_order_has_public_card_draft(order):
    model = SimpleNamespace(status=OrderStatus.NEW, creator_offer_card=None)
    await OrderAdmin().on_model_change(
        {"status": OrderStatus.NEW}, model, True, None
    )
    assert model.creator_offer_card == {}
    assert not _dispatch_ready(
        replace(order, creator_offer_card=model.creator_offer_card), 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [OrderStatus.ACTIVE, OrderStatus.CLOSED])
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
async def test_offer_card_opens_price_entry(
    order, offer_session, status, channel
):
    flow = offer_session.flow
    flow.orders.get_by_id.return_value = replace(
        order,
        status=status,
        offer_reserve_until=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    start = AsyncMock()
    flow.start_price_entry = start

    await flow.handle(click(order, "s_price", channel))
    start.assert_awaited_once_with(order.order_id)
    flow.dispatch.record_skip.assert_not_awaited()
    offer_session.messenger.edit_offer_card.assert_not_awaited()
    self_message = offer_session.messenger.send_text.call_args.kwargs
    assert self_message["text"] == "msg_enter_desired_price"
    assert (
        self_message["keyboard"].rows[0][0].callback_data
        == f"orr_cancel:{order.order_id}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", [MessengerType.TELEGRAM, MessengerType.MAX])
@pytest.mark.parametrize(
    "action", ["open", "brief", "confirm", "done", "s_price", "s_time"]
)
@pytest.mark.parametrize("phase", ["expired", "historical", "manual"])
async def test_finished_intake_disables_every_card_action(
    order, offer_session, channel, action, phase
):
    until = datetime.now(timezone.utc) - timedelta(seconds=1)
    closed = replace(order, offer_reserve_until=until)
    if phase == "historical":
        closed = replace(order, status=OrderStatus.CLOSED)
    elif phase == "manual":
        closed = replace(order, dispatch_stopped=True)
    flow = offer_session.flow
    flow.orders.get_by_id.return_value = closed
    flow.start_price_entry = AsyncMock()
    await flow.handle(click(order, action, channel))
    flow.start_price_entry.assert_not_awaited()
    flow.dispatch.record_skip.assert_not_awaited()
    flow.responses.respond_and_finalize.assert_not_awaited()
    card = offer_session.messenger.edit_offer_card.call_args.args[2]
    assert "Набор завершён" in card.text
    assert card.keyboard is None


@pytest.mark.asyncio
async def test_selected_creator_keeps_brief_and_contacts_after_intake(
    order, creator, offer_session
):
    closed = replace(order, offer_reserve_until=datetime.now(timezone.utc))
    offer_session.flow.orders.get_by_id.return_value = closed
    offer_session.receipts.list_responses_by_blogger.return_value = [
        SimpleNamespace(order_id=order.order_id, accepted=True, in_offer=True)
    ]
    await offer_session.flow.handle(click(order, "open"))
    card = offer_session.messenger.edit_offer_card.call_args.args[2]
    assert "Отклик сохранён" in card.text
    assert order.brief_link in {
        button.url for row in card.keyboard.rows for button in row
    }


def test_reserve_card_discloses_deadline_before_confirmation(order):
    reserve = replace(
        order,
        offer_reserve_until=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    for action in ("open", "confirm", "reserve"):
        card = render_public_offer(reserve, "ru", action)
        assert "Основной состав набран" in card.text
        assert "Участие не гарантировано" in card.text


def test_dispatch_stops_when_reserve_starts(order):
    reserve = replace(
        order,
        offer_reserve_until=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    assert not _dispatch_ready(reserve, None)
    assert not _dispatch_ready(reserve, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["done", "s_time", "open"])
async def test_card_closes_when_intake_expires_during_response(
    order, offer_session, action
):
    from ugc_bot.application.services.offer_dispatch_service import SkipResult

    flow = offer_session.flow
    if action == "done":
        flow.responses.respond_and_finalize.side_effect = (
            PaidSelectionResponseError("offer_intake_closed")
        )
    elif action == "s_time":
        flow.dispatch.record_skip.return_value = SkipResult(intake_closed=True)
    else:
        flow.orders.get_by_id.return_value = replace(
            order, offer_reserve_until=datetime.now(timezone.utc)
        )
        offer_session.receipts.list_responses_by_blogger.return_value = [
            SimpleNamespace(
                order_id=order.order_id, accepted=True, in_offer=False
            )
        ]
    await flow.handle(click(order, action))
    card = offer_session.messenger.edit_offer_card.call_args.args[2]
    assert "Набор завершён" in card.text
    assert card.keyboard is None
    offer_session.messenger.send_offer_card.assert_not_awaited()


def test_english_reserve_card_does_not_promise_contact_delivery(order):
    reserve = replace(
        order,
        offer_reserve_until=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    card = render_public_offer(reserve, "en", "confirm")
    assert "reserve" in card.text
    assert "Participation is not guaranteed" in card.text
    assert "share your profile and contact" not in card.text
