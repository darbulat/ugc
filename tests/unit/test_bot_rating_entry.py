"""Usable, owner-authorized bot entry for completed creator ratings."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from tests.helpers.fakes import FakeMessengerClient
from tests.unit.test_telegram_rating_baseline import callback as base_callback
from tests.unit.test_telegram_rating_baseline import flow as base_flow
from tests.unit.test_telegram_rating_baseline import message as base_message
from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.application.rating_eligibility_ports import RatingParticipant
from ugc_bot.bot.max.handlers import blogger_rating as max_handlers
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.rating_entry import compact_id
from ugc_bot.bot.telegram.handlers import blogger_rating as handlers
from ugc_bot.domain.enums import MessengerType


@pytest.fixture
def flow():
    return base_flow.__wrapped__()


def message(text="Great work"):
    event = base_message(text)
    event.chat = NS(id=2)
    event.message_id = 1
    event.photo = []
    event.successful_payment = None
    event.entities = []
    event.caption = None
    return event


def callback(data=None, with_message=True):
    event = base_callback(data, with_message)
    event.id = "callback-1"
    if with_message:
        event.message = message()
    return event


def test_score_callbacks_fit_telegram_and_roundtrip_ids():
    order_id, blogger_id = uuid4(), uuid4()
    keyboard = handlers._rating_keyboard(order_id, blogger_id)
    for score, button in enumerate(keyboard.inline_keyboard[0], 1):
        assert len(button.callback_data.encode()) <= 64
        assert handlers.decode_rating_callback(button.callback_data) == (
            order_id,
            blogger_id,
            score,
        )


def test_historic_score_callback_is_still_decoded():
    order_id, blogger_id = uuid4(), uuid4()
    assert handlers.decode_rating_callback(
        f"brs:{order_id}:{blogger_id}:4"
    ) == (order_id, blogger_id, 4)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/stop_reminders", "handle_stop_reminders"),
        ("/support_order", "handle_customer_help"),
        ("/services", "handle_customer_services"),
    ],
)
async def test_rating_comment_does_not_intercept_customer_commands(
    command, expected
):
    from aiogram.types import Chat, Message, MessageEntity
    from aiogram.types import User as TelegramUser

    from ugc_bot.bot.telegram.handlers import order_creation

    event = Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        from_user=TelegramUser(id=1, is_bot=False, first_name="Test"),
        text=command,
        entities=[
            MessageEntity(type="bot_command", offset=0, length=len(command))
        ],
    )
    bot = NS(me=NS(username="synthetic_bot"))
    state = handlers.RatingStates.waiting_comment.state
    for router in (handlers.router, order_creation.router):
        for registered in router.message.handlers:
            matches, _ = await registered.check(event, bot=bot, raw_state=state)
            if matches:
                assert registered.callback.__name__ == expected
                return
    pytest.fail(f"No handler for {command} while rating")


@pytest.mark.asyncio
@pytest.mark.parametrize("skip", [False, True])
async def test_real_telegram_router_complete_owner_rating_flow(flow, skip):
    messenger = FakeMessengerClient()
    orders = NS(
        list_by_advertiser=AsyncMock(
            return_value=[
                NS(
                    order_id=flow.order_id,
                    offer_text="Campaign",
                    created_at=datetime.now(UTC),
                )
            ]
        )
    )
    deps = dict(
        user_role_service=flow.roles,
        order_service=orders,
        blogger_rating_service=flow.service,
        manager_service=flow.managers,
        state=flow.state,
        messenger_client=messenger,
        user_locale="en",
        bot=NS(),
    )
    await handlers.router.propagate_event(
        "message", message("/rate_order"), **deps
    )
    order_data = messenger.sent_text[-1]["keyboard"].rows[0][0].callback_data
    assert len(order_data.encode()) == 26
    order_event = callback(order_data)
    await handlers.router.propagate_event("callback_query", order_event, **deps)
    creator_data = (
        order_event.message.answer.await_args.kwargs["reply_markup"]
        .inline_keyboard[0][0]
        .callback_data
    )
    assert len(creator_data.encode()) == 49
    creator_event = callback(creator_data)
    await handlers.router.propagate_event(
        "callback_query", creator_event, **deps
    )
    score_data = (
        creator_event.message.answer.await_args.kwargs["reply_markup"]
        .inline_keyboard[0][4]
        .callback_data
    )
    assert len(score_data.encode()) == 51
    score_event = callback(score_data)
    await handlers.router.propagate_event("callback_query", score_event, **deps)
    assert (await flow.state.get_data())["score"] == 5
    assert (await flow.state.get_data())["rating_locale"] == "en"
    await handlers.router.propagate_event(
        "callback_query" if skip else "message",
        callback("brc:skip") if skip else message("Great work"),
        raw_state=await flow.state.get_state(),
        **deps,
    )
    assert len(flow.repo.ratings) == 1
    assert flow.repo.ratings[0].score == 5
    assert flow.repo.ratings[0].comment == (None if skip else "Great work")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "foreign_order",
        "incomplete",
        "outsider",
        "bad_order",
        "bad_participant",
        "bad_score",
        "no_message",
    ],
)
async def test_rating_entry_rechecks_current_owner_and_completion(flow, case):
    data = f"brp:{compact_id(flow.order_id)}:{compact_id(flow.blogger_id)}"
    if case == "foreign_order":
        flow.eligibility.owners[flow.order_id] = uuid4()
    if case == "incomplete":
        flow.eligibility.participants[flow.order_id] = (
            RatingParticipant(flow.blogger_id, "Creator", False),
        )
    if case == "outsider":
        flow.roles.get_user.return_value = None
    if case == "bad_order":
        data = "bro:invalid"
    if case == "bad_participant":
        data = "brp:bad:bad"
    if case == "bad_score":
        data = "br2:bad:bad:5"
    event = callback(data, with_message=case != "no_message")
    await handlers.router.propagate_event(
        "callback_query",
        event,
        state=flow.state,
        user_role_service=flow.roles,
        blogger_rating_service=flow.service,
    )
    assert not flow.repo.ratings
    assert await flow.state.get_data() == {}
    event.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_incomplete_author_is_never_offered_and_updated_owner_denied(
    flow,
):
    incomplete = uuid4()
    flow.eligibility.participants[flow.order_id] += (
        RatingParticipant(incomplete, "Pending creator", False),
    )
    event = callback("bro:" + compact_id(flow.order_id))
    await handlers.rating_order_callback(event, flow.service, flow.roles)
    buttons = event.message.answer.await_args.kwargs[
        "reply_markup"
    ].inline_keyboard
    assert len(buttons) == 1
    assert incomplete.hex not in repr(buttons)
    flow.eligibility.participants[flow.order_id] = ()
    await handlers.rating_order_callback(
        callback("bro:" + compact_id(flow.order_id)), flow.service, flow.roles
    )
    flow.eligibility.owners[flow.order_id] = uuid4()
    await handlers.rating_order_callback(
        callback("bro:" + compact_id(flow.order_id)), flow.service, flow.roles
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["owned", "foreign", "incomplete", "bad_id", "no_base"]
)
async def test_registered_max_rating_router_opens_verified_specific_order(
    flow, case
):
    user = flow.eligibility.users[flow.user_id]
    flow.eligibility.users[flow.user_id] = replace(user, max_id="3")
    messenger = FakeMessengerClient()
    order = NS(
        order_id=flow.order_id,
        offer_text="Campaign",
        created_at=datetime.now(UTC),
    )
    deps = dict(
        user_role_service=flow.roles,
        order_service=NS(list_by_advertiser=AsyncMock(return_value=[order])),
        blogger_rating_service=flow.service,
        messenger_client=messenger,
        config=NS(
            webhook=NS(
                webhook_base_url=""
                if case == "no_base"
                else "https://umc.example"
            )
        ),
        locale="en",
    )
    router = MaxRouter()
    router.include(max_handlers.router)
    incoming = IncomingMessage(
        "2", IncomingUser("3", MessengerType.MAX), text="/rate_order"
    )
    await router.route_message(incoming, deps)
    await router.route_callback(
        IncomingCallback("menu", "2", incoming.user, data="customer:ratings"),
        deps,
    )
    data = messenger.sent_text[-1]["keyboard"].rows[0][0].callback_data
    if case == "foreign":
        flow.eligibility.owners[flow.order_id] = uuid4()
    if case == "incomplete":
        flow.eligibility.participants[flow.order_id] = ()
    await router.route_callback(
        IncomingCallback(
            "cb",
            "2",
            incoming.user,
            data="bro:bad" if case == "bad_id" else data,
        ),
        deps,
    )
    if case == "owned":
        url = messenger.sent_text[-1]["keyboard"].rows[0][0].web_app_url
        assert (
            url
            == f"https://umc.example/miniapp/max_app.html?screen=ratings&order_id={flow.order_id}"
        )
    else:
        assert messenger.sent_text[-1]["keyboard"] is None


def test_encoding_rejects_noncanonical_and_zero_ids():
    from ugc_bot.bot.rating_entry import expand_id

    for raw in [
        "a",
        "!" * 22,
        compact_id(__import__("uuid").UUID(int=0)),
        "A" * 21 + "B",
    ]:
        with pytest.raises(ValueError):
            expand_id(raw)
    for raw in [
        "br2:a:b:0",
        "xyz:a:b:1",
        "br2:" + compact_id(uuid4()) + ":" + compact_id(uuid4()) + ":9",
    ]:
        with pytest.raises(ValueError):
            handlers.decode_rating_callback(raw)


@pytest.mark.asyncio
async def test_unknown_and_empty_order_picker_have_no_controls(flow):
    messenger = FakeMessengerClient()
    orders = NS(list_by_advertiser=AsyncMock(return_value=[]))
    await handlers.rating_orders_command(
        message("/rate_order"), flow.roles, orders, messenger_client=messenger
    )
    assert messenger.sent_text[-1]["keyboard"] is None
    flow.roles.get_user.return_value = None
    await handlers.rating_orders_callback(
        callback("customer:ratings"),
        flow.roles,
        orders,
        messenger_client=messenger,
    )
    assert messenger.sent_text[-1]["keyboard"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing_service", "incomplete"])
async def test_score_click_revalidates_current_eligibility(flow, case):
    data = (
        handlers._rating_keyboard(flow.order_id, flow.blogger_id)
        .inline_keyboard[0][0]
        .callback_data
    )
    event = callback(data)
    if case == "incomplete":
        flow.eligibility.participants[flow.order_id] = ()
        await handlers.handle_rating_score(
            event, flow.state, flow.service, flow.roles
        )
    else:
        await handlers.handle_rating_score(event, flow.state)
    assert await flow.state.get_data() == {}
    assert not flow.repo.ratings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["corrupt_session", "legacy_repeat", "revoked_owner"]
)
async def test_rating_save_preserves_legacy_errors_and_rejects_revoked_owner(
    flow, case
):
    from ugc_bot.application.errors import RatingAlreadyExistsError

    await flow.state.update_data(
        order_id="bad" if case == "corrupt_session" else str(flow.order_id),
        blogger_id=str(flow.blogger_id),
        score=4,
    )
    service = flow.service
    if case == "legacy_repeat":
        service = NS(
            rate_blogger=AsyncMock(
                side_effect=RatingAlreadyExistsError("existing")
            )
        )
    if case == "revoked_owner":
        flow.eligibility.owners[flow.order_id] = uuid4()
    event = message()
    await handlers.handle_rating_comment(
        event, flow.state, service, flow.roles, flow.managers
    )
    assert not flow.repo.ratings
    assert await flow.state.get_state() is None
    event.answer.assert_awaited_once()


def test_all_new_rating_labels_are_localized_and_menu_entry_registered():
    from ugc_bot.bot.telegram.handlers.keyboards import (
        advertiser_menu_inline_keyboard,
    )
    from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
    from ugc_bot.bot.texts.defaults.rating import RATING_TEXTS

    for locale in ("ru", "en", "kk", "be", "uz"):
        assert set(RATING_TEXTS[locale]) == set(RATING_TEXTS["ru"])
        buttons = [
            button
            for row in advertiser_menu_inline_keyboard(
                DEFAULT_TEXTS[locale]
            ).rows
            for button in row
        ]
        entry = next(
            button
            for button in buttons
            if button.callback_data == "customer:ratings"
        )
        assert entry.text == DEFAULT_TEXTS[locale]["btn_rate_creators"]
