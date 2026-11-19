"""Visible navigation for both profiles and unfinished forms."""

from dataclasses import replace
from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram import Bot, Router
from aiogram.methods import SendMessage
from aiogram.types import Update

import ugc_bot.app as bot_app
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_blogger_profile,
    create_test_user,
)
from tests.helpers.fakes import FakeMessengerClient
from tests.helpers.services import build_profile_service
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.services.advertiser_registration_service import (
    AdvertiserRegistrationService,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers.profile import EditProfileStates
from ugc_bot.bot.telegram.navigation import (
    HOME,
    NavigationClient,
    navigation_keyboard,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
    build_keyboard_markup,
)


@pytest_asyncio.fixture
async def chat(
    monkeypatch,
    config,
    bot_texts_service,
    user_repo,
    blogger_repo,
    advertiser_repo,
    fake_tm,
):
    config.webhook.webhook_base_url = "https://bot.example.test"
    profiles = build_profile_service(user_repo, blogger_repo, advertiser_repo)
    roles = UserRoleService(user_repo=user_repo)
    services = {
        "metrics_collector": MagicMock(),
        "user_role_service": roles,
        "profile_service": profiles,
        "bot_texts_service": bot_texts_service,
        "referral_service": SimpleNamespace(parse_referral_code=lambda _: None),
        "manager_applications": SimpleNamespace(open=AsyncMock()),
        "blogger_registration_service": BloggerRegistrationService(
            user_repo=user_repo,
            blogger_repo=blogger_repo,
            transaction_manager=fake_tm,
        ),
        "currency_symbol": "₽",
        "max_order_price": 1000000,
        "order_service": SimpleNamespace(
            list_by_advertiser=AsyncMock(return_value=[])
        ),
        "offer_response_service": SimpleNamespace(
            list_by_blogger=AsyncMock(return_value=[])
        ),
        "advertiser_registration_service": AdvertiserRegistrationService(
            user_repo=user_repo,
            advertiser_repo=advertiser_repo,
            transaction_manager=fake_tm,
        ),
    }
    monkeypatch.setattr(
        bot_app,
        "Container",
        lambda _: SimpleNamespace(build_bot_services=lambda: services),
    )
    # Keep production handlers, filters, ordering AND navigation middleware.
    for name, original in list(vars(bot_app).items()):
        if name.endswith("_router") and isinstance(original, Router):
            fresh = Router()
            for name_, observer in original.observers.items():
                target = fresh.observers[name_]
                target.handlers.extend(observer.handlers)
                for middleware in observer.middleware._middlewares:
                    target.middleware(middleware)
                for filter_ in observer._handler.filters or []:
                    target.filter(filter_.callback)
            monkeypatch.setattr(bot_app, name, fresh)
    dispatcher = bot_app.build_dispatcher(config)
    bot = Bot("123:" + "A" * 35)
    requests = []

    async def request(_, method, **kwargs):
        requests.append(method)
        return True

    bot.session.make_request = request
    dispatcher["messenger_client"] = TelegramMessengerClient(bot)
    state = dispatcher.fsm.get_context(bot=bot, chat_id=777, user_id=777)
    ids = count(1)
    person = {"id": 777, "is_bot": False, "first_name": "Candidate"}

    async def send(text=None, callback=None):
        update_id = next(ids)
        message = {
            "message_id": update_id,
            "date": int(datetime.now(timezone.utc).timestamp()),
            "chat": {"id": 777, "type": "private"},
            "from": person,
            "text": text or "previous bot message",
        }
        event = {"message": message}
        if callback:
            event = {
                "callback_query": {
                    "id": str(update_id),
                    "from": person,
                    "chat_instance": "synthetic",
                    "message": message,
                    "data": callback,
                }
            }
        before = len(requests)
        await dispatcher.feed_update(
            bot, Update.model_validate({"update_id": update_id, **event})
        )
        return [r for r in requests[before:] if isinstance(r, SendMessage)]

    yield SimpleNamespace(
        send=send,
        state=state,
        services=services,
        requests=requests,
        roles=roles,
        profiles=profiles,
    )
    await dispatcher.storage.close()
    await bot.session.close()


def buttons(message):
    markup = message.reply_markup
    return [b for row in getattr(markup, "inline_keyboard", []) for b in row]


def action(message, prefix):
    return next(
        b.callback_data
        for b in buttons(message)
        if (b.callback_data or "").startswith(prefix)
    )


@pytest.mark.asyncio
async def test_visible_home_from_chat_form_preserves_answers_until_exit(chat):
    main = (await chat.send("/start"))[-1]
    assert {b.callback_data for b in buttons(main)} == {
        "role:creator",
        "role:advertiser",
        "mgr:open",
        "partner:open",
    }
    registration = (await chat.send(callback="role:creator"))[-1]
    assert any(
        b.web_app and b.web_app.url.endswith("view=register-blogger")
        for b in buttons(registration)
    )
    assert action(registration, HOME) == HOME
    phone = (await chat.send(callback="creator:create"))[-1]
    assert phone.reply_markup.keyboard[0][0].request_contact
    assert phone.reply_markup.keyboard[-1][0].text == "🏠 Главное меню"
    await chat.state.update_data(phone="unsaved-answer")
    current = await chat.state.get_state()
    confirm = (await chat.send("🏠 Главное меню"))[-1]
    assert await chat.state.get_state() == current
    assert (await chat.state.get_data())["phone"] == "unsaved-answer"
    old_exit = action(confirm, "nav:exit:")
    await chat.send(callback=action(confirm, "nav:continue:"))
    assert await chat.state.get_state() == current
    # Continuing invalidates the old confirmation.
    await chat.send(callback=old_exit)
    assert await chat.state.get_state() == current
    confirm = (await chat.send(callback=HOME))[-1]
    # Another answer after confirmation must not be discarded by a stale tap.
    await chat.state.update_data(phone="new-answer")
    refreshed = (await chat.send(callback=action(confirm, "nav:exit:")))[-1]
    assert await chat.state.get_state() == current
    assert (await chat.state.get_data())["phone"] == "new-answer"
    main = (await chat.send(callback=action(refreshed, "nav:exit:")))[-1]
    assert await chat.state.get_state() is None
    assert await chat.state.get_data() == {}
    assert "mgr:open" in {b.callback_data for b in buttons(main)}
    registration = (await chat.send(callback="role:advertiser"))[-1]
    assert any(
        b.web_app and b.web_app.url.endswith("view=register-advertiser")
        for b in buttons(registration)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["blogger", "advertiser"])
async def test_profile_agreement_only_confirms_the_displayed_role(
    chat,
    role,
    user_repo,
    blogger_repo,
    advertiser_repo,
):
    user = await create_test_user(user_repo, external_id="777")
    blogger = await create_test_blogger_profile(blogger_repo, user.user_id)
    advertiser = await create_test_advertiser_profile(
        advertiser_repo, user.user_id
    )
    await blogger_repo.save(replace(blogger, agreement_confirmed_at=None))
    await advertiser_repo.save(replace(advertiser, agreement_confirmed_at=None))
    messages = await chat.send(callback="profile:menu:profile:" + role)
    assert action(messages[-1], "profile:agree") == "profile:agree"
    messages = await chat.send(callback="profile:agree")
    assert ("instagram.com" in messages[-1].text) == (role == "blogger")
    blogger = await chat.profiles.get_blogger_profile(user.user_id)
    advertiser = await chat.profiles.get_advertiser_profile(user.user_id)
    assert (blogger.agreement_confirmed_at is not None) == (role == "blogger")
    assert (advertiser.agreement_confirmed_at is not None) == (
        role == "advertiser"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "current",
    [
        "BloggerRegistrationStates:phone",
        "AdvertiserRegistrationStates:name",
        "EditProfileStates:entering_value",
        "OrderCreationStates:offer_text",
    ],
)
@pytest.mark.parametrize(
    "target", [HOME, "role:advertiser", "partner:open", "mgr:open"]
)
async def test_navigation_confirms_leaving_forms(chat, current, target):
    await chat.state.set_state(current)
    await chat.state.update_data(answer="unsaved")
    confirm = (await chat.send(callback=target))[-1]
    assert action(confirm, "nav:exit:")
    assert await chat.state.get_state() == current
    assert (await chat.state.get_data())["answer"] == "unsaved"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["blogger", "advertiser"])
async def test_role_menu_view_and_edit_remain_scoped_with_two_profiles(
    chat,
    role,
    user_repo,
    blogger_repo,
    advertiser_repo,
):
    user = await create_test_user(user_repo, external_id="777", username="Test")
    await create_test_blogger_profile(blogger_repo, user.user_id)
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    selector = "creator" if role == "blogger" else role
    menu = (await chat.send(callback="role:" + selector))[-1]
    assert (
        action(menu, "profile:menu:profile") == "profile:menu:profile:" + role
    )
    assert action(menu, "profile:menu:edit") == "profile:menu:edit:" + role
    assert action(menu, "profile:menu:orders") == "profile:menu:orders:" + role
    profile = (await chat.send(callback=action(menu, "profile:menu:profile")))[
        -1
    ]
    assert ("instagram.com" in profile.text) == (role == "blogger")
    assert action(profile, HOME) == HOME
    orders = (await chat.send(callback=action(menu, "profile:menu:orders")))[-1]
    assert action(orders, HOME) == HOME
    if role == "advertiser":
        chat.services["order_service"].list_by_advertiser.assert_awaited_once()
        chat.services[
            "offer_response_service"
        ].list_by_blogger.assert_not_awaited()
    else:
        chat.services[
            "offer_response_service"
        ].list_by_blogger.assert_awaited_once()
        chat.services["order_service"].list_by_advertiser.assert_not_awaited()
    editing = (await chat.send(callback=action(profile, "profile:menu:edit")))[
        -1
    ]
    assert (
        await chat.state.get_state() == EditProfileStates.choosing_field.state
    )
    assert (await chat.state.get_data())["edit_profile_type"] == role
    fields = {b.callback_data for b in buttons(editing)}
    assert ("profile:field:brand" in fields) == (role == "advertiser")
    if role == "advertiser":
        await chat.send(callback="profile:field:brand")
        updated = await chat.send("New brand")
        assert "New brand" in updated[-1].text
        assert "instagram.com" not in updated[-1].text
        assert action(updated[-1], "profile:menu:profile").endswith(
            ":advertiser"
        )
        assert (
            await chat.profiles.get_advertiser_profile(user.user_id)
        ).brand == "New brand"
    assert await chat.profiles.get_blogger_profile(user.user_id) is not None
    other = "advertiser" if role == "blogger" else "creator"
    result = (await chat.send(callback=HOME))[-1]
    if await chat.state.get_state():
        await chat.send(callback=action(result, "nav:exit:"))
    menu = (await chat.send(callback="role:" + other))[-1]
    profile = (await chat.send(callback=action(menu, "profile:menu:profile")))[
        -1
    ]
    assert ("instagram.com" in profile.text) == (role == "advertiser")


@pytest.mark.parametrize("locale", DEFAULT_TEXTS)
@pytest.mark.parametrize("kind", list(KeyboardKind) + [None])
def test_navigation_preserves_native_keyboard_actions(locale, kind):
    original = (
        Keyboard(kind, [[Button("Phone", request_contact=True)]])
        if kind
        else None
    )
    keyboard = navigation_keyboard(original, DEFAULT_TEXTS[locale])
    markup = build_keyboard_markup(keyboard)
    rows = (
        markup.inline_keyboard
        if keyboard.kind == KeyboardKind.INLINE
        else markup.keyboard
    )
    assert rows[-1][0].text == DEFAULT_TEXTS[locale]["btn_main_menu"]
    if kind == KeyboardKind.REPLY:
        assert rows[0][0].request_contact


@pytest.mark.asyncio
async def test_navigation_does_not_change_messages_to_other_recipients():
    client = FakeMessengerClient()
    wrapped = NavigationClient(client, "777", DEFAULT_TEXTS["ru"], "blogger")
    await wrapped.send_text(chat_id="888", text="message")
    assert client.sent_text[0]["keyboard"] is None
