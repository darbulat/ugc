"""Application configuration loading.

Config is split into domain sections (bot, db, kafka, etc.) to simplify
maintenance and testing. AppConfig composes them.
"""

import base64
import binascii
import json
import re
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from ugc_bot.domain.financial_tariff import (
    MAX_POSITION_TOTAL_MINOR,
    require_tariff,
)
from ugc_bot.domain.refund_rules import RefundRules

_ENV = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
    hide_input_in_errors=True,
)

_FLAT_KEYS = {
    "bot": [
        "BOT_TOKEN",
        "TELEGRAM_PROVIDER_TOKEN",
        "TELEGRAM_BOT_USERNAME",
        "TELEGRAM_PAYMENT_ACCOUNT_ID",
    ],
    "log": ["LOG_LEVEL", "LOG_FORMAT"],
    "db": [
        "DATABASE_URL",
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
    ],
    "admin": [
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD",
        "ADMIN_SECRET",
        "ADMIN_SITE_NAME",
        "ADMIN_BASE_URL",
        "ADMIN_DASHBOARD_TIMEZONE",
        "ADMIN_DELAY_ACTIVE_DAYS",
        "ADMIN_NO_RESPONSES_HOURS",
        "ADMIN_LOW_PICKED_HOURS",
        "ADMIN_ARCHIVE_DAYS",
    ],
    "kafka": [
        "KAFKA_ENABLED",
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_TOPIC",
        "KAFKA_GROUP_ID",
        "KAFKA_DLQ_TOPIC",
        "KAFKA_SEND_RETRIES",
        "KAFKA_SEND_RETRY_DELAY_SECONDS",
    ],
    "feedback": [
        "FEEDBACK_DELAY_MINUTES",
        "FEEDBACK_POLL_INTERVAL_SECONDS",
        "FEEDBACK_ENABLED",
        "CAMPAIGN_DIGEST_ENABLED",
        "FEEDBACK_REMINDER_HOUR",
        "FEEDBACK_REMINDER_MINUTE",
        "FEEDBACK_REMINDER_TIMEZONE",
    ],
    "role_reminder": [
        "ROLE_REMINDER_ENABLED",
        "ROLE_REMINDER_HOUR",
        "ROLE_REMINDER_MINUTE",
        "ROLE_REMINDER_TIMEZONE",
    ],
    "redis": ["REDIS_URL", "USE_REDIS_STORAGE"],
    "instagram": [
        "INSTAGRAM_WEBHOOK_VERIFY_TOKEN",
        "INSTAGRAM_APP_SECRET",
        "ADMIN_INSTAGRAM_USERNAME",
        "INSTAGRAM_ACCESS_TOKEN",
        "INSTAGRAM_API_BASE_URL",
        "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "INSTAGRAM_BUSINESS_ACCESS_TOKEN",
        "INSTAGRAM_WEB_PROFILE_ENABLED",
        "INSTAGRAM_WEB_PROFILE_APP_ID",
        "INSTAGRAM_STATS_COLLECTOR_ENABLED",
        "INSTAGRAM_STATS_COLLECTOR_INTERVAL_SECONDS",
        "INSTAGRAM_STATS_COLLECTOR_BATCH_SIZE",
        "INSTAGRAM_STATS_COLLECTOR_DELAY_SECONDS",
        "SCRAPECREATORS_API_KEY",
        "SCRAPECREATORS_BASE_URL",
    ],
    "geocoder": [
        "GEOCODER_PROVIDER",
        "NOMINATIM_ENABLED",
        "NOMINATIM_BASE_URL",
        "NOMINATIM_USER_AGENT",
        "NOMINATIM_TIMEOUT",
        "NOMINATIM_DELAY_SECONDS",
        "DADATA_ENABLED",
        "DADATA_BASE_URL",
        "DADATA_TIMEOUT",
        "DADATA_API_KEY",
        "DADATA_SECRET",
        "GEOCODER_CACHE_ENABLED",
        "GEOCODER_CACHE_TTL_SECONDS",
        "GEOCODER_CACHE_BACKEND",
        "GEOCODER_CACHE_MEMORY_MAX_ENTRIES",
    ],
    "docs": [
        "DOCS_OFFER_URL",
        "DOCS_PRIVACY_URL",
        "DOCS_CONSENT_URL",
        "DOCS_OFFER_URL_INTL",
        "DOCS_PRIVACY_URL_INTL",
        "DOCS_CONSENT_URL_INTL",
    ],
    "webhook": ["WEBHOOK_BASE_URL", "WEBHOOK_SECRET"],
    "outbox": [
        "OUTBOX_RETENTION_DAYS",
        "OUTBOX_CLEANUP_BATCH_SIZE",
        "OUTBOX_CLEANUP_INTERVAL_ITERATIONS",
    ],
    "order": [
        "ALLOWED_BLOGGER_COUNTS",
        "CUSTOMER_WORKFLOWS_ENABLED",
        "MAX_ORDER_PRICE",
        "ORDER_RADIUS_KM",
        "UNPAID_REMINDERS_ENABLED",
        "UNPAID_REMINDERS_START_AT",
        "UNPAID_REMINDERS_EXCLUDED_USERS",
    ],
    "campaign": [
        "CAMPAIGN_DELIVERY_ENABLED",
        "CAMPAIGN_REQUIRE_PAID_SUBSCRIPTION",
        "CAMPAIGN_DELIVERY_INTERVAL_SECONDS",
    ],
    "financial": [
        "FINANCIAL_SELECTION_PRICE_MINOR",
        "FINANCIAL_ACCOMPANIMENT_PRICE_MINOR",
        "FINANCIAL_CORE_ENABLED",
        "FINANCIAL_NEW_ORDERS_ENABLED",
        "FINANCIAL_PAYOUTS_ENABLED",
        "FINANCIAL_REQUISITES_KEY",
        "FINANCIAL_REQUISITES_KEY_ID",
        "FINANCIAL_MANUAL_BANK_ACCOUNT_ID",
        "FINANCIAL_MANUAL_BANK_SOURCE_ID",
        "FINANCIAL_SUPERADMIN_USER_IDS",
        "FINANCIAL_SELECTION_REFUND_WINDOW_SECONDS",
        "FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR",
        "FINANCIAL_SELECTION_CLOSURE_MODE",
        "FINANCIAL_ACCOMPANIMENT_REFUND_RATES_BPS",
        "FINANCIAL_ACCOMPANIMENT_MANAGER_REFUND_MODE",
    ],
    "messenger_linking": [
        "MESSENGER_LINKING_ENABLED",
        "MESSENGER_LINKING_TOKEN_SECRET",
        "MESSENGER_LINKING_KEY_ID",
    ],
    "referral": [
        "REFERRAL_SUPPORT_CHAT_ID",
        "REFERRAL_BOT_USERNAME",
        "MAX_REFERRAL_BOT_USERNAME",
    ],
    "max_bot": [
        "MAX_BOT_TOKEN",
        "MAX_BOT_WEBHOOK_URL",
        "MAX_BOT_WEBHOOK_SECRET",
    ],
    "market": [
        "PAYMENT_CURRENCY",
        "CURRENCY_SYMBOL",
        "BOT_DEFAULT_LOCALE",
        "BOT_START_TEXT",
        "BOT_SUPPORT_RESPONSE_TEXT",
        "BOT_SUPPORT_CONTACT",
        "BOT_RECEIPT_SERVICE_DESCRIPTION",
        "SUPPORT_CHAT_ID",
    ],
}


def _is_flat_dict(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    # Flat: has env-style keys and no nested section
    flat_markers = {"BOT_TOKEN", "DATABASE_URL", "KAFKA_ENABLED", "LOG_LEVEL"}
    return bool(flat_markers & set(obj.keys())) or obj == {}


def _flat_to_nested(flat: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        section: {k: flat[k] for k in keys if k in flat}
        for section, keys in _FLAT_KEYS.items()
    }


# --- Section configs (each reads from env via BaseSettings) ---


class BotConfig(BaseSettings):
    model_config = _ENV

    bot_token: str = Field(alias="BOT_TOKEN")
    telegram_provider_token: str = Field(
        default="", alias="TELEGRAM_PROVIDER_TOKEN"
    )
    telegram_provider_token_intl: str = Field(
        default="", alias="TELEGRAM_PROVIDER_TOKEN_INTL"
    )
    bot_username: str = Field(default="", alias="TELEGRAM_BOT_USERNAME")
    telegram_payment_account_id: str = Field(
        default="", alias="TELEGRAM_PAYMENT_ACCOUNT_ID"
    )

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("BOT_TOKEN is required to start the bot.")
        return v.strip()


class LogConfig(BaseSettings):
    model_config = _ENV

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="text", alias="LOG_FORMAT")

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, v: str) -> str:  # pragma: no cover
        return v.strip().upper()


class DbConfig(BaseSettings):
    model_config = _ENV

    database_url: str = Field(default="", alias="DATABASE_URL")
    # Keep per-service pools small when going through PgBouncer session pooling.
    pool_size: int = Field(default=1, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=0, alias="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")


_WEAK_ADMIN_VALUES = frozenset(
    {"admin", "change_me", "changeme", "password", "secret"}
)


class AdminConfig(BaseSettings):
    model_config = _ENV

    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    admin_secret: str = Field(default="", alias="ADMIN_SECRET")

    @field_validator("admin_password")
    @classmethod
    def validate_admin_password(cls, v: str) -> str:
        if v and v.strip().lower() in _WEAK_ADMIN_VALUES:
            raise ValueError(
                "ADMIN_PASSWORD must not use default/weak values. "
                "Set a strong password for production.",
            )
        return v

    @field_validator("admin_secret")
    @classmethod
    def validate_admin_secret(cls, v: str) -> str:
        if v and v.strip().lower() in _WEAK_ADMIN_VALUES:
            raise ValueError(
                "ADMIN_SECRET must not use default/weak values. "
                "Set a secure random secret for production.",
            )
        return v

    admin_site_name: str = Field(default="UGC Admin", alias="ADMIN_SITE_NAME")
    admin_base_url: str = Field(
        default="", alias="ADMIN_BASE_URL"
    )  # e.g. https://admin.example.com/admin
    admin_dashboard_timezone: str = Field(
        default="Europe/Moscow", alias="ADMIN_DASHBOARD_TIMEZONE"
    )
    admin_delay_active_days: int = Field(
        default=7, alias="ADMIN_DELAY_ACTIVE_DAYS"
    )
    admin_no_responses_hours: int = Field(
        default=24, alias="ADMIN_NO_RESPONSES_HOURS"
    )
    admin_low_picked_hours: int = Field(
        default=48, alias="ADMIN_LOW_PICKED_HOURS"
    )
    admin_archive_days: int = Field(default=7, alias="ADMIN_ARCHIVE_DAYS")


class KafkaConfig(BaseSettings):
    model_config = _ENV

    kafka_enabled: bool = Field(default=True, alias="KAFKA_ENABLED")
    kafka_bootstrap_servers: str = Field(
        default="kafka:9092", alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    kafka_topic: str = Field(default="order_activated", alias="KAFKA_TOPIC")
    kafka_group_id: str = Field(default="ugc-bot", alias="KAFKA_GROUP_ID")
    kafka_dlq_topic: str = Field(
        default="order_activated_dlq", alias="KAFKA_DLQ_TOPIC"
    )
    kafka_send_retries: int = Field(default=3, alias="KAFKA_SEND_RETRIES")
    kafka_send_retry_delay_seconds: float = Field(
        default=1.0, alias="KAFKA_SEND_RETRY_DELAY_SECONDS"
    )
    kafka_producer_retries: int = Field(
        default=3, alias="KAFKA_PRODUCER_RETRIES"
    )
    kafka_producer_retry_backoff_ms: int = Field(
        default=500, alias="KAFKA_PRODUCER_RETRY_BACKOFF_MS"
    )
    kafka_consumer_heartbeat_interval_ms: int = Field(
        default=3000, alias="KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS"
    )
    kafka_consumer_session_timeout_ms: int = Field(
        default=30000, alias="KAFKA_CONSUMER_SESSION_TIMEOUT_MS"
    )


class FeedbackConfig(BaseSettings):
    model_config = _ENV

    feedback_delay_minutes: int = Field(
        default=4320, alias="FEEDBACK_DELAY_MINUTES"
    )
    feedback_poll_interval_seconds: int = Field(
        default=300, alias="FEEDBACK_POLL_INTERVAL_SECONDS"
    )
    feedback_enabled: bool = Field(default=True, alias="FEEDBACK_ENABLED")
    campaign_digest_enabled: bool = Field(
        default=False, alias="CAMPAIGN_DIGEST_ENABLED"
    )
    feedback_reminder_hour: int = Field(
        default=10, alias="FEEDBACK_REMINDER_HOUR"
    )
    feedback_reminder_minute: int = Field(
        default=0, alias="FEEDBACK_REMINDER_MINUTE"
    )
    feedback_reminder_timezone: str = Field(
        default="Europe/Moscow", alias="FEEDBACK_REMINDER_TIMEZONE"
    )


class RoleReminderConfig(BaseSettings):
    model_config = _ENV

    role_reminder_enabled: bool = Field(
        default=True, alias="ROLE_REMINDER_ENABLED"
    )
    role_reminder_hour: int = Field(default=10, alias="ROLE_REMINDER_HOUR")
    role_reminder_minute: int = Field(default=0, alias="ROLE_REMINDER_MINUTE")
    role_reminder_timezone: str = Field(
        default="Europe/Moscow", alias="ROLE_REMINDER_TIMEZONE"
    )


class RedisConfig(BaseSettings):
    model_config = _ENV

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    use_redis_storage: bool = Field(default=True, alias="USE_REDIS_STORAGE")
    redis_max_connections: int = Field(
        default=20, alias="REDIS_MAX_CONNECTIONS"
    )
    redis_socket_timeout: float = Field(
        default=5.0, alias="REDIS_SOCKET_TIMEOUT"
    )
    redis_socket_connect_timeout: float = Field(
        default=5.0, alias="REDIS_SOCKET_CONNECT_TIMEOUT"
    )


class InstagramConfig(BaseSettings):
    model_config = _ENV

    instagram_webhook_verify_token: str = Field(
        default="", alias="INSTAGRAM_WEBHOOK_VERIFY_TOKEN"
    )
    instagram_app_secret: str = Field(default="", alias="INSTAGRAM_APP_SECRET")
    admin_instagram_username: str = Field(
        default="usemycontent", alias="ADMIN_INSTAGRAM_USERNAME"
    )
    instagram_access_token: str = Field(
        default="", alias="INSTAGRAM_ACCESS_TOKEN"
    )
    instagram_api_base_url: str = Field(
        default="https://graph.instagram.com", alias="INSTAGRAM_API_BASE_URL"
    )
    instagram_business_account_id: str = Field(
        default="", alias="INSTAGRAM_BUSINESS_ACCOUNT_ID"
    )
    instagram_business_access_token: str = Field(
        default="", alias="INSTAGRAM_BUSINESS_ACCESS_TOKEN"
    )
    instagram_stats_update_enabled: bool = Field(
        default=False, alias="INSTAGRAM_STATS_UPDATE_ENABLED"
    )
    instagram_stats_update_interval_seconds: int = Field(
        default=86400, alias="INSTAGRAM_STATS_UPDATE_INTERVAL_SECONDS"
    )
    instagram_stats_batch_size: int = Field(
        default=50, alias="INSTAGRAM_STATS_BATCH_SIZE"
    )
    instagram_stats_delay_seconds: float = Field(
        default=1.0, alias="INSTAGRAM_STATS_DELAY_SECONDS"
    )
    instagram_stats_collector_enabled: bool = Field(
        default=True, alias="INSTAGRAM_STATS_COLLECTOR_ENABLED"
    )
    instagram_stats_collector_interval_seconds: int = Field(
        default=86400, alias="INSTAGRAM_STATS_COLLECTOR_INTERVAL_SECONDS"
    )
    instagram_stats_collector_batch_size: int = Field(
        default=50, alias="INSTAGRAM_STATS_COLLECTOR_BATCH_SIZE"
    )
    instagram_stats_collector_delay_seconds: float = Field(
        default=3.0, alias="INSTAGRAM_STATS_COLLECTOR_DELAY_SECONDS"
    )
    instagram_stats_provider_fallback_delay_seconds: float = Field(
        default=2.0,
        alias="INSTAGRAM_STATS_PROVIDER_FALLBACK_DELAY_SECONDS",
    )
    scrapecreators_api_key: str = Field(
        default="", alias="SCRAPECREATORS_API_KEY"
    )
    scrapecreators_base_url: str = Field(
        default="https://api.scrapecreators.com",
        alias="SCRAPECREATORS_BASE_URL",
    )
    instagram_stats_aiograpi_username: str = Field(
        default="", alias="INSTAGRAM_STATS_AIOGRAPI_USERNAME"
    )
    instagram_stats_aiograpi_password: str = Field(
        default="", alias="INSTAGRAM_STATS_AIOGRAPI_PASSWORD"
    )
    instagram_stats_aiograpi_session_path: str = Field(
        default="", alias="INSTAGRAM_STATS_AIOGRAPI_SESSION_PATH"
    )

    @field_validator("scrapecreators_base_url")
    @classmethod
    def strip_scrapecreators_base_url_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v


class GeocoderConfig(BaseSettings):
    """Geocoding provider configuration (Nominatim, Dadata, etc.)."""

    model_config = _ENV

    provider: Literal["nominatim", "dadata"] = Field(
        default="nominatim", alias="GEOCODER_PROVIDER"
    )

    # Nominatim
    nominatim_enabled: bool = Field(default=True, alias="NOMINATIM_ENABLED")
    nominatim_base_url: str = Field(
        default="https://nominatim.openstreetmap.org",
        alias="NOMINATIM_BASE_URL",
    )
    nominatim_user_agent: str = Field(
        default="ugc-bot/1.0",
        alias="NOMINATIM_USER_AGENT",
    )
    nominatim_timeout_seconds: float = Field(
        default=5.0,
        alias="NOMINATIM_TIMEOUT",
    )
    nominatim_delay_seconds: float = Field(
        default=1.0,
        alias="NOMINATIM_DELAY_SECONDS",
    )

    # Dadata
    dadata_enabled: bool = Field(default=True, alias="DADATA_ENABLED")
    dadata_base_url: str = Field(
        default="https://suggestions.dadata.ru/suggestions/api/4_1/rs",
        alias="DADATA_BASE_URL",
    )
    dadata_timeout_seconds: float = Field(
        default=5.0,
        alias="DADATA_TIMEOUT",
    )
    dadata_api_key: str = Field(default="", alias="DADATA_API_KEY")
    dadata_secret: str = Field(default="", alias="DADATA_SECRET")

    # Cache (shared for any provider)
    cache_enabled: bool = Field(default=True, alias="GEOCODER_CACHE_ENABLED")
    cache_ttl_seconds: int = Field(
        default=604800,
        alias="GEOCODER_CACHE_TTL_SECONDS",
    )  # 7 days
    cache_backend: Literal["redis", "memory"] = Field(
        default="redis",
        alias="GEOCODER_CACHE_BACKEND",
    )
    cache_memory_max_entries: int = Field(
        default=10_000,
        alias="GEOCODER_CACHE_MEMORY_MAX_ENTRIES",
    )

    @field_validator("nominatim_base_url", "dadata_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v


class DocsConfig(BaseSettings):
    """URLs for legal documents (offer, privacy, consent)."""

    model_config = _ENV

    docs_offer_url: str = Field(default="", alias="DOCS_OFFER_URL")
    docs_privacy_url: str = Field(default="", alias="DOCS_PRIVACY_URL")
    docs_consent_url: str = Field(default="", alias="DOCS_CONSENT_URL")
    docs_offer_url_intl: str = Field(default="", alias="DOCS_OFFER_URL_INTL")
    docs_privacy_url_intl: str = Field(
        default="", alias="DOCS_PRIVACY_URL_INTL"
    )
    docs_consent_url_intl: str = Field(
        default="", alias="DOCS_CONSENT_URL_INTL"
    )

    def get_urls_for_country(
        self, country_code: str | None
    ) -> tuple[str, str, str]:
        """Return (offer, privacy, consent) URLs based on country code."""
        if country_code == "ru" or not country_code:
            return (
                self.docs_offer_url,
                self.docs_privacy_url,
                self.docs_consent_url,
            )
        return (
            self.docs_offer_url_intl or self.docs_offer_url,
            self.docs_privacy_url_intl or self.docs_privacy_url,
            self.docs_consent_url_intl or self.docs_consent_url,
        )


class WebhookConfig(BaseSettings):
    """Telegram webhook configuration for scalable bot deployment."""

    model_config = _ENV

    webhook_base_url: str = Field(
        default="", alias="WEBHOOK_BASE_URL"
    )  # e.g. https://bot.usemycontent.ru
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")

    @field_validator("webhook_base_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/") if v else v


class OutboxConfig(BaseSettings):
    """Outbox event cleanup configuration."""

    model_config = _ENV

    outbox_retention_days: int = Field(default=7, alias="OUTBOX_RETENTION_DAYS")
    outbox_cleanup_batch_size: int = Field(
        default=1000, alias="OUTBOX_CLEANUP_BATCH_SIZE"
    )
    outbox_cleanup_interval_iterations: int = Field(
        default=720, alias="OUTBOX_CLEANUP_INTERVAL_ITERATIONS"
    )


class OrderConfig(BaseSettings):
    """Order creation limits: allowed blogger counts and max price."""

    model_config = _ENV

    customer_workflows_enabled: bool = Field(
        default=False, alias="CUSTOMER_WORKFLOWS_ENABLED"
    )
    unpaid_reminders_enabled: bool = Field(
        default=False, alias="UNPAID_REMINDERS_ENABLED"
    )
    unpaid_reminders_start_at: AwareDatetime | None = Field(
        default=None, alias="UNPAID_REMINDERS_START_AT"
    )
    unpaid_reminders_excluded_users: frozenset[UUID] = Field(
        default_factory=frozenset, alias="UNPAID_REMINDERS_EXCLUDED_USERS"
    )

    allowed_blogger_counts: str = Field(
        default="1,3,5,10", alias="ALLOWED_BLOGGER_COUNTS"
    )
    max_order_price: float = Field(default=10_000.0, alias="MAX_ORDER_PRICE")
    order_radius_km: float = Field(default=50.0, alias="ORDER_RADIUS_KM")

    @field_validator("allowed_blogger_counts")
    @classmethod
    def parse_allowed_counts(cls, v: str) -> str:
        """Validate comma-separated positive integers; return as-is."""
        parts = [p.strip() for p in v.split(",") if p.strip()]
        for p in parts:
            try:
                val = int(p)
            except ValueError as e:
                raise ValueError(
                    f"ALLOWED_BLOGGER_COUNTS must be comma-separated "
                    f"integers: {p}"
                ) from e
            if val < 1:
                raise ValueError(f"Allowed blogger count must be positive: {p}")
        return v

    def get_allowed_blogger_counts_set(self) -> frozenset[int]:
        """Return frozenset of allowed blogger counts."""
        return frozenset(
            int(p.strip())
            for p in self.allowed_blogger_counts.split(",")
            if p.strip()
        )


class MarketConfig(BaseSettings):
    """Market-specific configuration: currency, locale, optional bot texts."""

    model_config = _ENV

    payment_currency: str = Field(default="RUB", alias="PAYMENT_CURRENCY")
    currency_symbol: str = Field(default="₽", alias="CURRENCY_SYMBOL")
    default_locale: str = Field(default="ru", alias="BOT_DEFAULT_LOCALE")
    start_text: str = Field(default="", alias="BOT_START_TEXT")
    support_response_text: str = Field(
        default="", alias="BOT_SUPPORT_RESPONSE_TEXT"
    )
    support_contact: str = Field(default="", alias="BOT_SUPPORT_CONTACT")
    receipt_service_description: str = Field(
        default="", alias="BOT_RECEIPT_SERVICE_DESCRIPTION"
    )
    support_chat_id: str = Field(default="", alias="SUPPORT_CHAT_ID")


class ReferralConfig(BaseSettings):
    """Referral system configuration."""

    model_config = _ENV

    referral_support_chat_id: str = Field(
        default="",
        alias="REFERRAL_SUPPORT_CHAT_ID",
    )
    referral_bot_username: str = Field(
        default="",
        alias="REFERRAL_BOT_USERNAME",
    )
    max_referral_bot_username: str = Field(
        default="",
        alias="MAX_REFERRAL_BOT_USERNAME",
    )
    referral_stats_limit: int = Field(
        default=10_000,
        alias="REFERRAL_STATS_LIMIT",
    )
    referral_reconciliation_enabled: bool = Field(
        default=False,
        alias="REFERRAL_RECONCILIATION_ENABLED",
    )
    referral_reconciliation_interval_seconds: int = Field(
        default=300,
        alias="REFERRAL_RECONCILIATION_INTERVAL_SECONDS",
    )


class MaxBotConfig(BaseSettings):
    """Max messenger bot configuration."""

    model_config = _ENV

    token: str = Field(default="", alias="MAX_BOT_TOKEN")
    webhook_url: str = Field(default="", alias="MAX_BOT_WEBHOOK_URL")
    webhook_secret: str = Field(default="", alias="MAX_BOT_WEBHOOK_SECRET")


# --- Composite ---


class FinancialConfig(BaseSettings):
    """Independent emergency gates; policy/order parameters have no defaults."""

    model_config = _ENV
    superadmin_user_ids_raw: str = Field(
        default="", alias="FINANCIAL_SUPERADMIN_USER_IDS", max_length=16384
    )

    def superadmin_user_ids(self) -> frozenset[UUID]:
        raw = self.superadmin_user_ids_raw.strip()
        if not raw:
            return frozenset()
        values = json.loads(raw) if raw.startswith("[") else raw.split(",")
        if type(values) is not list or any(
            type(v) is not str or not v.strip() for v in values
        ):
            raise ValueError("financial_superadmin_uuid_list_required")
        try:
            result = tuple(UUID(v.strip()) for v in values)
        except (ValueError, TypeError, AttributeError):
            raise ValueError(
                "financial_superadmin_uuid_list_required"
            ) from None
        if any(not v.int for v in result) or len(set(result)) != len(result):
            raise ValueError("financial_superadmin_uuid_list_required")
        return frozenset(result)

    selection_price_minor: int | None = Field(
        default=None,
        alias="FINANCIAL_SELECTION_PRICE_MINOR",
        ge=1,
        le=MAX_POSITION_TOTAL_MINOR,
    )
    accompaniment_price_minor: int | None = Field(
        default=None,
        alias="FINANCIAL_ACCOMPANIMENT_PRICE_MINOR",
        ge=60000,
        le=MAX_POSITION_TOTAL_MINOR,
    )

    @field_validator(
        "selection_price_minor", "accompaniment_price_minor", mode="before"
    )
    @classmethod
    def _strict_tariff_minor(cls, value: Any) -> int | None:
        if value is None or type(value) is int:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            return int(value)
        raise ValueError("tariff_integer_minor_required")

    core_enabled: bool = Field(default=False, alias="FINANCIAL_CORE_ENABLED")
    new_orders_enabled: bool = Field(
        default=False, alias="FINANCIAL_NEW_ORDERS_ENABLED"
    )
    payouts_enabled: bool = Field(
        default=False, alias="FINANCIAL_PAYOUTS_ENABLED"
    )
    requisites_key: SecretStr = Field(
        default=SecretStr(""), alias="FINANCIAL_REQUISITES_KEY"
    )
    requisites_key_id: str = Field(
        default="", alias="FINANCIAL_REQUISITES_KEY_ID"
    )
    manual_bank_account_id: str = Field(
        default="", alias="FINANCIAL_MANUAL_BANK_ACCOUNT_ID", max_length=256
    )
    manual_bank_source_id: str = Field(
        default="", alias="FINANCIAL_MANUAL_BANK_SOURCE_ID", max_length=256
    )
    selection_refund_window_seconds: int | None = Field(
        default=None,
        alias="FINANCIAL_SELECTION_REFUND_WINDOW_SECONDS",
        ge=1,
        le=31536000,
    )
    selection_refund_window_anchor: (
        Literal["item_delivered", "order_closed"] | None
    ) = Field(default=None, alias="FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR")
    selection_closure_mode: (
        Literal["all_positions_resolved", "manual"] | None
    ) = Field(default=None, alias="FINANCIAL_SELECTION_CLOSURE_MODE")
    # Keep raw env JSON for duplicate-key validation on older settings versions.
    accompaniment_refund_rates_bps: object | None = Field(
        default=None, alias="FINANCIAL_ACCOMPANIMENT_REFUND_RATES_BPS"
    )
    accompaniment_manager_refund_mode: (
        Literal["retain_earned", "proportional", "manual_review"] | None
    ) = Field(default=None, alias="FINANCIAL_ACCOMPANIMENT_MANAGER_REFUND_MODE")

    @field_validator("selection_refund_window_seconds", mode="before")
    @classmethod
    def _strict_refund_window(cls, value: Any) -> int | None:
        if value is None or type(value) is int:
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            return int(value)
        raise ValueError("refund_window_integer_required")

    @staticmethod
    def _unique_refund_rates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_refund_stage")
            result[key] = value
        return result

    @field_validator("accompaniment_refund_rates_bps", mode="before")
    @classmethod
    def _strict_refund_rates(cls, value: Any) -> dict[str, int] | None:
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = json.loads(
                    value, object_pairs_hook=cls._unique_refund_rates
                )
            except (ValueError, TypeError):
                raise ValueError("refund_rates_json_object_required") from None
        if not isinstance(value, dict) or any(
            type(key) is not str
            or type(rate) is not int
            or not 0 <= rate <= 10000
            for key, rate in value.items()
        ):
            raise ValueError("refund_rates_integer_basis_points_required")
        return value

    @model_validator(mode="after")
    def _complete_refund_configuration(self) -> Self:
        self.refund_rules()
        if (self.selection_price_minor is None) != (
            self.accompaniment_price_minor is None
        ):
            raise ValueError("tariff_configuration_incomplete")
        if (
            self.selection_price_minor is not None
            and self.accompaniment_price_minor is not None
        ):
            require_tariff(
                self.selection_price_minor, self.accompaniment_price_minor
            )
        self.superadmin_user_ids()
        return self

    def refund_rules(self) -> RefundRules | None:
        values = (
            self.selection_refund_window_seconds,
            self.selection_refund_window_anchor,
            self.selection_closure_mode,
            self.accompaniment_refund_rates_bps,
            self.accompaniment_manager_refund_mode,
        )
        if all(value is None for value in values):
            return None
        if any(value is None for value in values):
            raise ValueError("refund_rules_configuration_incomplete")
        assert self.selection_refund_window_seconds is not None
        assert self.selection_refund_window_anchor is not None
        assert self.selection_closure_mode is not None
        assert isinstance(self.accompaniment_refund_rates_bps, dict)
        assert self.accompaniment_manager_refund_mode is not None
        return RefundRules(
            selection_refund_window_seconds=self.selection_refund_window_seconds,
            selection_refund_window_anchor=self.selection_refund_window_anchor,
            selection_closure_mode=self.selection_closure_mode,
            accompaniment_refund_rates_bps=tuple(
                sorted(self.accompaniment_refund_rates_bps.items())
            ),
            accompaniment_manager_refund_mode=(
                self.accompaniment_manager_refund_mode
            ),
        )


class MessengerLinkingConfig(BaseSettings):
    """Dedicated identity-linking key; missing configuration grants no proof."""

    model_config = SettingsConfigDict(**_ENV, populate_by_name=True)

    enabled: bool = Field(default=False, alias="MESSENGER_LINKING_ENABLED")
    token_secret: SecretStr | None = Field(
        default=None, alias="MESSENGER_LINKING_TOKEN_SECRET"
    )
    key_id: str | None = Field(
        default=None,
        alias="MESSENGER_LINKING_KEY_ID",
        pattern=r"^[A-Za-z0-9_-]{1,64}$",
    )

    @field_validator("token_secret")
    @classmethod
    def _validate_token_secret(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        if value is None:
            return None
        encoded = value.get_secret_value()
        message = "Linking key must be canonical base64url for at least32 bytes"
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,4096}", encoded):
            raise ValueError(message)
        try:
            decoded = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError):
            raise ValueError(message) from None
        if (
            len(decoded) < 32
            or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
            != encoded
        ):
            raise ValueError(message)
        return value


class CampaignRuntimeConfig(BaseSettings):
    model_config = _ENV
    delivery_enabled: bool = Field(
        default=False, alias="CAMPAIGN_DELIVERY_ENABLED"
    )
    require_paid_subscription: bool = Field(
        default=False, alias="CAMPAIGN_REQUIRE_PAID_SUBSCRIPTION"
    )
    interval_seconds: int = Field(
        default=5, ge=1, le=3600, alias="CAMPAIGN_DELIVERY_INTERVAL_SECONDS"
    )


class AppConfig(BaseModel):
    """Application configuration."""

    model_config = {"extra": "forbid", "hide_input_in_errors": True}

    bot: BotConfig
    log: LogConfig
    db: DbConfig
    admin: AdminConfig
    kafka: KafkaConfig
    feedback: FeedbackConfig
    role_reminder: RoleReminderConfig
    redis: RedisConfig
    instagram: InstagramConfig
    geocoder: GeocoderConfig = Field(default_factory=GeocoderConfig)
    docs: DocsConfig
    webhook: WebhookConfig
    outbox: OutboxConfig
    order: OrderConfig
    market: MarketConfig
    referral: ReferralConfig
    campaign: CampaignRuntimeConfig = Field(
        default_factory=CampaignRuntimeConfig
    )
    financial: FinancialConfig = Field(default_factory=FinancialConfig)
    messenger_linking: MessengerLinkingConfig = Field(
        default_factory=MessengerLinkingConfig
    )
    max_bot: MaxBotConfig | None = None

    @property
    def customer_workflows_enabled(self) -> bool:
        return self.order.customer_workflows_enabled

    @model_validator(mode="before")
    @classmethod
    def _handle_flat_dict(cls, data: Any) -> Any:
        if not _is_flat_dict(data):
            return data
        nested = _flat_to_nested(data if isinstance(data, dict) else {})
        return {
            "bot": BotConfig.model_validate(nested["bot"]),
            "log": LogConfig.model_validate(nested["log"]),
            "db": DbConfig.model_validate(nested["db"]),
            "admin": AdminConfig.model_validate(nested["admin"]),
            "kafka": KafkaConfig.model_validate(nested["kafka"]),
            "feedback": FeedbackConfig.model_validate(nested["feedback"]),
            "role_reminder": RoleReminderConfig.model_validate(
                nested["role_reminder"]
            ),
            "redis": RedisConfig.model_validate(nested["redis"]),
            "instagram": InstagramConfig.model_validate(nested["instagram"]),
            "geocoder": GeocoderConfig.model_validate(nested["geocoder"]),
            "docs": DocsConfig.model_validate(nested["docs"]),
            "webhook": WebhookConfig.model_validate(nested["webhook"]),
            "outbox": OutboxConfig.model_validate(nested["outbox"]),
            "order": OrderConfig.model_validate(nested["order"]),
            "market": MarketConfig.model_validate(nested["market"]),
            "referral": ReferralConfig.model_validate(nested["referral"]),
            "campaign": CampaignRuntimeConfig.model_validate(
                nested["campaign"]
            ),
            "financial": FinancialConfig.model_validate(nested["financial"]),
            "messenger_linking": MessengerLinkingConfig.model_validate(
                nested["messenger_linking"]
            ),
            "max_bot": (
                max_cfg
                if (
                    max_cfg := MaxBotConfig.model_validate(
                        nested.get("max_bot", {})
                    )
                ).token
                else None
            ),
        }


def load_config() -> AppConfig:
    """Load config from environment variables and .env file.

    Environment variables are read via pydantic-settings (BaseSettings).
    AppConfig.model_validate({}) triggers _handle_flat_dict which
    loads from env through nested section configs (BotConfig, DbConfig, etc.).
    """
    return AppConfig.model_validate({})
