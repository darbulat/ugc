"""Missing linking config cannot borrow bot, payment or admin credentials."""

import base64
import importlib
import importlib.util

from ugc_bot.config import AppConfig


def factory():
    module = "ugc_bot.container.messenger_linking_factory"
    assert importlib.util.find_spec(module) is not None, (
        "linking factory missing"
    )
    return importlib.import_module(module).build_messenger_linking_service


def config(**changes):
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "123:" + "A" * 35,
            "TELEGRAM_BOT_USERNAME": "synthetic_test_bot",
            "MAX_BOT_TOKEN": "max-test-token",
            "WEBHOOK_SECRET": "synthetic-secret",
            "MESSENGER_LINKING_ENABLED": True,
            "MESSENGER_LINKING_TOKEN_SECRET": base64.urlsafe_b64encode(
                b"x" * 32
            )
            .decode()
            .rstrip("="),
            "MESSENGER_LINKING_KEY_ID": "test-key",
            **changes,
        }
    )


def test_missing_transaction_manager_has_no_linking_service():
    assert factory()(config(), None) is None


def test_production_crypto_freezes_both_configured_native_bot_scopes():
    build = factory()
    first = build(config(), object())
    changed = build(config(MAX_BOT_TOKEN="different-max-token"), object())
    assert first.scope.bot_id == 123
    assert first.scope.max_bot_fingerprint != changed.scope.max_bot_fingerprint
    assert len(first.scope.max_bot_fingerprint) == 64
    assert first.enabled


def test_missing_material_or_bot_scope_is_safe_unavailable_with_reads():
    build = factory()
    for changes in [
        {"WEBHOOK_SECRET": ""},
        {"MESSENGER_LINKING_TOKEN_SECRET": None},
        {"MESSENGER_LINKING_KEY_ID": None},
        {"TELEGRAM_BOT_USERNAME": ""},
        {"MAX_BOT_TOKEN": ""},
        {"BOT_TOKEN": "invalid-token"},
    ]:
        value = build(config(**changes), object())
        assert value.tokens is None
        assert value.repository is not None


def test_blank_native_ingress_secret_disables_new_linking_but_preserves_reads():
    value = factory()(config(WEBHOOK_SECRET="   "), object())
    assert value.tokens is None
    assert value.repository is not None
