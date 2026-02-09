"""Tests for startup logging helpers."""

import logging
from unittest.mock import Mock

import pytest

from ugc_bot import startup_logging as sl
from ugc_bot.config import AppConfig
from ugc_bot.logging_setup import JSONFormatter


def test_get_service_version_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Return 'unknown' when distribution metadata is not available."""

    def _raise(_name: str):  # type: ignore[no-untyped-def]
        raise sl.PackageNotFoundError

    monkeypatch.setattr(sl, "version", _raise)
    assert sl.get_service_version() == "unknown"


def test_mask_url_credentials_masks_userinfo() -> None:
    """Mask userinfo in URLs that include credentials."""

    assert (
        sl._mask_url_credentials("postgresql://user:pass@localhost:5432/db")
        == "postgresql://user:***@localhost:5432/db"
    )
    assert (
        sl._mask_url_credentials("redis://localhost:6379/0")
        == "redis://localhost:6379/0"
    )


def test_mask_url_credentials_unchanged_when_no_colon_in_userinfo() -> None:
    """Return value when netloc has @ but userinfo has no ':'."""
    assert (
        sl._mask_url_credentials("http://user@host/path")
        == "http://user@host/path"
    )


def test_sanitize_for_logging_returns_non_dict_list_str_unchanged() -> None:
    """Return non-dict/list/str values as-is (e.g. int, None)."""
    assert sl._sanitize_for_logging(42) == 42
    assert sl._sanitize_for_logging(None) is None


def test_safe_config_for_logging_accepts_iterable_config() -> None:
    """Accept config not dict, no model_dump, but dict(config) works."""
    config_pairs = [("bot_token", "x"), ("database_url", "y")]
    got = sl.safe_config_for_logging(config_pairs)
    assert got == {"bot_token": "***", "database_url": "***"}


def test_sanitize_for_logging_handles_list() -> None:
    """_sanitize_for_logging recurses into lists."""
    got = sl._sanitize_for_logging([1, "http://u:p@h/path"])
    assert got == [1, "http://u:***@h/path"]


def test_mask_url_credentials_handles_parser_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return input when URL parsing raises."""

    def _boom(_value: str):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    monkeypatch.setattr(sl, "urlsplit", _boom)
    assert sl._mask_url_credentials("not-a-url") == "not-a-url"


def test_safe_config_masks_sensitive_and_url_credentials() -> None:
    """Mask known secret fields and credentials embedded into URLs."""

    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "token",
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            "ADMIN_PASSWORD": "admin-pass",
            "ADMIN_SECRET": "admin-secret",
            "REDIS_URL": "redis://user:pass@localhost:6379/0",
            "INSTAGRAM_API_BASE_URL": "https://user:pass@example.com/api",
        }
    )
    safe = sl.safe_config_for_logging(config)

    assert safe["bot"]["bot_token"] == "***"
    assert safe["db"]["database_url"] == "***"
    assert safe["admin"]["admin_password"] == "***"
    assert safe["admin"]["admin_secret"] == "***"
    assert safe["redis"]["redis_url"] == "***"
    assert (
        safe["instagram"]["instagram_api_base_url"]
        == "https://user:***@example.com/api"
    )


def test_safe_config_for_logging_handles_unserializable_config() -> None:
    """Return empty dict when config cannot be dumped."""

    class BadConfig:
        def model_dump(self) -> dict:  # type: ignore[no-untyped-def]
            raise RuntimeError("boom")

    assert sl.safe_config_for_logging(BadConfig()) == {}


def test_is_json_logging_configured_detects_jsonformatter() -> None:
    """Detect JSON mode by inspecting root handlers."""

    root = logging.getLogger()
    old_handlers = list(root.handlers)
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.handlers = [handler]
    try:
        assert sl.is_json_logging_configured() is True
    finally:
        root.handlers = old_handlers


def test_log_startup_info_embeds_config_for_text_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When JSON formatter is not configured, embed config in message."""

    monkeypatch.setattr(sl, "get_service_version", lambda: "1.2.3")
    monkeypatch.setattr(sl, "is_json_logging_configured", lambda: False)

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "token", "DATABASE_URL": "db"}
    )
    with caplog.at_level("INFO"):
        sl.log_startup_info(
            logger=logging.getLogger("svc-text"),
            service_name="svc-text",
            config=config,
        )

    message = "\n".join(r.getMessage() for r in caplog.records)
    assert "svc-text starting" in message
    assert "version=1.2.3" in message
    assert '"bot_token": "***"' in message
    assert '"database_url": "***"' in message


def test_log_startup_info_uses_extra_for_json_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When JSON formatter is configured, send fields through extra."""

    monkeypatch.setattr(sl, "get_service_version", lambda: "1.2.3")
    monkeypatch.setattr(sl, "is_json_logging_configured", lambda: True)

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "token", "DATABASE_URL": "db"}
    )
    with caplog.at_level("INFO"):
        sl.log_startup_info(
            logger=logging.getLogger("svc-json"),
            service_name="svc-json",
            config=config,
        )

    # Find our record and ensure extra fields exist.
    rec = next(r for r in caplog.records if r.name == "svc-json")
    assert rec.getMessage() == "svc-json starting"
    assert rec.service == "svc-json"
    assert rec.service_version == "1.2.3"
    assert isinstance(rec.config, dict)


def test_log_startup_info_accepts_logger_like(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Support logger-like objects (used in some unit tests)."""

    monkeypatch.setattr(sl, "get_service_version", lambda: "1.2.3")
    fake_logger = Mock()
    sl.log_startup_info(
        logger=fake_logger,
        service_name="svc",
        config={"db": {"database_url": "db"}},
    )
    assert fake_logger.info.called
