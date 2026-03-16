"""Tests for configuration loading."""

import pytest

from ugc_bot.config import AppConfig, load_config


def test_is_flat_dict_returns_false_for_non_dict() -> None:
    """_is_flat_dict returns False for non-dict (e.g. list)."""
    from ugc_bot.config import _is_flat_dict

    assert _is_flat_dict([]) is False
    assert _is_flat_dict(None) is False


def test_app_config_accepts_nested_dict() -> None:
    """AppConfig.model_validate accepts nested dict (not flat env-style)."""
    nested = {
        "bot": {"BOT_TOKEN": "token"},
        "log": {"LOG_LEVEL": "INFO", "LOG_FORMAT": "text"},
        "db": {"DATABASE_URL": "postgresql://localhost/db"},
        "admin": {
            "ADMIN_USERNAME": "a",
            "ADMIN_PASSWORD": "p",
            "ADMIN_SECRET": "s",
        },
        "kafka": {"KAFKA_ENABLED": "false"},
        "feedback": {"FEEDBACK_ENABLED": "false"},
        "role_reminder": {"ROLE_REMINDER_ENABLED": "false"},
        "redis": {
            "REDIS_URL": "redis://localhost",
            "USE_REDIS_STORAGE": "false",
        },
        "instagram": {
            "INSTAGRAM_WEBHOOK_VERIFY_TOKEN": "v",
            "INSTAGRAM_APP_SECRET": "s",
        },
        "docs": {
            "DOCS_OFFER_URL": "",
            "DOCS_PRIVACY_URL": "",
            "DOCS_CONSENT_URL": "",
        },
        "webhook": {
            "WEBHOOK_BASE_URL": "",
            "WEBHOOK_SECRET": "",
        },
        "outbox": {
            "OUTBOX_RETENTION_DAYS": "7",
            "OUTBOX_CLEANUP_BATCH_SIZE": "1000",
            "OUTBOX_CLEANUP_INTERVAL_ITERATIONS": "720",
        },
        "order": {
            "ALLOWED_BLOGGER_COUNTS": "1,3,5,10",
            "MAX_ORDER_PRICE": "10000",
        },
        "market": {
            "PAYMENT_CURRENCY": "RUB",
            "CURRENCY_SYMBOL": "₽",
            "BOT_DEFAULT_LOCALE": "ru",
        },
        "referral": {
            "REFERRAL_SUPPORT_CHAT_ID": "",
            "REFERRAL_BOT_USERNAME": "",
        },
    }
    config = AppConfig.model_validate(nested)
    assert config.bot.bot_token == "token"
    assert config.db.database_url == "postgresql://localhost/db"
    assert config.outbox.outbox_retention_days == 7
    assert config.order.get_allowed_blogger_counts_set() == frozenset(
        {1, 3, 5, 10}
    )
    assert config.order.max_order_price == 10000.0


def test_load_config_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load config from environment variables."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    config = load_config()

    assert config.bot.bot_token == "token"
    assert config.log.log_level == "DEBUG"
    assert config.db.database_url == "postgresql://test"


def test_log_config_normalizes_log_level() -> None:
    """LogConfig normalizes log_level (strip and upper)."""
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "t",
            "DATABASE_URL": "db",
            "LOG_LEVEL": "  warn  ",
            "LOG_FORMAT": "text",
        }
    )
    assert config.log.log_level == "WARN"


def test_bot_config_empty_token_raises() -> None:
    """BotConfig raises ValueError when BOT_TOKEN is empty or whitespace."""
    from ugc_bot.config import BotConfig

    with pytest.raises(ValueError, match="BOT_TOKEN is required"):
        BotConfig.model_validate({"BOT_TOKEN": "   "})


def test_admin_config_rejects_weak_password() -> None:
    """AdminConfig rejects weak admin password values."""
    base = {
        "BOT_TOKEN": "t",
        "DATABASE_URL": "db",
        "ADMIN_USERNAME": "a",
        "ADMIN_SECRET": "strong_secret_xyz",
    }
    for weak in ("admin", "change_me", "changeme", "password", "secret"):
        with pytest.raises(ValueError, match="ADMIN_PASSWORD"):
            AppConfig.model_validate({**base, "ADMIN_PASSWORD": weak})


def test_admin_config_rejects_weak_secret() -> None:
    """AdminConfig rejects weak admin secret values."""
    base = {
        "BOT_TOKEN": "t",
        "DATABASE_URL": "db",
        "ADMIN_USERNAME": "a",
        "ADMIN_PASSWORD": "strong_password_xyz",
    }
    for weak in ("admin", "change_me", "changeme", "password", "secret"):
        with pytest.raises(ValueError, match="ADMIN_SECRET"):
            AppConfig.model_validate({**base, "ADMIN_SECRET": weak})


def test_docs_config_get_urls_for_country_ru() -> None:
    """get_urls_for_country returns RU URLs for 'ru' and None."""
    from ugc_bot.config import DocsConfig

    docs = DocsConfig.model_validate(
        {
            "DOCS_OFFER_URL": "https://ru/offer",
            "DOCS_PRIVACY_URL": "https://ru/privacy",
            "DOCS_CONSENT_URL": "https://ru/consent",
            "DOCS_OFFER_URL_INTL": "https://intl/offer",
            "DOCS_PRIVACY_URL_INTL": "https://intl/privacy",
            "DOCS_CONSENT_URL_INTL": "https://intl/consent",
        }
    )
    assert docs.get_urls_for_country("ru") == (
        "https://ru/offer",
        "https://ru/privacy",
        "https://ru/consent",
    )
    assert docs.get_urls_for_country(None) == (
        "https://ru/offer",
        "https://ru/privacy",
        "https://ru/consent",
    )


def test_docs_config_get_urls_for_country_intl() -> None:
    """get_urls_for_country returns INTL URLs for non-RU country."""
    from ugc_bot.config import DocsConfig

    docs = DocsConfig.model_validate(
        {
            "DOCS_OFFER_URL": "https://ru/offer",
            "DOCS_PRIVACY_URL": "https://ru/privacy",
            "DOCS_CONSENT_URL": "https://ru/consent",
            "DOCS_OFFER_URL_INTL": "https://intl/offer",
            "DOCS_PRIVACY_URL_INTL": "https://intl/privacy",
            "DOCS_CONSENT_URL_INTL": "https://intl/consent",
        }
    )
    assert docs.get_urls_for_country("kz") == (
        "https://intl/offer",
        "https://intl/privacy",
        "https://intl/consent",
    )


def test_docs_config_get_urls_for_country_intl_fallback() -> None:
    """get_urls_for_country falls back to RU when INTL is empty."""
    from ugc_bot.config import DocsConfig

    docs = DocsConfig.model_validate(
        {
            "DOCS_OFFER_URL": "https://ru/offer",
            "DOCS_PRIVACY_URL": "https://ru/privacy",
            "DOCS_CONSENT_URL": "https://ru/consent",
        }
    )
    assert docs.get_urls_for_country("kz") == (
        "https://ru/offer",
        "https://ru/privacy",
        "https://ru/consent",
    )


def test_order_config_rejects_non_integer_allowed_blogger_counts() -> None:
    """OrderConfig.parse_allowed_counts raises when value is not an integer."""
    from ugc_bot.config import OrderConfig

    with pytest.raises(ValueError, match="ALLOWED_BLOGGER_COUNTS must be"):
        OrderConfig.model_validate({"ALLOWED_BLOGGER_COUNTS": "1,abc"})


def test_order_config_rejects_non_positive_allowed_blogger_counts() -> None:
    """OrderConfig.parse_allowed_counts raises when value is not positive."""
    from ugc_bot.config import OrderConfig

    with pytest.raises(ValueError, match="must be positive"):
        OrderConfig.model_validate({"ALLOWED_BLOGGER_COUNTS": "1,0"})
