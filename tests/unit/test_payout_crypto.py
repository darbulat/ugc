"""Externally supplied keys protect recipient snapshots and context."""

import base64
import importlib
import os
from uuid import uuid4

import pytest


def adapter(key=None, key_id="synthetic-test-key"):
    try:
        cls = importlib.import_module(
            "ugc_bot.infrastructure.secure_requisites"
        ).PayoutRequisitesCrypto
    except ModuleNotFoundError:
        pytest.fail("required payout requisites crypto adapter missing")
    return cls(
        key
        if key is not None
        else base64.urlsafe_b64encode(os.urandom(32)).decode(),
        key_id,
    )


def test_recipient_details_round_trip_and_wrong_context_fails():
    crypto = adapter()
    owner, identity = uuid4(), uuid4()
    details = {"recipient_name": "Synthetic Name", "bank_account": "1234567890"}
    stored = crypto.seal(details, owner, identity)
    assert details["bank_account"].encode() not in stored["ciphertext"]
    assert stored["masked_label"] == "••••7890"
    assert crypto.open(stored, owner, identity) == details
    for user, ref in ((uuid4(), identity), (owner, uuid4())):
        with pytest.raises(
            ValueError, match="payout_requisites_authentication_failed"
        ):
            crypto.open(stored, user, ref)
    with pytest.raises(
        ValueError, match="payout_requisites_authentication_failed"
    ):
        crypto.open(
            stored | {"ciphertext": stored["ciphertext"][:-1] + b"x"},
            owner,
            identity,
        )


@pytest.mark.parametrize(
    "key,key_id",
    [
        ("", ""),
        ("bad", "test"),
        (base64.urlsafe_b64encode(b"x" * 16).decode(), "test"),
        (base64.urlsafe_b64encode(b"x" * 32).decode(), ""),
    ],
)
def test_missing_or_invalid_external_key_never_falls_back(key, key_id):
    with pytest.raises(
        ValueError, match="payout_encryption_configuration_required"
    ):
        adapter(key, key_id)


def test_key_id_mismatch_cannot_decrypt_and_fingerprint_is_stable():
    crypto = adapter()
    owner, ref = uuid4(), uuid4()
    data = {"bank_account": "123456", "recipient_name": "Name"}
    first, second = crypto.seal(data, owner, ref), crypto.seal(data, owner, ref)
    assert first["ciphertext"] != second["ciphertext"]
    assert first["fingerprint"] == second["fingerprint"]
    assert (
        first["fingerprint"]
        != crypto.seal(data | {"bank_account": "654321"}, owner, ref)[
            "fingerprint"
        ]
    )
    with pytest.raises(
        ValueError, match="payout_requisites_authentication_failed"
    ):
        crypto.open(first | {"key_id": "different"}, owner, ref)


@pytest.mark.parametrize(
    "details",
    [
        {},
        {"bank_account": ""},
        {"bank_account": 123},
        {"x" * 65: "value"},
        {str(i): "v" for i in range(31)},
        {str(i): "x" * 1500 for i in range(20)},
    ],
)
def test_invalid_or_excessive_private_details_are_refused(details):
    with pytest.raises(ValueError, match="payout_requisites_fields_invalid"):
        adapter().seal(details, uuid4(), uuid4())


def test_authenticated_ciphertext_cannot_change_fingerprint():
    crypto = adapter()
    owner, ref = uuid4(), uuid4()
    record = crypto.seal({"bank_account": "12345"}, owner, ref)
    with pytest.raises(
        ValueError, match="payout_requisites_authentication_failed"
    ):
        crypto.open(record | {"fingerprint": "0" * 64}, owner, ref)


def test_flat_config_keeps_external_key_secret_and_has_no_fallback():
    from ugc_bot.config import AppConfig

    key = base64.urlsafe_b64encode(os.urandom(32)).decode()
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "FINANCIAL_REQUISITES_KEY": key,
            "FINANCIAL_REQUISITES_KEY_ID": "synthetic",
            "FINANCIAL_MANUAL_BANK_ACCOUNT_ID": "synthetic-origin",
            "FINANCIAL_CORE_ENABLED": False,
            "FINANCIAL_PAYOUTS_ENABLED": False,
        }
    )
    assert config.financial.requisites_key.get_secret_value() == key
    assert key not in repr(config)
    assert config.financial.manual_bank_account_id == "synthetic-origin"
    assert (
        not config.financial.core_enabled
        and not config.financial.payouts_enabled
    )


def test_runtime_without_database_cannot_construct_payout_authority():
    from ugc_bot.config import AppConfig
    from ugc_bot.container.payout_factory import build_payout_service

    with pytest.raises(ValueError, match="payout_database_required"):
        build_payout_service(
            AppConfig.model_validate(
                {"BOT_TOKEN": "test-token", "FINANCIAL_CORE_ENABLED": False}
            ),
            None,
            None,
        )
