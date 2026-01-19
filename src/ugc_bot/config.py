"""Application configuration loading."""

from __future__ import annotations

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
    openai_enabled: bool = Field(default=False, alias="OPENAI_ENABLED")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

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
