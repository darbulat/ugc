"""Application configuration loading.

Config is split into domain sections (bot, db, kafka, etc.) to simplify
maintenance and testing. AppConfig composes them.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)

_FLAT_KEYS = {
    "bot": ["BOT_TOKEN", "TELEGRAM_PROVIDER_TOKEN", "TELEGRAM_BOT_USERNAME"],
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
        "MAX_ORDER_PRICE",
        "ORDER_RADIUS_KM",
    ],
    "referral": ["REFERRAL_SUPPORT_CHAT_ID", "REFERRAL_BOT_USERNAME"],
    "market": [
        "PAYMENT_CURRENCY",
        "CURRENCY_SYMBOL",
        "BOT_DEFAULT_LOCALE",
        "BOT_START_TEXT",
        "BOT_SUPPORT_RESPONSE_TEXT",
        "BOT_SUPPORT_CONTACT",
        "BOT_RECEIPT_SERVICE_DESCRIPTION",
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
    pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
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


class FeedbackConfig(BaseSettings):
    model_config = _ENV

    feedback_delay_minutes: int = Field(
        default=4320, alias="FEEDBACK_DELAY_MINUTES"
    )
    feedback_poll_interval_seconds: int = Field(
        default=300, alias="FEEDBACK_POLL_INTERVAL_SECONDS"
    )
    feedback_enabled: bool = Field(default=True, alias="FEEDBACK_ENABLED")
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
    referral_stats_limit: int = Field(
        default=10_000,
        alias="REFERRAL_STATS_LIMIT",
    )


# --- Composite ---


class AppConfig(BaseModel):
    """Application configuration."""

    model_config = {"extra": "forbid"}

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
        }


def load_config() -> AppConfig:
    """Load config from environment variables and .env file.

    Environment variables are read via pydantic-settings (BaseSettings).
    AppConfig.model_validate({}) triggers _handle_flat_dict which
    loads from env through nested section configs (BotConfig, DbConfig, etc.).
    """
    return AppConfig.model_validate({})
