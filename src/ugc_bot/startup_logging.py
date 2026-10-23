"""Startup logging helpers.

Provides consistent startup logs across entrypoints:
- service version
- sanitized config (no secrets)

Works with both text and JSON logging. If JSON logging is not detected
at runtime, the config is embedded into the log message because standard
text formatters usually drop extra fields.
"""

import json
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ugc_bot.logging_setup import JSONFormatter

MASK = "***"
SENSITIVE_KEYS = {
    "admin_password",
    "admin_secret",
    "bot_token",
    "database_url",
    "instagram_access_token",
    "instagram_app_secret",
    "instagram_webhook_verify_token",
    "redis_url",
    "telegram_provider_token",
    "webhook_secret",
}
SENSITIVE_KEYWORDS = (
    "password",
    "secret",
    "token",
    "apikey",
    "authorization",
    "credential",
    "signature",
)


def get_service_version() -> str:
    """Return installed service version if available."""

    for dist_name in ("ugc-bot", "ugc_bot"):
        try:
            return version(dist_name)
        except PackageNotFoundError:
            continue
    return "unknown"


def _mask_url_credentials(value: str) -> str:
    """Mask URL passwords, bearer userinfo and sensitive query parameters."""

    try:
        parts = urlsplit(value)
    except ValueError:
        # A malformed URL must not bypass credential redaction.
        return MASK if "://" in value or value.startswith("//") else value

    if not parts.netloc:
        return value

    netloc = parts.netloc
    if "@" in netloc:
        _, hostinfo = netloc.rsplit("@", 1)
        netloc = f"{MASK}@{hostinfo}"

    query = _mask_url_parameters(parts.query)
    fragment = _mask_url_parameters(parts.fragment)
    return urlunsplit((parts.scheme, netloc, parts.path, query, fragment))


def _mask_url_parameters(value: str) -> str:
    """Mask labelled credentials in query strings or OAuth-style fragments."""
    pairs = parse_qsl(value, keep_blank_values=True)
    if not any(_is_sensitive_key(key) for key, _ in pairs):
        return value
    return urlencode(
        [(key, MASK if _is_sensitive_key(key) else val) for key, val in pairs]
    )


def _is_sensitive_key(key: str) -> bool:
    """Return True if key likely holds sensitive value."""

    lowered = key.lower()
    if lowered in SENSITIVE_KEYS:
        return True
    normalized = "".join(char for char in lowered if char.isalnum())
    return any(marker in normalized for marker in SENSITIVE_KEYWORDS)


def _sanitize_for_logging(obj: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize a config-like structure for safe logging."""

    if key is not None and _is_sensitive_key(key):
        return MASK

    if isinstance(obj, dict):
        return {
            str(k): _sanitize_for_logging(v, key=str(k)) for k, v in obj.items()
        }

    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_logging(v) for v in obj]

    if isinstance(obj, str):
        return _mask_url_credentials(obj)

    if obj is None or isinstance(obj, (bool, int, float)):
        return obj

    # Never stringify opaque providers or credential objects via JSON fallback.
    return MASK


def safe_config_for_logging(config: Any) -> dict[str, Any]:
    """Return config dump suitable for logs (secrets masked)."""

    raw: Any
    try:
        if hasattr(config, "model_dump"):
            raw = config.model_dump()
        elif isinstance(config, dict):
            raw = config
        else:
            raw = dict(config)
    except Exception:
        return {}

    sanitized = _sanitize_for_logging(raw)
    return sanitized if isinstance(sanitized, dict) else {}


def is_json_logging_configured() -> bool:
    """Return True if root handlers use our JSON formatter."""

    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        formatter = getattr(handler, "formatter", None)
        if isinstance(formatter, JSONFormatter):
            return True
    return False  # pragma: no cover


def log_startup_info(*, logger: Any, service_name: str, config: Any) -> None:
    """Log startup info with version and sanitized config.

    Args:
        logger: Logger-like object with .info().
        service_name: Human-readable service identifier.
        config: Application config object (typically AppConfig).
    """

    service_version = get_service_version()
    safe_config = safe_config_for_logging(config)

    # Text logs: embed config into message.
    if not is_json_logging_configured():
        logger.info(
            "%s starting (version=%s, config=%s)",
            service_name,
            service_version,
            json.dumps(
                safe_config, ensure_ascii=False, default=str, sort_keys=True
            ),
        )
        return  # pragma: no cover

    logger.info(
        "%s starting",
        service_name,
        extra={
            "service": service_name,
            "service_version": service_version,
            "config": safe_config,
        },
    )
