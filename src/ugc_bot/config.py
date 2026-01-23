"""Application configuration loading."""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration container."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="text", alias="LOG_FORMAT")
    database_url: str = Field(default="", alias="DATABASE_URL")
    admin_username: str = Field(default="admin", alias="ADMIN_USERNAME")
    admin_password: str = Field(default="", alias="ADMIN_PASSWORD")
    admin_secret: str = Field(default="", alias="ADMIN_SECRET")
    admin_site_name: str = Field(default="UGC Admin", alias="ADMIN_SITE_NAME")
    kafka_enabled: bool = Field(default=True, alias="KAFKA_ENABLED")
    kafka_bootstrap_servers: str = Field(
        default="kafka:9092", alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    kafka_topic: str = Field(default="order_activated", alias="KAFKA_TOPIC")
    kafka_group_id: str = Field(default="ugc-bot", alias="KAFKA_GROUP_ID")
    kafka_dlq_topic: str = Field(default="order_activated_dlq", alias="KAFKA_DLQ_TOPIC")
    kafka_send_retries: int = Field(default=3, alias="KAFKA_SEND_RETRIES")
    kafka_send_retry_delay_seconds: float = Field(
        default=1.0, alias="KAFKA_SEND_RETRY_DELAY_SECONDS"
    )
    feedback_delay_hours: int = Field(default=72, alias="FEEDBACK_DELAY_HOURS")
    feedback_poll_interval_seconds: int = Field(
        default=300, alias="FEEDBACK_POLL_INTERVAL_SECONDS"
    )
    feedback_enabled: bool = Field(default=True, alias="FEEDBACK_ENABLED")
    telegram_provider_token: str = Field(default="", alias="TELEGRAM_PROVIDER_TOKEN")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    use_redis_storage: bool = Field(default=True, alias="USE_REDIS_STORAGE")
    instagram_webhook_verify_token: str = Field(
        default="", alias="INSTAGRAM_WEBHOOK_VERIFY_TOKEN"
    )
    instagram_app_secret: str = Field(default="", alias="INSTAGRAM_APP_SECRET")
    admin_instagram_username: str = Field(
        default="admin_ugc_bot", alias="ADMIN_INSTAGRAM_USERNAME"
    )
    instagram_access_token: str = Field(default="", alias="INSTAGRAM_ACCESS_TOKEN")
    instagram_api_base_url: str = Field(
        default="https://graph.instagram.com", alias="INSTAGRAM_API_BASE_URL"
    )

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: str) -> str:
        """Ensure bot token is provided."""

        if not value.strip():
            raise ValueError("BOT_TOKEN is required to start the bot.")
        return value.strip()

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """Normalize log level to uppercase."""

        return value.strip().upper()


def load_config() -> AppConfig:
    """Load configuration from environment variables."""

    return AppConfig.model_validate({})
