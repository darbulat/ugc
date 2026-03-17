"""E2E tests for referral system with multi-currency support.

Requires: bot running with webhook, TELEGRAM_E2E_* env vars set.
Tests are language-agnostic: assertions accept bot replies in RU or EN.
"""

import os

import pytest

from tests.e2e.telegram_client import (
    click_inline_and_get_reply,
    send_and_get_reply,
)


def _has_any(text: str | None, *keywords: str) -> bool:
    """Return True if text contains any of the keywords (case-insensitive)."""
    if not text:
        return False
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords)


def _is_language_prompt(text: str | None) -> bool:
    return _has_any(
        text, "язык", "language", "Choose language", "Выберите язык"
    )


def _is_country_prompt(text: str | None) -> bool:
    return _has_any(
        text, "страну", "country", "Россия", "Беларусь", "Казахстан"
    )


async def _maybe_select_language_and_country(
    client, entity, text: str | None, timeout: float = 15.0
) -> str | None:
    """Handle the full onboarding prologue: language -> country -> role."""
    if _is_language_prompt(text):
        text = await click_inline_and_get_reply(
            client, entity, "lang:ru", timeout=timeout
        )
    if _is_country_prompt(text):
        text = await click_inline_and_get_reply(
            client, entity, "country:ru", timeout=timeout
        )
    return text


async def _ensure_user_profile(client, entity, bot_username: str) -> None:
    """Ensure user has a profile (blogger or advertiser). Skip if not."""
    text = await send_and_get_reply(
        client, entity, bot_username, "/start", timeout=20
    )
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )
    assert text and _has_any(
        text,
        "UGC",
        "профиль",
        "profile",
        "Выберите",
        "Choose",
        "действие",
        "action",
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_command_shows_stats(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Send /referral and verify stats text with currency info is shown."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    # Stats message should contain referral-related keywords
    assert _has_any(
        text,
        # RU labels
        "реферал",
        "креатор",
        "заказ",
        "доход",
        "баланс",
        "выплачено",
        "статистика",
        # EN labels
        "referral",
        "creator",
        "order",
        "income",
        "balance",
        "paid",
        "stats",
        # Currency symbols or codes that might appear
        "₽",
        "RUB",
        "USD",
        "GEL",
        "₸",
        "KZT",
        # Referral link
        "t.me",
    ), f"Expected referral stats text, got: {text!r}"


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_command_shows_link(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Send /referral and verify referral link is present."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    # User's own /referral should include a referral link with ref_ code
    assert _has_any(
        text,
        "t.me",
        "ref_",
        "реферальная ссылка",
        "referral link",
    ), f"Expected referral link in response, got: {text!r}"


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_stats_contains_currency_info(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Verify /referral response mentions currency amounts or zero state."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    # Stats must show either currency amounts (e.g. "100.00 ₽") or zero-state
    # labels like "0" or creator count
    has_currency = _has_any(
        text,
        "₽",
        "₸",
        "₾",
        "$",
        "RUB",
        "USD",
        "GEL",
        "KZT",
        "BYN",
    )
    has_numbers = any(c.isdigit() for c in (text or ""))
    assert has_currency or has_numbers, (
        f"Expected currency info or numeric stats, got: {text!r}"
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_list_command(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Send /referral_list and verify list or empty message."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral_list", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral_list"
    # Should show either a list of referrals or "no referrals" message
    assert _has_any(
        text,
        # List content
        "реферал",
        "referral",
        "страница",
        "page",
        "выполнено",
        "done",
        "заказ",
        "order",
        # Empty state
        "никого",
        "nobody",
        "пусто",
        "empty",
        "нет",
        "no",
        # Pending block
        "не заполнили",
        "not filled",
        "профиль",
        "profile",
    ), f"Expected referral list or empty message, got: {text!r}"


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_payout_button_when_no_balance(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Click payout for RUB when balance is 0 — expect alert."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )
    assert text is not None, "Bot did not reply to /referral"

    # Try clicking payout for RUB — user likely has 0 balance
    reply = await click_inline_and_get_reply(
        client, entity, "referral:payout:RUB", timeout=15
    )
    # Either no such button (reply is None) or bot shows unavailable alert
    if reply is not None:
        assert _has_any(
            reply,
            "недоступ",
            "unavailable",
            "уже",
            "already",
            "нет средств",
            "no funds",
            "заявка",
            "request",
            "выплат",
            "payout",
            "отправлен",
            "sent",
        ), f"Unexpected payout response: {reply!r}"
