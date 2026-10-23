"""Regression coverage for financial capture configuration."""

import pytest

from ugc_bot.config import AppConfig, BotConfig


def test_flat_payment_account_id_matches_nested_bot_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_PAYMENT_ACCOUNT_ID", raising=False)
    values = {
        "BOT_TOKEN": "test-token",
        "TELEGRAM_PAYMENT_ACCOUNT_ID": "test-merchant-scope",
    }
    nested_bot = BotConfig.model_validate(values)
    flat = AppConfig.model_validate(values)

    assert nested_bot.telegram_payment_account_id == "test-merchant-scope"
    assert (
        flat.bot.telegram_payment_account_id
        == nested_bot.telegram_payment_account_id
    )
