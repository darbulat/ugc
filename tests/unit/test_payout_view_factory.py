"""Reader crypto preserves startup failure and key-loss contracts."""

import base64
import importlib
import os

import pytest
from pydantic import SecretStr


def test_read_factory_missing_key_is_bootable_without_a_fallback(config):
    module = importlib.import_module("ugc_bot.container.payout_view_factory")
    config.financial.requisites_key = SecretStr("")
    config.financial.requisites_key_id = ""
    service = module.build_payout_view_service(config, object())
    assert service.crypto is None
    with pytest.raises(ValueError, match="payout_database_required"):
        module.build_payout_view_service(config, None)


@pytest.mark.parametrize(
    "key,key_id", [("bad", "synthetic"), ("", "synthetic")]
)
def test_explicit_invalid_crypto_still_fails_startup(config, key, key_id):
    module = importlib.import_module("ugc_bot.container.payout_view_factory")
    config.financial.requisites_key = SecretStr(key)
    config.financial.requisites_key_id = key_id
    with pytest.raises(
        ValueError, match="payout_encryption_configuration_required"
    ):
        module.build_payout_view_service(config, object())


def test_valid_external_crypto_is_not_replaced(config):
    module = importlib.import_module("ugc_bot.container.payout_view_factory")
    config.financial.requisites_key = SecretStr(
        base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    config.financial.requisites_key_id = "synthetic-external"
    service = module.build_payout_view_service(config, object())
    assert service.crypto.key_id == "synthetic-external"
