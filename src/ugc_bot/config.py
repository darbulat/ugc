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
