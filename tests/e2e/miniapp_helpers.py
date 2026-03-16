"""Mini App E2E helpers: initData generation and Playwright utilities."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from playwright.sync_api import Page

_WEBAPP_DATA_KEY = "WebAppData"

MINIAPP_TEST_USER_IDS: dict[str, dict[str, int]] = {
    "advertiser": {"ru": 990000001, "en": 990000002},
    "blogger": {"ru": 990000011, "en": 990000012},
}


def generate_init_data(bot_token: str, user_id: int, username: str) -> str:
    """Generate a valid Telegram WebApp initData string with HMAC signature.

    Uses the same algorithm as miniapp/auth.py for validation.
    """
    user_obj = json.dumps(
        {"id": user_id, "first_name": "Test", "username": username},
        separators=(",", ":"),
    )
    auth_date = str(int(time.time()))

    params = {"auth_date": auth_date, "user": user_obj}

    # Build data_check_string: sorted key=value pairs joined by \n
    data_check_parts = sorted(
        (f"{k}={v}" for k, v in params.items()),
        key=lambda x: x.split("=", 1)[0],
    )
    data_check_string = "\n".join(data_check_parts)

    # HMAC: secret = HMAC(WebAppData, bot_token),
    # hash = HMAC(secret, data_check_string)
    secret_key = hmac.new(
        _WEBAPP_DATA_KEY.encode(), bot_token.encode(), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    params["hash"] = computed_hash
    return urlencode(params)


def build_telegram_mock_script(
    init_data: str, user_id: int, username: str
) -> str:
    """Return JS to mock window.Telegram.WebApp for Playwright injection."""
    return f"""
    window.Telegram = {{
        WebApp: {{
            initData: {json.dumps(init_data)},
            initDataUnsafe: {{
                user: {{ id: {user_id}, username: {json.dumps(username)} }}
            }},
            ready: function() {{}},
            expand: function() {{}},
            close: function() {{}},
            openLink: function(url) {{ window.open(url, '_blank'); }},
            themeParams: {{}},
            colorScheme: "light",
            MainButton: {{
                show: function() {{}},
                hide: function() {{}},
                setText: function() {{}},
                onClick: function() {{}},
                isVisible: false
            }}
        }}
    }};
    """


def wait_for_screen(page: Page, screen_id: str, timeout: int = 10000) -> None:
    """Wait until a screen becomes active (has .active class)."""
    page.wait_for_selector(f"#{screen_id}.active", timeout=timeout)
