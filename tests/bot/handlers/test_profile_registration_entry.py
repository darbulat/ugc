"""Role selection offers the existing chat flow and the correct app form."""

import pytest

from tests.helpers.fakes import (
    FakeCallback,
    FakeFSMContext,
    FakeMessage,
    FakeUser,
)
from tests.helpers.services import build_profile_service
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.telegram.handlers import (
    advertiser_registration as advertiser,
)
from ugc_bot.bot.telegram.handlers import blogger_registration as blogger
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ADV_START,
    CALLBACK_CREATOR_CREATE,
    advertiser_start_keyboard,
    creator_start_keyboard,
)
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.infrastructure.messenger.telegram.client import (
    build_keyboard_markup,
)

ROLES = [
    ("blogger", creator_start_keyboard, CALLBACK_CREATOR_CREATE),
    ("advertiser", advertiser_start_keyboard, CALLBACK_ADV_START),
]


@pytest.mark.parametrize("locale", DEFAULT_TEXTS)
@pytest.mark.parametrize("role,builder,chat_callback", ROLES)
def test_role_buttons_open_app_form_or_existing_chat_flow(
    locale, role, builder, chat_callback
):
    texts = DEFAULT_TEXTS[locale]
    keyboard = builder(
        texts, miniapp_base_url="https://bot.example.test/service/"
    )
    markup = build_keyboard_markup(keyboard)
    assert len(markup.inline_keyboard) == 2
    app, chat = (row[0] for row in markup.inline_keyboard)
    assert app.text == texts["btn_fill_profile_app"]
    assert app.web_app.url == (
        "https://bot.example.test/service/miniapp/app.html"
        f"?view=register-{role}"
    )
    assert app.callback_data is None
    assert chat.text == texts["btn_fill_profile_chat"]
    assert chat.callback_data == chat_callback
    assert chat.web_app is None


@pytest.mark.parametrize(
    "url",
    ["", " ", "http://bot.test", "https://[", "https://bot.test?key=value"],
)
@pytest.mark.parametrize("role,builder,chat_callback", ROLES)
def test_missing_or_invalid_app_url_keeps_working_chat_button(
    url, role, builder, chat_callback
):
    keyboard = builder(DEFAULT_TEXTS["ru"], miniapp_base_url=url)
    assert len(keyboard.rows) == 1
    assert keyboard.rows[0][0].callback_data == chat_callback
    assert keyboard.rows[0][0].web_app_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["blogger", "advertiser"])
@pytest.mark.parametrize("inline", [False, True])
async def test_role_handler_offers_app_and_chat_still_starts_registration(
    role,
    inline,
    user_repo,
    config,
    bot_texts_service,
    messenger_client,
    event_adapter,
):
    config.webhook.webhook_base_url = "https://bot.example.test"
    users = UserRoleService(user_repo=user_repo)
    profiles = build_profile_service(user_repo)
    user = FakeUser(42, "candidate", "Candidate")
    message = FakeMessage(user=user)
    state = FakeFSMContext()
    if role == "blogger":
        choose = (
            blogger.choose_creator_role_inline
            if inline
            else blogger.choose_creator_role
        )
    else:
        choose = (
            advertiser.choose_advertiser_role_inline
            if inline
            else advertiser.choose_advertiser_role
        )
    callback_role = "creator" if role == "blogger" else "advertiser"
    event = (
        FakeCallback("role:" + callback_role, user, message)
        if inline
        else message
    )
    await choose(
        event,
        state=state,
        user_role_service=users,
        profile_service=profiles,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    keyboard = messenger_client.sent_text[-1]["keyboard"]
    assert len(keyboard.rows) == 2
    assert keyboard.rows[0][0].web_app_url.endswith(f"?view=register-{role}")
    chat = keyboard.rows[1][0]
    callback = FakeCallback(chat.callback_data, user, message)
    kwargs = {
        "state": state,
        "user_role_service": users,
        "config": config,
        "bot_texts_service": bot_texts_service,
        "messenger_client": messenger_client,
        "event_adapter": event_adapter,
    }
    if role == "blogger":
        await blogger.start_registration_inline(callback, **kwargs)
        assert state.state == blogger.BloggerRegistrationStates.phone.state
    else:
        await advertiser.handle_advertiser_start_callback(
            callback, profile_service=profiles, **kwargs
        )
        assert state.state == advertiser.AdvertiserRegistrationStates.name.state
