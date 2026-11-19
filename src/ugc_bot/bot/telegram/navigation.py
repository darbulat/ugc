"""Visible navigation for Telegram customer/creator screens only."""

from dataclasses import replace
from typing import Any

from aiogram import BaseMiddleware

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS

HOME = "nav:home"
SCOPED_ACTIONS = (
    "profile:menu:profile",
    "profile:menu:edit",
    "profile:menu:orders",
)


def callback_role(value: str | None) -> str | None:
    """Only role selectors and known scoped actions carry a role."""
    for role in ("blogger", "advertiser"):
        if value in {f"{action}:{role}" for action in SCOPED_ACTIONS} | {
            f"profile:type:{role}"
        }:
            return role
    return None


def navigation_keyboard(keyboard, texts, role=None):
    """Keep contact/location and inline actions, adding a visible way home."""
    if keyboard and keyboard.kind != KeyboardKind.REMOVE:
        rows = [
            [
                replace(button, callback_data=f"{button.callback_data}:{role}")
                if role and button.callback_data in SCOPED_ACTIONS
                else button
                for button in row
            ]
            for row in keyboard.rows
        ]
        # The role selector is already the main menu.
        if any(b.callback_data == "role:creator" for r in rows for b in r):
            return keyboard
        if not any(b.callback_data == HOME for r in rows for b in r):
            rows.append(
                [
                    Button(
                        texts["btn_main_menu"],
                        callback_data=HOME
                        if keyboard.kind == KeyboardKind.INLINE
                        else None,
                    )
                ]
            )
        return replace(keyboard, rows=rows)
    if keyboard and keyboard.kind == KeyboardKind.REMOVE:
        return Keyboard(
            kind=KeyboardKind.REPLY,
            rows=[[Button(texts["btn_main_menu"])]],
            resize=True,
            is_persistent=True,
        )
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(texts["btn_main_menu"], callback_data=HOME)]],
    )


class NavigationClient:
    """Decorate replies to the current user only."""

    def __init__(self, client, chat_id, texts, role):
        self.client, self.chat_id = client, str(chat_id)
        self.texts, self.profile_role = texts, role

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    def _kwargs(self, kwargs):
        if str(kwargs.get("chat_id")) == self.chat_id:
            kwargs["keyboard"] = navigation_keyboard(
                kwargs.get("keyboard"), self.texts, self.profile_role
            )
        return kwargs

    async def send_text(self, **kwargs):
        return await self.client.send_text(**self._kwargs(kwargs))

    async def send_photo(self, **kwargs):
        return await self.client.send_photo(**self._kwargs(kwargs))

    async def edit_text(self, **kwargs):
        return await self.client.edit_text(**self._kwargs(kwargs))


class NavigationMiddleware(BaseMiddleware):
    """Applied to creator/client routers, never the manager or MAX routers."""

    def __init__(self, role=None):
        self.role = role

    async def __call__(self, handler, event, data):
        client = data.get("messenger_client")
        message = getattr(event, "message", None) or event
        chat = getattr(message, "chat", None)
        if client is not None and chat is not None and chat.type == "private":
            state = data.get("state")
            stored = await state.get_data() if state else {}
            role = (
                callback_role(getattr(event, "data", None))
                or self.role
                or stored.get("edit_profile_type")
                or stored.get("profile_view_role")
            )
            if role not in ("blogger", "advertiser"):
                role = None
            locale = data.get("user_locale", "ru")
            texts = DEFAULT_TEXTS.get(locale, DEFAULT_TEXTS["ru"]).copy()
            service = data.get("bot_texts_service")
            if service:
                texts["btn_main_menu"] = await service.get(
                    "btn_main_menu", locale
                )
            data["messenger_client"] = NavigationClient(
                client, chat.id, texts, role
            )
        return await handler(event, data)
