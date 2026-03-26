"""Tests for language_inline_keyboard."""

from ugc_bot.application.messenger.dto import KeyboardKind
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_LANG_PREFIX,
    language_inline_keyboard,
)
from ugc_bot.domain.entities import Language


def test_language_keyboard_builds_buttons():
    languages = [
        Language(code="ru", name_native="Русский"),
        Language(code="en", name_native="English"),
    ]
    kb = language_inline_keyboard(languages)
    assert kb.kind == KeyboardKind.INLINE
    assert len(kb.rows) == 1  # 2 per row, 2 languages = 1 row
    assert kb.rows[0][0].callback_data == f"{CALLBACK_LANG_PREFIX}ru"
    assert kb.rows[0][1].callback_data == f"{CALLBACK_LANG_PREFIX}en"
    assert kb.rows[0][0].text == "Русский"


def test_language_keyboard_empty_returns_empty():
    kb = language_inline_keyboard([])
    assert kb.rows == []
