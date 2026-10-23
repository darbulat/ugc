"""Public startup logger regressions using synthetic credentials only."""

import io
import json
import logging
from typing import Any

import pytest

from ugc_bot.config import AppConfig
from ugc_bot.logging_setup import JSONFormatter
from ugc_bot.startup_logging import log_startup_info


def emitted_config(
    config: Any, json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, dict[str, Any]]:
    """Exercise the real logger, formatter and startup format detection."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JSONFormatter() if json_mode else logging.Formatter("%(message)s")
    )
    monkeypatch.setattr(logging.getLogger(), "handlers", [handler])
    logger = logging.Logger("synthetic-startup", level=logging.INFO)
    logger.addHandler(handler)
    log_startup_info(logger=logger, service_name="synthetic-svc", config=config)
    output = stream.getvalue()
    if json_mode:
        payload = json.loads(output)
        assert payload["service"] == "synthetic-svc"
        assert payload["service_version"]
        return output, payload["config"]
    assert "synthetic-svc starting (version=" in output
    return output, json.loads(output.split(", config=", 1)[1].rstrip(")\n"))


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_redacts_real_config_external_api_keys(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "synthetic-bot-credential",
            "DATABASE_URL": "postgresql://fixture:synthetic-db@example.test/db",
            "ADMIN_PASSWORD": "synthetic-admin-password",
            "ADMIN_SECRET": "synthetic-admin-secret",
            "KAFKA_ENABLED": False,
            "SCRAPECREATORS_API_KEY": "synthetic-scrape-credential",
            "DADATA_API_KEY": "synthetic-dadata-credential",
        }
    )
    output, safe = emitted_config(config, json_mode, monkeypatch)
    assert "synthetic-scrape-credential" not in output
    assert "synthetic-dadata-credential" not in output
    assert safe["instagram"]["scrapecreators_api_key"] == "***"
    assert safe["geocoder"]["dadata_api_key"] == "***"
    assert safe["bot"]["bot_token"] == "***"
    assert safe["db"]["database_url"] == "***"
    assert safe["admin"]["admin_password"] == "***"
    assert safe["admin"]["admin_secret"] == "***"
    assert safe["kafka"]["kafka_enabled"] is False
    assert safe["log"]["log_level"] == config.log.log_level
    assert safe["instagram"]["scrapecreators_base_url"].startswith("https://")


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_redacts_secrets_in_nested_sequences(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {
        "providers": (
            {"APIkey": "synthetic-camel-key", "timeout": 12},
            [{"API-KEY": "synthetic-dash-key", "enabled": True}],
            {"api_key": "synthetic-underscore-key"},
            {"accessToken": "synthetic-token"},
            {"PASSWORD": "synthetic-password"},
            {"client_secret": "synthetic-client-secret"},
        ),
        "retries": 3,
    }
    output, safe = emitted_config(config, json_mode, monkeypatch)
    for credential in (
        "synthetic-camel-key",
        "synthetic-dash-key",
        "synthetic-underscore-key",
        "synthetic-token",
        "synthetic-password",
        "synthetic-client-secret",
    ):
        assert credential not in output
    assert safe["providers"][0] == {"APIkey": "***", "timeout": 12}
    assert safe["providers"][1] == [{"API-KEY": "***", "enabled": True}]
    assert safe["retries"] == 3


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_never_stringifies_raw_provider_objects(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Provider:
        def __str__(self) -> str:
            return "synthetic-raw-provider-credential"

        def __repr__(self) -> str:
            return "synthetic-raw-provider-credential"

    output, safe = emitted_config(
        {"providers": [Provider()], "enabled": True}, json_mode, monkeypatch
    )
    assert "synthetic-raw-provider-credential" not in output
    assert safe == {"providers": ["***"], "enabled": True}


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "endpoint",
    [
        "https://synthetic-url-credential@example.test/api",
        "https://example.test/api?api_key=synthetic-url-credential&limit=5",
        "https://[invalid/synthetic-url-credential",
    ],
)
def test_startup_redacts_url_credentials(
    json_mode: bool, endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = {
        "database_url": "postgresql://fixture:synthetic-db@example.test/db",
        "endpoint": endpoint,
        "public_url": "https://example.test/public",
    }
    output, safe = emitted_config(config, json_mode, monkeypatch)
    assert "synthetic-url-credential" not in output
    assert "synthetic-db" not in output
    assert safe["database_url"] == "***"
    assert safe["public_url"] == config["public_url"]


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_redacts_credential_in_url_username(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint = "https://synthetic-user-credential:x@example.test/api?limit=5"
    output, safe = emitted_config(
        {"endpoint": endpoint}, json_mode, monkeypatch
    )
    assert "synthetic-user-credential" not in output
    assert safe["endpoint"] == "https://***@example.test/api?limit=5"


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    "field",
    ["Authorization", "Proxy-Authorization", "credentials", "X-Signature"],
)
def test_startup_redacts_authentication_metadata(
    json_mode: bool, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, safe = emitted_config(
        {"providers": [{field: "synthetic-header-credential", "timeout": 12}]},
        json_mode,
        monkeypatch,
    )
    assert "synthetic-header-credential" not in output
    assert safe == {"providers": [{field: "***", "timeout": 12}]}


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_redacts_credential_in_url_fragment(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, safe = emitted_config(
        {
            "endpoint": "https://example.test/callback#access_token=synthetic-fragment-credential&mode=public"
        },
        json_mode,
        monkeypatch,
    )
    assert "synthetic-fragment-credential" not in output
    assert "mode=public" in safe["endpoint"]


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_redacts_network_path_userinfo(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, safe = emitted_config(
        {
            "endpoint": (
                "//synthetic-network-user:synthetic-network-password"
                "@example.test/api?limit=5"
            ),
            "asset": "../public/icon.svg",
        },
        json_mode,
        monkeypatch,
    )
    assert "synthetic-network-user" not in output
    assert "synthetic-network-password" not in output
    assert safe["endpoint"] == "//***@example.test/api?limit=5"
    assert safe["asset"] == "../public/icon.svg"


@pytest.mark.parametrize("json_mode", [False, True])
def test_startup_masks_malformed_network_path(
    json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    output, safe = emitted_config(
        {"endpoint": "//synthetic-invalid-credential:x@[invalid"},
        json_mode,
        monkeypatch,
    )
    assert "synthetic-invalid-credential" not in output
    assert safe["endpoint"] == "***"
