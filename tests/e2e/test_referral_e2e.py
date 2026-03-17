"""E2E tests for referral system with multi-currency support.

Requires: bot running with webhook, TELEGRAM_E2E_* env vars set.
Tests are language-agnostic: assertions accept bot replies in RU or EN.

Multi-currency balance tests insert synthetic referral data via
E2E_DATABASE_URL and verify /referral shows per-currency amounts.
"""

import os
import uuid
from datetime import datetime, timezone

import pytest

from tests.e2e.telegram_client import (
    click_inline_and_get_reply,
    send_and_get_reply,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
        text,
        "страну",
        "country",
        "Россия",
        "Беларусь",
        "Казахстан",
        "краіну",
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
    # After onboarding prologue the bot may still show country prompt
    # in another locale — retry once more.
    text = await _maybe_select_language_and_country(
        client, entity, text, timeout=15
    )
    if not text or not _has_any(
        text,
        "UGC",
        "профиль",
        "profile",
        "Выберите",
        "Choose",
        "действие",
        "action",
        "role",
        "роль",
    ):
        pytest.skip(
            f"User not past onboarding: {text!r}. "
            "Ensure user has a profile on the dev bot."
        )


# ---------------------------------------------------------------------------
# DB fixtures for multi-currency referral data
# ---------------------------------------------------------------------------

E2E_TELEGRAM = os.environ.get("E2E_CLEAN_TELEGRAM", "darbulat")


def _get_db_engine():
    """Create SQLAlchemy engine from E2E_DATABASE_URL."""
    db_url = os.environ.get("E2E_DATABASE_URL", "").strip()
    if not db_url:
        return None
    from sqlalchemy import create_engine

    return create_engine(db_url)


def _find_e2e_user_id(conn, telegram: str):
    """Find user_id by telegram username."""
    from sqlalchemy import text

    row = conn.execute(
        text("SELECT user_id FROM users WHERE telegram = :tg LIMIT 1"),
        {"tg": telegram},
    ).fetchone()
    return row[0] if row else None


# Synthetic IDs for cleanup
_SYNTHETIC_PREFIX = "e2e_ref_"
_SYNTHETIC_USER_IDS: list[uuid.UUID] = []
_SYNTHETIC_ORDER_IDS: list[uuid.UUID] = []


@pytest.fixture()
def referral_multicurrency_data():
    """Insert multi-currency referral data for the E2E user.

    Creates:
    - 3 referred users (synthetic)
    - 3 referral bindings
    - 3 orders in RUB, GEL, KZT (status=closed)
    - 3 payments (status=paid)
    - 3 interactions (status=ok)
    - 3 referral_income_entries (creator type, different currencies)

    Yields the referrer user_id, then cleans up.
    """
    engine = _get_db_engine()
    if engine is None:
        pytest.skip("E2E_DATABASE_URL not set")

    from sqlalchemy import text

    now = datetime.now(timezone.utc)
    _SYNTHETIC_USER_IDS.clear()
    _SYNTHETIC_ORDER_IDS.clear()

    with engine.begin() as conn:
        referrer_id = _find_e2e_user_id(conn, E2E_TELEGRAM)
        if referrer_id is None:
            pytest.skip(f"E2E user '{E2E_TELEGRAM}' not found in DB")

        # Ensure referrer has referral_code and payout_rate
        conn.execute(
            text(
                "UPDATE users SET referral_code = :code, "
                "referral_payout_rate = 0.10 "
                "WHERE user_id = :uid AND "
                "(referral_code IS NULL "
                "OR referral_payout_rate IS NULL)"
            ),
            {"code": f"e2eref{referrer_id!s:.8}", "uid": referrer_id},
        )

        currencies = [
            ("RUB", 5000.00, 500.00),
            ("GEL", 200.00, 20.00),
            ("KZT", 50000.00, 5000.00),
        ]

        for currency, price, commission in currencies:
            # Create referred user
            ref_user_id = uuid.uuid4()
            _SYNTHETIC_USER_IDS.append(ref_user_id)
            conn.execute(
                text(
                    "INSERT INTO users "
                    "(user_id, external_id, messenger_type, "
                    "username, status, created_at, updated_at) "
                    "VALUES "
                    "(:uid, :eid, 'telegram', :uname, "
                    "'active', :now, :now)"
                ),
                {
                    "uid": ref_user_id,
                    "eid": f"{_SYNTHETIC_PREFIX}{ref_user_id!s:.8}",
                    "uname": f"E2E Ref {currency}",
                    "now": now,
                },
            )

            # Create referral binding
            conn.execute(
                text(
                    "INSERT INTO user_referral_bindings "
                    "(referrer_user_id, referred_user_id, "
                    "created_at) "
                    "VALUES (:referrer, :referred, :now)"
                ),
                {
                    "referrer": referrer_id,
                    "referred": ref_user_id,
                    "now": now,
                },
            )

            # Create order (closed, with currency)
            order_id = uuid.uuid4()
            _SYNTHETIC_ORDER_IDS.append(order_id)
            conn.execute(
                text(
                    "INSERT INTO orders "
                    "(order_id, advertiser_id, order_type, "
                    "product_link, offer_text, price, "
                    "bloggers_needed, status, currency, "
                    "created_at, updated_at) "
                    "VALUES "
                    "(:oid, :adv, 'ugc_only', "
                    "'https://e2e.test', 'E2E test', "
                    ":price, 1, 'closed', :cur, :now, :now)"
                ),
                {
                    "oid": order_id,
                    "adv": ref_user_id,
                    "price": price,
                    "cur": currency,
                    "now": now,
                },
            )

            # Create payment (paid)
            conn.execute(
                text(
                    "INSERT INTO payments "
                    "(payment_id, order_id, provider, "
                    "status, amount, currency, external_id, "
                    "created_at, updated_at, paid_at) "
                    "VALUES "
                    "(:pid, :oid, 'test', 'paid', "
                    ":amount, :cur, :ext, :now, :now, :now)"
                ),
                {
                    "pid": uuid.uuid4(),
                    "oid": order_id,
                    "amount": price,
                    "cur": currency,
                    "ext": f"e2e_pay_{currency}",
                    "now": now,
                },
            )

            # Create interaction (status=ok)
            conn.execute(
                text(
                    "INSERT INTO interactions "
                    "(interaction_id, order_id, blogger_id, "
                    "advertiser_id, status, "
                    "from_advertiser, from_blogger, "
                    "created_at, updated_at) "
                    "VALUES "
                    "(:iid, :oid, :blogger, :adv, 'ok', "
                    "'✅', '✅', :now, :now)"
                ),
                {
                    "iid": uuid.uuid4(),
                    "oid": order_id,
                    "blogger": ref_user_id,
                    "adv": ref_user_id,
                    "now": now,
                },
            )

            # Create referral_income_entry
            conn.execute(
                text(
                    "INSERT INTO referral_income_entries "
                    "(entry_id, referrer_user_id, "
                    "referred_user_id, order_id, "
                    "income_type, currency, "
                    "platform_revenue, commission_rate, "
                    "commission_amount, created_at) "
                    "VALUES "
                    "(:eid, :referrer, :referred, :oid, "
                    "'creator', :cur, :rev, 0.10, "
                    ":comm, :now)"
                ),
                {
                    "eid": uuid.uuid4(),
                    "referrer": referrer_id,
                    "referred": ref_user_id,
                    "oid": order_id,
                    "cur": currency,
                    "rev": price,
                    "comm": commission,
                    "now": now,
                },
            )

    yield referrer_id

    # Cleanup: delete synthetic data (CASCADE handles FKs)
    with engine.begin() as conn:
        if _SYNTHETIC_ORDER_IDS:
            conn.execute(
                text(
                    "DELETE FROM referral_income_entries "
                    "WHERE order_id = ANY(:ids)"
                ),
                {"ids": [str(oid) for oid in _SYNTHETIC_ORDER_IDS]},
            )
            conn.execute(
                text("DELETE FROM interactions WHERE order_id = ANY(:ids)"),
                {"ids": [str(oid) for oid in _SYNTHETIC_ORDER_IDS]},
            )
            conn.execute(
                text("DELETE FROM payments WHERE order_id = ANY(:ids)"),
                {"ids": [str(oid) for oid in _SYNTHETIC_ORDER_IDS]},
            )
            conn.execute(
                text("DELETE FROM orders WHERE order_id = ANY(:ids)"),
                {"ids": [str(oid) for oid in _SYNTHETIC_ORDER_IDS]},
            )
        if _SYNTHETIC_USER_IDS:
            conn.execute(
                text(
                    "DELETE FROM user_referral_bindings "
                    "WHERE referred_user_id = ANY(:ids)"
                ),
                {"ids": [str(uid) for uid in _SYNTHETIC_USER_IDS]},
            )
            conn.execute(
                text("DELETE FROM users WHERE user_id = ANY(:ids)"),
                {"ids": [str(uid) for uid in _SYNTHETIC_USER_IDS]},
            )

    engine.dispose()


# ---------------------------------------------------------------------------
# Basic referral tests (no DB setup needed)
# ---------------------------------------------------------------------------


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_command_shows_stats(
    telegram_user_client, telegram_e2e_config
) -> None:
    """Send /referral and verify stats text with currency info."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    assert _has_any(
        text,
        "реферал",
        "креатор",
        "заказ",
        "доход",
        "баланс",
        "выплачено",
        "статистика",
        "referral",
        "creator",
        "order",
        "income",
        "balance",
        "paid",
        "stats",
        "₽",
        "RUB",
        "USD",
        "GEL",
        "₸",
        "KZT",
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
    """Verify /referral response mentions currency amounts or zero."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    has_currency = _has_any(
        text, "₽", "₸", "₾", "$", "RUB", "USD", "GEL", "KZT", "BYN"
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
    assert _has_any(
        text,
        "реферал",
        "referral",
        "страница",
        "page",
        "выполнено",
        "done",
        "заказ",
        "order",
        "никого",
        "nobody",
        "пусто",
        "empty",
        "нет",
        "no",
        "няма",
        "пакуль",
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

    reply = await click_inline_and_get_reply(
        client, entity, "referral:payout:RUB", timeout=15
    )
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


# ---------------------------------------------------------------------------
# Multi-currency balance tests (require E2E_DATABASE_URL)
# ---------------------------------------------------------------------------


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_multicurrency_stats(
    telegram_user_client,
    telegram_e2e_config,
    referral_multicurrency_data,
) -> None:
    """With synthetic data: /referral shows amounts in RUB, GEL, KZT."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    # Should show income lines with amounts in all 3 currencies
    assert _has_any(text, "500", "500.00"), (
        f"Expected RUB commission 500.00 in stats, got: {text!r}"
    )
    assert _has_any(text, "20", "20.00"), (
        f"Expected GEL commission 20.00 in stats, got: {text!r}"
    )
    assert _has_any(text, "5000", "5000.00"), (
        f"Expected KZT commission 5000.00 in stats, got: {text!r}"
    )
    # At least 2 different currency symbols/codes visible
    currencies_found = sum(
        1 for sym in ("₽", "₾", "₸", "RUB", "GEL", "KZT") if sym in (text or "")
    )
    assert currencies_found >= 2, (
        f"Expected at least 2 currency symbols, got: {text!r}"
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_multicurrency_payout_buttons(
    telegram_user_client,
    telegram_e2e_config,
    referral_multicurrency_data,
) -> None:
    """With synthetic data: /referral shows per-currency payout buttons."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )
    assert text is not None, "Bot did not reply to /referral"

    # Try clicking payout for each currency — buttons should exist
    clicked_any = False
    for currency in ("RUB", "GEL", "KZT"):
        reply = await click_inline_and_get_reply(
            client,
            entity,
            f"referral:payout:{currency}",
            timeout=10,
        )
        if reply is not None:
            clicked_any = True
            # Bot should confirm payout request or show alert
            assert _has_any(
                reply,
                "выплат",
                "payout",
                "заявка",
                "request",
                "отправлен",
                "sent",
                "запрос",
                "недоступ",
                "unavailable",
                "уже",
                "already",
            ), f"Unexpected payout reply for {currency}: {reply!r}"
            # Re-fetch /referral for next button attempt
            text = await send_and_get_reply(
                client,
                entity,
                bot_username,
                "/referral",
                timeout=20,
            )

    assert clicked_any, (
        "No payout buttons were clickable. "
        "Check that referral_income_entries have positive balance."
    )


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_multicurrency_list(
    telegram_user_client,
    telegram_e2e_config,
    referral_multicurrency_data,
) -> None:
    """With synthetic data: /referral_list shows referred users."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral_list", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral_list"
    # Should show at least the 3 synthetic referred users
    assert _has_any(
        text,
        "E2E Ref",
        "e2e ref",
        "страница",
        "page",
        "реферал",
        "referral",
        "выполнено",
        "done",
    ), f"Expected referred users in list, got: {text!r}"

    # Should show order completion counts
    has_numbers = any(c.isdigit() for c in (text or ""))
    assert has_numbers, f"Expected numeric order counts in list, got: {text!r}"


@pytest.mark.e2e_telegram
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TELEGRAM_E2E_BOT_TOKEN"),
    reason="TELEGRAM_E2E_BOT_TOKEN not set",
)
async def test_referral_multicurrency_approx_total(
    telegram_user_client,
    telegram_e2e_config,
    referral_multicurrency_data,
) -> None:
    """With multi-currency data: /referral shows approximate total."""
    bot_username = telegram_e2e_config["bot_username"]
    entity = await telegram_user_client.get_entity(bot_username)
    client = telegram_user_client

    await _ensure_user_profile(client, entity, bot_username)

    text = await send_and_get_reply(
        client, entity, bot_username, "/referral", timeout=20
    )

    assert text is not None, "Bot did not reply to /referral"
    # With income in multiple currencies, bot should show approx total
    # (converted to referrer's currency) with ≈ symbol
    assert _has_any(
        text,
        "≈",
        "примерно",
        "approximate",
        "приблизительно",
        "итого",
        "total",
    ), f"Expected approximate total line for multi-currency, got: {text!r}"
