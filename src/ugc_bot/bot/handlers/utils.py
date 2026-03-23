"""Shared helpers for bot handlers."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, cast
from uuid import UUID

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    Invoice,
    Keyboard,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.ports import CountryRepository
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.messenger.telegram.adapter import (
    TelegramEventAdapter,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    build_keyboard_markup,
    is_user_blocked_bot,
)


def _resolve_user_lookup_from_message(
    message: IncomingMessage | Any,
    messenger_client: MessengerClient | Any,
    user_role_service: Any | None,
) -> tuple[
    str,
    MessengerType,
    str,
    Callable[..., Awaitable[None]] | None,
    MessengerClient | None,
    Any,
]:
    """Normalize user lookup inputs for messages."""
    if user_role_service is None:
        user_role_service = messenger_client
        messenger_client = None
    if isinstance(message, IncomingMessage):
        external_id = message.user.external_id
        messenger_type = message.user.messenger_type
        chat_id = message.chat_id
        answer = None
    else:
        from_user = getattr(message, "from_user", None)
        external_id = str(getattr(from_user, "id", ""))
        messenger_type = MessengerType.TELEGRAM
        chat_id = external_id
        answer = getattr(message, "answer", None)
    return (
        external_id,
        messenger_type,
        chat_id,
        answer,
        messenger_client,
        user_role_service,
    )


def _resolve_user_lookup_from_callback(
    callback: IncomingCallback | Any,
    messenger_client: MessengerClient | Any,
    user_role_service: Any | None,
) -> tuple[
    str,
    MessengerType,
    str,
    Callable[..., Awaitable[None]] | None,
    MessengerClient | None,
    Any,
]:
    """Normalize user lookup inputs for callbacks."""
    if user_role_service is None:
        user_role_service = messenger_client
        messenger_client = None
    if isinstance(callback, IncomingCallback):
        external_id = callback.user.external_id
        messenger_type = callback.user.messenger_type
        callback_id = callback.callback_id
        answer = None
    else:
        from_user = getattr(callback, "from_user", None)
        external_id = str(getattr(from_user, "id", ""))
        messenger_type = MessengerType.TELEGRAM
        callback_id = ""
        answer = getattr(callback, "answer", None)
    return (
        external_id,
        messenger_type,
        callback_id,
        answer,
        messenger_client,
        user_role_service,
    )


async def _send_text_or_answer(
    messenger_client: MessengerClient | None,
    *,
    chat_id: str,
    text: str,
    answer: Callable[..., Awaitable[None]] | None,
    keyboard: Keyboard | None = None,
) -> None:
    """Send message via messenger client or fallback answer."""
    if messenger_client is not None:
        await messenger_client.send_text(
            chat_id=chat_id, text=text, keyboard=keyboard
        )
    elif answer is not None:
        try:
            if keyboard is None:
                await answer(text)
            else:
                await answer(text, keyboard)
        except TypeError:  # pragma: no cover - depends on test doubles
            await answer(text)


async def _answer_callback_or_fallback(
    messenger_client: MessengerClient | None,
    *,
    callback_id: str,
    text: str,
    answer: Callable[[str], Awaitable[None]] | None,
) -> None:
    """Answer callback via messenger client or fallback answer."""
    if messenger_client is not None and callback_id:
        await messenger_client.answer_callback(
            callback_id=callback_id, text=text
        )
    elif answer is not None:
        await answer(text)


class LegacyMessengerClient:
    """Fallback messenger client using aiogram-like message/callback."""

    def __init__(self, event: object) -> None:
        """Initialize with aiogram-like Message or CallbackQuery."""
        self._event = event

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: object | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        """Send a text reply using the original event when possible."""
        _ = disable_preview
        markup = (
            build_keyboard_markup(keyboard)
            if isinstance(keyboard, Keyboard)
            else keyboard
        )
        message = getattr(self._event, "message", None)
        if message is not None:
            answer = getattr(message, "answer", None)
            if callable(answer):
                await answer(text, reply_markup=markup, parse_mode=parse_mode)
                return
        answer = getattr(self._event, "answer", None)
        if callable(answer):
            await answer(text, reply_markup=markup, parse_mode=parse_mode)
            return
        bot = getattr(self._event, "bot", None)
        if bot and hasattr(bot, "send_message"):
            await bot.send_message(
                chat_id=int(chat_id),
                text=text,
                reply_markup=markup,
                parse_mode=parse_mode,
            )

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: object | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Send a photo reply using the original event when possible."""
        markup = (
            build_keyboard_markup(keyboard)
            if isinstance(keyboard, Keyboard)
            else keyboard
        )
        bot = getattr(self._event, "bot", None)
        if bot and hasattr(bot, "send_photo"):
            await bot.send_photo(
                chat_id=int(chat_id),
                photo=file_id,
                caption=caption,
                reply_markup=markup,
                parse_mode=parse_mode,
            )

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: object | None = None,
        parse_mode: str | None = None,
    ) -> None:
        """Edit message text using the original event when possible."""
        _ = chat_id, message_id
        markup = (
            build_keyboard_markup(keyboard)
            if isinstance(keyboard, Keyboard)
            else keyboard
        )
        message = getattr(self._event, "message", None)
        if message is not None:
            edit_text = getattr(message, "edit_text", None)
            if callable(edit_text):
                await edit_text(
                    text, reply_markup=markup, parse_mode=parse_mode
                )
                return
        edit_text = getattr(self._event, "edit_text", None)
        if callable(edit_text):
            await edit_text(text, reply_markup=markup, parse_mode=parse_mode)

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: object | None = None,
    ) -> None:
        """Edit message reply markup using the original event when possible."""
        _ = chat_id, message_id
        markup = (
            build_keyboard_markup(keyboard)
            if isinstance(keyboard, Keyboard)
            else keyboard
        )
        message = getattr(self._event, "message", None)
        if message is not None:
            edit_markup = getattr(message, "edit_reply_markup", None)
            if callable(edit_markup):
                await edit_markup(reply_markup=markup)
                return
        edit_markup = getattr(self._event, "edit_reply_markup", None)
        if callable(edit_markup):
            await edit_markup(reply_markup=markup)

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Answer callback using the original event when possible."""
        _ = callback_id
        answer = getattr(self._event, "answer", None)
        if callable(answer):
            await answer(text=text or "", show_alert=show_alert)

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        """Send invoice using bot if available."""
        from aiogram.types import LabeledPrice

        bot = getattr(self._event, "bot", None)
        if bot and hasattr(bot, "send_invoice"):
            prices = [
                LabeledPrice(label=item.label, amount=item.amount_minor)
                for item in invoice.items
            ]
            kwargs: dict = {
                "chat_id": int(chat_id),
                "title": invoice.title,
                "description": invoice.description,
                "payload": invoice.payload,
                "provider_token": invoice.provider_token,
                "currency": invoice.currency,
                "prices": prices,
            }
            if (
                hasattr(invoice, "provider_data")
                and invoice.provider_data is not None
            ):
                kwargs["provider_data"] = invoice.provider_data
            if getattr(invoice, "need_email", False):
                kwargs["need_email"] = True
            if getattr(invoice, "send_email_to_provider", False):
                kwargs["send_email_to_provider"] = True
            await bot.send_invoice(**kwargs)


def resolve_messenger_dependencies(
    event: object,
    messenger_client: MessengerClient | None,
    event_adapter: MessengerEventAdapter | None,
) -> tuple[MessengerClient, MessengerEventAdapter]:
    """Resolve messenger dependencies for handler compatibility."""
    resolved_client = messenger_client or LegacyMessengerClient(event)
    resolved_adapter = cast(
        MessengerEventAdapter,
        event_adapter if event_adapter is not None else TelegramEventAdapter(),
    )
    return resolved_client, resolved_adapter


@dataclass(slots=True)
class RateLimiter:
    """Simple in-memory rate limiter."""

    limit: int
    window_seconds: float
    _events: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, key: str) -> bool:
        """Return True when request is allowed (sync)."""
        now = monotonic()
        window_start = now - self.window_seconds
        events = [ts for ts in self._events.get(key, []) if ts >= window_start]
        if len(events) >= self.limit:
            self._events[key] = events
            return False
        events.append(now)
        self._events[key] = events
        return True

    async def allow_async(self, key: str) -> bool:
        """Return True when request is allowed (async)."""
        return self.allow(key)


async def send_with_retry(
    messenger_client: Any,
    chat_id: str,
    text: str,
    *,
    retries: int,
    delay_seconds: float,
    logger: logging.Logger,
    extra: dict[str, Any] | None = None,
    on_bot_blocked: Callable[[], Awaitable[None]] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a message with retry on failures."""

    for attempt in range(1, retries + 1):
        try:
            if hasattr(messenger_client, "send_text"):
                await messenger_client.send_text(
                    chat_id=chat_id, text=text, **kwargs
                )
            elif hasattr(messenger_client, "send_message"):
                payload = dict(kwargs)
                if "keyboard" in payload and "reply_markup" not in payload:
                    payload["reply_markup"] = payload.pop("keyboard")
                await messenger_client.send_message(
                    chat_id=int(chat_id), text=text, **payload
                )
            else:
                raise AttributeError("Messenger client lacks send methods")
            return True
        except Exception as exc:
            logger.warning(
                "Send message failed",
                extra={
                    "attempt": attempt,
                    "retries": retries,
                    "chat_id": chat_id,
                    "error": str(exc),
                    **(extra or {}),
                },
            )
            if is_user_blocked_bot(exc):
                if on_bot_blocked is not None:
                    await on_bot_blocked()
                return False
            if attempt < retries:
                await asyncio.sleep(delay_seconds)
    return False


def format_agreements_message(
    config: AppConfig,
    intro: str | None = None,
    texts: dict[str, str] | None = None,
    country_code: str | None = None,
) -> str:
    """Build agreements text with clickable document links (HTML).

    Args:
        config: Application config with docs URLs.
        intro: Introductory text before document links. If None, uses
            texts["msg_agreements_intro_default"] when texts is provided.
        texts: Optional dict with keys msg_agreements_intro_default,
            msg_label_offer, msg_label_privacy, msg_label_consent,
            msg_confirm_docs_fallback. If None, uses built-in defaults.

    Returns:
        Formatted HTML string with document links.
    """
    texts = texts or {}
    if intro is None:
        intro = texts.get(
            "msg_agreements_intro_default",
            "Profile created. Please read the documents and confirm.",
        )
    offer_label = texts.get("msg_label_offer", "📄 Offer")
    privacy_label = texts.get("msg_label_privacy", "🔒 Privacy Policy")
    consent_label = texts.get(
        "msg_label_consent", "🧾 Consent to personal data processing"
    )
    fallback = texts.get(
        "msg_confirm_docs_fallback",
        "Please confirm your agreement with the platform documents.",
    )

    offer_url, privacy_url, consent_url = config.docs.get_urls_for_country(
        country_code
    )

    parts = [intro, ""]
    if offer_url:
        parts.append(f'<a href="{offer_url}">{offer_label}</a>')
    if privacy_url:
        parts.append(f'<a href="{privacy_url}">{privacy_label}</a>')
    if consent_url:
        parts.append(f'<a href="{consent_url}">{consent_label}</a>')
    if len(parts) == 2:
        parts.append(fallback)
    return "\n".join(parts)


async def handle_role_choice(
    message: IncomingMessage,
    messenger_client: MessengerClient,
    user_role_service: Any,
    state: StateStore,
    *,
    profile_getter: Callable[[UUID], Awaitable[object | None]],
    choose_action_text: str,
    intro_text: str,
    menu_keyboard: Callable[[dict[str, str]], Keyboard],
    start_keyboard: Callable[[dict[str, str]], Keyboard],
    texts: dict[str, str],
) -> None:
    """Handle role selection: persist role, show menu or intro.

    Use for both creator and advertiser role choice handlers.
    """
    if not message.user.external_id:
        return
    await state.clear()
    external_id = message.user.external_id
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=message.user.messenger_type,
    )
    username = user.username if user else ""

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=message.user.messenger_type,
        username=username,
        role_chosen=False,
        telegram_username=message.user.username,
    )

    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=message.user.messenger_type,
    )
    profile = await profile_getter(user.user_id) if user else None
    if profile is not None:
        await messenger_client.send_text(
            chat_id=message.chat_id,
            text=choose_action_text,
            keyboard=menu_keyboard(texts),
        )
    else:
        await messenger_client.send_text(
            chat_id=message.chat_id,
            text=intro_text,
            keyboard=start_keyboard(texts),
        )


def parse_user_id_from_state(data: dict, key: str = "user_id") -> UUID | None:
    """Parse user_id (or edit_user_id) from FSM state data as UUID.

    Returns UUID if value is present and valid, None otherwise.
    """
    raw = data.get(key)
    if raw is None:
        return None
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str):
        try:
            return UUID(raw)
        except (ValueError, TypeError):
            return None
    return None


async def get_user_and_ensure_allowed(
    message: IncomingMessage | Any,
    messenger_client: MessengerClient | Any,
    user_role_service: Any | None = None,
    *,
    user_not_found_msg: str,
    blocked_msg: str,
    pause_msg: str,
) -> User | None:
    """Resolve user, check blocked/pause; return None if not allowed."""
    (
        external_id,
        messenger_type,
        chat_id,
        answer,
        messenger_client,
        user_role_service,
    ) = _resolve_user_lookup_from_message(
        message, messenger_client, user_role_service
    )
    if not external_id:
        return None
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=messenger_type,
    )
    if user is None:
        await _send_text_or_answer(
            messenger_client,
            chat_id=chat_id,
            text=user_not_found_msg,
            answer=answer,
        )
        return None
    if user.status == UserStatus.BLOCKED:
        await _send_text_or_answer(
            messenger_client,
            chat_id=chat_id,
            text=blocked_msg,
            answer=answer,
        )
        return None
    if user.status == UserStatus.PAUSE:
        await _send_text_or_answer(
            messenger_client,
            chat_id=chat_id,
            text=pause_msg,
            answer=answer,
        )
        return None
    return user


async def get_user_and_ensure_allowed_callback(
    callback: IncomingCallback | Any,
    messenger_client: MessengerClient | Any,
    user_role_service: Any | None = None,
    *,
    user_not_found_msg: str,
    blocked_msg: str,
    pause_msg: str,
) -> User | None:
    """Resolve user from callback; return None if blocked/pause."""
    (
        external_id,
        messenger_type,
        callback_id,
        answer,
        messenger_client,
        user_role_service,
    ) = _resolve_user_lookup_from_callback(
        callback, messenger_client, user_role_service
    )
    if not external_id:
        return None
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=messenger_type,
    )
    if user is None:
        await _answer_callback_or_fallback(
            messenger_client,
            callback_id=callback_id,
            text=user_not_found_msg,
            answer=answer,
        )
        return None
    if user.status == UserStatus.BLOCKED:
        await _answer_callback_or_fallback(
            messenger_client,
            callback_id=callback_id,
            text=blocked_msg,
            answer=answer,
        )
        return None
    if user.status == UserStatus.PAUSE:
        await _answer_callback_or_fallback(
            messenger_client,
            callback_id=callback_id,
            text=pause_msg,
            answer=answer,
        )
        return None
    return user


async def resolve_currency_symbol(
    user: User | None,
    country_repo: "CountryRepository | None",
    default: str = "₽",
) -> str:
    """Return currency symbol for the user's country, falling back to default."""  # noqa: E501
    if user is None or country_repo is None:
        return default
    country_code = getattr(user, "country", None)
    if not country_code:
        return default
    country = await country_repo.get_by_code(country_code)
    return country.currency_symbol if country else default
