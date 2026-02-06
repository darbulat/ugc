"""Shared helpers for bot handlers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable
from uuid import UUID

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import (
    CallbackQuery,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.bot.handlers.draft_prompts import get_draft_prompt
from ugc_bot.bot.handlers.keyboards import (
    DRAFT_RESTORED_TEXT,
    RESUME_DRAFT_BUTTON_TEXT,
    START_OVER_BUTTON_TEXT,
    draft_choice_keyboard,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus


@dataclass(slots=True)
class RateLimiter:
    """Simple in-memory rate limiter."""

    limit: int
    window_seconds: float
    _events: dict[str, list[float]] = field(default_factory=dict)

    def allow(self, key: str) -> bool:
        """Return True when request is allowed."""

        now = monotonic()
        window_start = now - self.window_seconds
        events = [ts for ts in self._events.get(key, []) if ts >= window_start]
        if len(events) >= self.limit:
            self._events[key] = events
            return False
        events.append(now)
        self._events[key] = events
        return True


async def send_with_retry(
    bot,
    chat_id: int,
    text: str,
    *,
    retries: int,
    delay_seconds: float,
    logger: logging.Logger,
    extra: dict[str, Any] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a message with retry on failures."""

    for attempt in range(1, retries + 1):
        try:
            await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            return True
        except Exception as exc:  # pragma: no cover - depends on network errors
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
            if attempt < retries:
                await asyncio.sleep(delay_seconds)
    return False


def format_agreements_message(
    config: AppConfig,
    intro: str = "Профиль создан. Ознакомьтесь с документами и подтвердите.",
) -> str:
    """Build agreements text with clickable document links (HTML).

    Args:
        config: Application config with docs URLs.
        intro: Introductory text before document links.
        use_emoji: If True, add emoji prefixes to link labels.

    Returns:
        Formatted HTML string with document links.
    """
    parts = [intro, ""]
    offer_label = "📄 Оферта"
    privacy_label = "🔒 Политика конфиденциальности"
    consent_label = "🧾 Согласие на обработку персональных данных"
    if config.docs.docs_offer_url:
        parts.append(
            f'<a href="{config.docs.docs_offer_url}">{offer_label}</a>'
        )
    if config.docs.docs_privacy_url:
        parts.append(
            f'<a href="{config.docs.docs_privacy_url}">{privacy_label}</a>'
        )
    if config.docs.docs_consent_url:
        parts.append(
            f'<a href="{config.docs.docs_consent_url}">{consent_label}</a>'
        )
    if len(parts) == 2:
        parts.append("Подтвердите согласие с документами платформы.")
    return "\n".join(parts)


async def handle_role_choice(
    message: Message,
    user_role_service: Any,
    state: FSMContext,
    *,
    profile_getter: Callable[[UUID], Awaitable[object | None]],
    choose_action_text: str,
    intro_text: str,
    menu_keyboard: Callable[[], ReplyKeyboardMarkup],
    start_keyboard: Callable[[], ReplyKeyboardMarkup],
) -> None:
    """Handle role selection: persist role, show menu or intro.

    Use for both creator and advertiser role choice handlers.
    """
    if message.from_user is None:
        return
    await state.clear()
    external_id = str(message.from_user.id)
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    username = user.username if user else ""

    await user_role_service.set_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        username=username,
        role_chosen=True,
        telegram_username=message.from_user.username,
    )

    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    profile = await profile_getter(user.user_id) if user else None
    if profile is not None:
        await message.answer(
            choose_action_text,
            reply_markup=menu_keyboard(),
        )
    else:
        await message.answer(
            intro_text,
            reply_markup=start_keyboard(),
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
    message: Message,
    user_role_service: Any,
    *,
    user_not_found_msg: str,
    blocked_msg: str,
    pause_msg: str,
) -> User | None:
    """Resolve user, check blocked/pause; return None if not allowed."""
    if message.from_user is None:
        return None
    external_id = str(message.from_user.id)
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await message.answer(user_not_found_msg)
        return None
    if user.status == UserStatus.BLOCKED:
        await message.answer(blocked_msg)
        return None
    if user.status == UserStatus.PAUSE:
        await message.answer(pause_msg)
        return None
    return user


async def get_user_and_ensure_allowed_callback(
    callback: CallbackQuery,
    user_role_service: Any,
    *,
    user_not_found_msg: str,
    blocked_msg: str,
    pause_msg: str,
) -> User | None:
    """Resolve user from callback; return None if blocked/pause."""
    if callback.from_user is None:
        return None
    external_id = str(callback.from_user.id)
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
    )
    if user is None:
        await callback.answer(user_not_found_msg)
        return None
    if user.status == UserStatus.BLOCKED:
        await callback.answer(blocked_msg)
        return None
    if user.status == UserStatus.PAUSE:
        await callback.answer(pause_msg)
        return None
    return user


async def handle_draft_choice(
    message: Message,
    state: FSMContext,
    fsm_draft_service: FsmDraftService,
    *,
    flow_type: str,
    user_id_key: str,
    first_state: State,
    first_prompt: str,
    first_keyboard: ReplyKeyboardMarkup | ReplyKeyboardRemove,
    session_expired_msg: str,
    draft_used_msg: str = "Черновик использован. Начинаем с начала.",
    keyboard_for_restored_state: Callable[
        [str, dict], ReplyKeyboardMarkup | ReplyKeyboardRemove
    ]
    | None = None,
) -> None:
    """Handle draft restore: resume, start over, or ask to choose."""
    text = (message.text or "").strip()
    data = await state.get_data()
    user_id = parse_user_id_from_state(data, key=user_id_key)
    if user_id is None:
        await state.clear()
        await message.answer(session_expired_msg)
        return

    if text == RESUME_DRAFT_BUTTON_TEXT:
        draft = await fsm_draft_service.get_draft(user_id, flow_type)
        if draft is None:
            await message.answer(draft_used_msg)
            await message.answer(first_prompt, reply_markup=first_keyboard)
            await state.set_state(first_state)
            return
        await fsm_draft_service.delete_draft(user_id, flow_type)
        await state.update_data(**draft.data)
        await state.set_state(draft.state_key)
        prompt = get_draft_prompt(draft.state_key, draft.data)
        reply_markup = (
            keyboard_for_restored_state(draft.state_key, draft.data)
            if keyboard_for_restored_state is not None
            else first_keyboard
        )
        await message.answer(
            f"{DRAFT_RESTORED_TEXT}\n\n{prompt}",
            reply_markup=reply_markup,
        )
        return

    if text == START_OVER_BUTTON_TEXT:
        await fsm_draft_service.delete_draft(user_id, flow_type)
        await message.answer(first_prompt, reply_markup=first_keyboard)
        await state.set_state(first_state)
        return

    await message.answer(
        "Выберите «Продолжить» или «Начать заново».",
        reply_markup=draft_choice_keyboard(),
    )
