"""New private capabilities reject stale or ambiguous signed envelopes."""

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from ugc_bot.miniapp.auth import validate_init_data_and_get_telegram_user_id


def signed(auth_date="100000", *, bot_token="sensitive-token", **extra):
    data = {"user": json.dumps({"id": 101}), **extra}
    if auth_date is not None:
        data["auth_date"] = auth_date
    check = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret = hmac.new(
        b"WebAppData", bot_token.encode(), hashlib.sha256
    ).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


@pytest.mark.parametrize("age", [0, 86400, -60])
def test_current_and_boundary_sessions_are_accepted(age):
    from ugc_bot.miniapp.principal import require_recent_init_data

    raw = signed()
    assert (
        validate_init_data_and_get_telegram_user_id(raw, "sensitive-token")
        == "101"
    )
    require_recent_init_data(raw, now=100000 + age)


@pytest.mark.parametrize("age", [86401, -61])
def test_old_or_excessively_future_signed_session_is_rejected(age):
    from ugc_bot.miniapp.principal import require_recent_init_data

    raw = signed()
    with pytest.raises(HTTPException) as error:
        require_recent_init_data(raw, now=100000 + age)
    assert error.value.status_code == 401


@pytest.mark.parametrize("date", [None, "", "-1", "NaN", "1.1", "١٠٠٠٠٠"])
def test_missing_or_non_integer_auth_date_is_rejected(date):
    from ugc_bot.miniapp.principal import require_recent_init_data

    with pytest.raises(HTTPException) as error:
        require_recent_init_data(signed(date), now=100000)
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "extra", ["&auth_date=100000", "&user=%7B%7D", "&hash=x"]
)
def test_duplicate_signed_fields_are_rejected(extra):
    from ugc_bot.miniapp.principal import require_recent_init_data

    with pytest.raises(HTTPException) as error:
        require_recent_init_data(signed() + extra, now=100000)
    assert error.value.status_code == 401


def test_invalid_signature_logs_no_token_hash_or_user_payload(caplog):
    raw = signed(user=json.dumps({"id": 101, "username": "private-person"}))
    with pytest.raises(ValueError, match="Invalid init_data signature"):
        validate_init_data_and_get_telegram_user_id(raw, "private-bot-token")
    assert "private-bo" not in caplog.text
    assert "private-person" not in caplog.text
    assert "computed=" not in caplog.text


@pytest.mark.parametrize("raw", ["x" * 16385, signed("1000000000000")])
def test_oversized_payload_or_timestamp_is_rejected(raw):
    from ugc_bot.miniapp.principal import require_recent_init_data

    with pytest.raises(HTTPException) as error:
        require_recent_init_data(raw, now=100000)
    assert error.value.status_code == 401
