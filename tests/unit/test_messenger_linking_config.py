"""Dedicated linking capability never borrows a payment or bot secret."""

import base64

import pytest
from pydantic import SecretStr, ValidationError

from ugc_bot.config import AppConfig, load_config

KEY = (
    base64.urlsafe_b64encode(b"synthetic-test-link-key-32-bytes!!")
    .decode()
    .rstrip("=")
)


def test_linking_defaults_off_with_no_fallback():
    config = AppConfig.model_validate({"BOT_TOKEN": "test-token"})
    section = getattr(config, "messenger_linking", None)
    assert section is not None, "dedicated linking configuration is missing"
    assert section.enabled is False
    assert section.token_secret is None
    assert section.key_id is None


def test_flat_linking_config_uses_dedicated_secret_and_redacts_it():
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "MESSENGER_LINKING_ENABLED": "true",
            "MESSENGER_LINKING_TOKEN_SECRET": KEY,
            "MESSENGER_LINKING_KEY_ID": "lk-test-1",
        }
    )
    section = getattr(config, "messenger_linking", None)
    assert section is not None, "flat mapping must preserve linking config"
    assert section.enabled is True
    assert isinstance(section.token_secret, SecretStr)
    assert section.token_secret.get_secret_value() == KEY
    assert section.key_id == "lk-test-1"
    assert KEY not in repr(section) + config.model_dump_json()
    nested = config.model_dump()
    rebuilt = AppConfig.model_validate(nested)
    assert rebuilt.messenger_linking == section


def test_linking_config_reads_environment(monkeypatch):
    monkeypatch.setenv("MESSENGER_LINKING_ENABLED", "true")
    monkeypatch.setenv("MESSENGER_LINKING_TOKEN_SECRET", KEY)
    monkeypatch.setenv("MESSENGER_LINKING_KEY_ID", "env-key")
    config = load_config()
    section = getattr(config, "messenger_linking", None)
    assert section is not None, "linking env mapping is missing"
    assert section.enabled is True
    assert section.token_secret.get_secret_value() == KEY
    assert section.key_id == "env-key"


@pytest.mark.parametrize(
    "key", ["", "short", "x" * 31, "x" * 32, "x" * 43, "+" * 44]
)
def test_explicit_weak_linking_key_is_refused(key):
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "MESSENGER_LINKING_TOKEN_SECRET": key,
                "MESSENGER_LINKING_KEY_ID": "test-key",
            }
        )


@pytest.mark.parametrize("kid", ["", "bad key", "a" * 65])
def test_explicit_invalid_linking_key_id_is_refused(kid):
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "BOT_TOKEN": "test-token",
                "MESSENGER_LINKING_TOKEN_SECRET": KEY,
                "MESSENGER_LINKING_KEY_ID": kid,
            }
        )


@pytest.mark.parametrize(
    "change",
    [
        {"MESSENGER_LINKING_KEY_ID": "bad key"},
        {"MESSENGER_LINKING_TOKEN_SECRET": KEY + "+"},
    ],
)
def test_outer_config_validation_never_echoes_linking_key(change):
    data = {
        "BOT_TOKEN": "test-token",
        "MESSENGER_LINKING_TOKEN_SECRET": KEY,
        "MESSENGER_LINKING_KEY_ID": "test-key",
        **change,
    }
    with pytest.raises(ValidationError) as failure:
        AppConfig.model_validate(data)
    assert KEY not in str(failure.value)
