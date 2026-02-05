"""Application configuration loading.

Config is split into domain sections (bot, db, kafka, etc.) to simplify
maintenance and testing. AppConfig composes them.
"""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV = SettingsConfigDict(
    env_file=".env",
    env_file_encoding="utf-8",
    extra="ignore",
)

_FLAT_KEYS = {
    "bot": ["BOT_TOKEN", "TELEGRAM_PROVIDER_TOKEN"],
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
    ],
    "docs": [
        "DOCS_OFFER_URL",
        "DOCS_PRIVACY_URL",
        "DOCS_CONSENT_URL",
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


class AdminConfig(BaseSettings):
    model_config = _ENV

    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    admin_secret: str = Field(default="", alias="ADMIN_SECRET")
    admin_site_name: str = Field(default="UGC Admin", alias="ADMIN_SITE_NAME")


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


class DocsConfig(BaseSettings):
    """URLs for legal documents (offer, privacy, consent)."""

    model_config = _ENV

    docs_offer_url: str = Field(default="", alias="DOCS_OFFER_URL")
    docs_privacy_url: str = Field(default="", alias="DOCS_PRIVACY_URL")
    docs_consent_url: str = Field(default="", alias="DOCS_CONSENT_URL")


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
    docs: DocsConfig

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
            "docs": DocsConfig.model_validate(nested["docs"]),
        }


def load_config() -> AppConfig:
    """Load config from env (.env)."""
    return AppConfig.model_validate({})
