"""Main menu and a non-destructive exit from unfinished chat forms."""

import hashlib
import json
from secrets import token_hex

from aiogram import F, Router
from aiogram.filters import Filter

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.telegram.handlers.keyboards import role_inline_keyboard
from ugc_bot.bot.telegram.handlers.utils import resolve_messenger_dependencies
from ugc_bot.bot.telegram.navigation import HOME

router = Router()
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")
_EXIT = "nav:exit:"
_CONTINUE = "nav:continue:"
_MARKER = "_navigation_exit"
_FORMS = (
    "BloggerRegistrationStates:",
    "AdvertiserRegistrationStates:",
    "EditProfileStates:",
    "OrderCreationStates:",
)


def _form_active(current):
    return bool(current and current.startswith(_FORMS))


class FormActive(Filter):
    async def __call__(self, event, raw_state=None):
        return _form_active(raw_state)


class MainMenuText(Filter):
    async def __call__(self, message, bot_texts_service, user_locale="ru"):
        label = await bot_texts_service.get("btn_main_menu", user_locale)
        return (message.text or "").strip() == label.strip()


async def _fingerprint(state):
    data = await state.get_data()
    encoded = json.dumps(
        {k: v for k, v in data.items() if k != _MARKER},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(
        f"{await state.get_state()}:{encoded}".encode()
    ).hexdigest()


async def _confirm_exit(incoming, state, client, texts, locale):
    token = token_hex(8)
    await state.update_data(
        **{_MARKER: {"token": token, "fingerprint": await _fingerprint(state)}}
    )
    words = await texts.get_many(
        ["msg_exit_form", "btn_continue_form", "btn_exit_to_menu"], locale
    )
    await client.send_text(
        chat_id=incoming.chat_id,
        text=words["msg_exit_form"],
        keyboard=Keyboard(
            kind=KeyboardKind.INLINE,
            rows=[
                [
                    Button(
                        words["btn_continue_form"],
                        callback_data=_CONTINUE + token,
                    )
                ],
                [
                    Button(
                        words["btn_exit_to_menu"], callback_data=_EXIT + token
                    )
                ],
            ],
        ),
    )


async def _menu(incoming, state, client, texts, locale, manager_applications):
    if _form_active(await state.get_state()):
        await client.send_text(
            chat_id=incoming.chat_id,
            text=await texts.get("btn_main_menu", locale),
            keyboard=Keyboard(kind=KeyboardKind.REMOVE),
        )
    await state.clear()
    words = await texts.get_many(
        ["btn_creator", "btn_advertiser", "btn_partner_program"], locale
    )
    await client.send_text(
        chat_id=incoming.chat_id,
        text=await texts.get("start_message", locale),
        keyboard=role_inline_keyboard(
            words, include_manager=manager_applications is not None
        ),
    )


@router.message(MainMenuText())
async def main_menu_message(
    message,
    state,
    bot_texts_service,
    user_locale="ru",
    manager_applications=None,
    messenger_client=None,
    event_adapter=None,
):
    client, adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = adapter.from_message(message)
    if _form_active(await state.get_state()):
        await _confirm_exit(
            incoming, state, client, bot_texts_service, user_locale
        )
    else:
        await _menu(
            incoming,
            state,
            client,
            bot_texts_service,
            user_locale,
            manager_applications,
        )


@router.callback_query(F.data.in_({HOME, "change_role"}))
@router.callback_query(
    F.data.in_({"role:creator", "role:advertiser", "partner:open", "mgr:open"}),
    FormActive(),
)
async def main_menu_callback(
    callback,
    state,
    bot_texts_service,
    user_locale="ru",
    manager_applications=None,
    messenger_client=None,
    event_adapter=None,
):
    client, adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = adapter.from_callback(callback)
    await client.answer_callback(callback_id=incoming.callback_id)
    if _form_active(await state.get_state()):
        await _confirm_exit(
            incoming, state, client, bot_texts_service, user_locale
        )
    else:
        await _menu(
            incoming,
            state,
            client,
            bot_texts_service,
            user_locale,
            manager_applications,
        )


@router.callback_query(F.data.startswith(_EXIT) | F.data.startswith(_CONTINUE))
async def resolve_exit_callback(
    callback,
    state,
    bot_texts_service,
    user_locale="ru",
    manager_applications=None,
    messenger_client=None,
    event_adapter=None,
):
    client, adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = adapter.from_callback(callback)
    await client.answer_callback(callback_id=incoming.callback_id)
    data = await state.get_data()
    marker = data.get(_MARKER) or {}
    if (incoming.data or "").rsplit(":", 1)[-1] != marker.get("token"):
        return
    if incoming.message_id:
        await client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    if (incoming.data or "").startswith(_CONTINUE):
        await state.update_data(**{_MARKER: None})
        await client.send_text(
            chat_id=incoming.chat_id,
            text=await bot_texts_service.get("msg_continue_form", user_locale),
        )
    elif marker.get("fingerprint") != await _fingerprint(state):
        # An old confirmation must never discard answers entered afterwards.
        await _confirm_exit(
            incoming, state, client, bot_texts_service, user_locale
        )
    else:
        await _menu(
            incoming,
            state,
            client,
            bot_texts_service,
            user_locale,
            manager_applications,
        )
