"""Tests for Max referral handler — referral deep-link generation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.application.services.referral_commission import (
    MultiCurrencyReferralStats,
)
from ugc_bot.bot.max.handlers.referral import router
from ugc_bot.domain.enums import MessengerType, UserStatus


def _mc_stats(creators_count: int = 0) -> MultiCurrencyReferralStats:
    return MultiCurrencyReferralStats(
        creators_count=creators_count,
        income_by_currency={},
        orders_by_currency={},
        paid_by_currency={},
        pending_by_currency={},
        available_by_currency={},
        has_request_today_by_currency={},
    )


def _make_user(
    *,
    referral_code: str = "",
    status: UserStatus = UserStatus.ACTIVE,
):
    u = MagicMock()
    u.user_id = "u1"
    u.referral_code = referral_code
    u.status = status
    u.country = "RU"
    return u


def _incoming(text: str = "/referral") -> IncomingMessage:
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(
            external_id="42",
            messenger_type=MessengerType.MAX,
            username="alice",
        ),
        text=text,
        message_id="msg_1",
    )


def _deps(*, config, user, mc_stats=None):
    from tests.helpers.fakes import FakeMessengerClient

    client = FakeMessengerClient()
    user_role_service = AsyncMock()
    user_role_service.get_user = AsyncMock(return_value=user)

    income_service = AsyncMock()
    income_service.get_multicurrency_stats = AsyncMock(
        return_value=mc_stats or _mc_stats(),
    )

    bot_texts_service = AsyncMock()
    bot_texts_service.get_many = AsyncMock(
        return_value={
            "msg_referral_link_intro": "Ваша реферальная ссылка:",
        },
    )

    return {
        "messenger_client": client,
        "user_role_service": user_role_service,
        "referral_income_service": income_service,
        "bot_texts_service": bot_texts_service,
        "config": config,
        "locale": "ru",
        "country_repo": None,
        "exchange_rate_service": None,
    }


@pytest.mark.asyncio
async def test_referral_command_includes_max_link_when_configured():
    """Max referral link is included when max_referral_bot_username is set."""
    config = MagicMock()
    config.referral.max_referral_bot_username = "id165919810643_bot"
    config.referral.referral_stats_limit = 10_000

    user = _make_user(referral_code="abc12xyz")
    deps = _deps(config=config, user=user)

    await router.route_message(_incoming(), deps)

    client = deps["messenger_client"]
    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "https://max.ru/id165919810643_bot?start=ref_abc12xyz" in text
    assert "Ваша реферальная ссылка:" in text


@pytest.mark.asyncio
async def test_referral_command_skips_link_when_max_username_not_set():
    """No referral link when max_referral_bot_username is empty."""
    config = MagicMock()
    config.referral.max_referral_bot_username = ""
    config.referral.referral_stats_limit = 10_000

    user = _make_user(referral_code="abc12xyz")
    deps = _deps(config=config, user=user)

    await router.route_message(_incoming(), deps)

    client = deps["messenger_client"]
    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "max.ru" not in text


@pytest.mark.asyncio
async def test_referral_command_skips_link_when_no_referral_code():
    """No referral link when user has no referral_code."""
    config = MagicMock()
    config.referral.max_referral_bot_username = "id165919810643_bot"
    config.referral.referral_stats_limit = 10_000

    user = _make_user(referral_code="")
    deps = _deps(config=config, user=user)

    await router.route_message(_incoming(), deps)

    client = deps["messenger_client"]
    assert len(client.sent_text) == 1
    text = client.sent_text[0]["text"]
    assert "max.ru" not in text
