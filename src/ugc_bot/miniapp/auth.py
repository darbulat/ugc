"""Validate Telegram Web App initData and extract user id.

See: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

import hashlib
import hmac
import json
import logging
from urllib.parse import parse_qsl

logger = logging.getLogger(__name__)

_WEBAPP_DATA_KEY = "WebAppData"


def validate_init_data_and_get_telegram_user_id(
    init_data: str, bot_token: str
) -> str:
    """Validate initData signature and return Telegram user id (external_id).

    Args:
        init_data: Raw query string from Telegram.WebApp.initData.
        bot_token: Bot token for HMAC verification.

    Returns:
        Telegram user id as string (for use as external_id).

    Raises:
        ValueError: If init_data is empty, invalid, or signature check fails.
    """
    if not (init_data or init_data.strip()):
        raise ValueError("init_data is required")

    parsed = parse_qsl(init_data.strip(), keep_blank_values=True)
    if not parsed:
        raise ValueError("init_data is required")

    data_dict = dict(parsed)
    received_hash = data_dict.get("hash")
    if not received_hash:
        raise ValueError("init_data missing hash")

    data_check_parts = sorted(
        (k + "=" + v for k, v in data_dict.items() if k != "hash"),
        key=lambda x: x.split("=", 1)[0],
    )
    data_check_string = "\n".join(data_check_parts)

    secret_key = hmac.new(
        _WEBAPP_DATA_KEY.encode(),
        bot_token.encode(),
        hashlib.sha256,
    ).digest()

    computed_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        logger.warning("initData signature mismatch")
        raise ValueError("Invalid init_data signature")

    user_json = data_dict.get("user")
    if not user_json:
        raise ValueError("init_data missing user")

    try:
        user = json.loads(user_json)
    except json.JSONDecodeError as e:
        raise ValueError("init_data user is not valid JSON") from e

    if not isinstance(user, dict):
        raise ValueError("init_data user must be an object")

    telegram_id = user.get("id")
    if telegram_id is None:
        raise ValueError("init_data user missing id")

    return str(telegram_id)
