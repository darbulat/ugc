# Mini App UI E2E Tests — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Playwright-based UI E2E tests for the Telegram Mini App covering registration, orders, and navigation flows.

**Architecture:** Tests run against a live dev server (`E2E_MINIAPP_URL`). `window.Telegram.WebApp` is mocked via `page.add_init_script()` with a valid HMAC-signed `initData`. Tests are parametrized by locale (`ru`, `en`).

**Tech Stack:** Playwright (pytest-playwright), HMAC-SHA256 for initData signing.

**Spec:** `docs/superpowers/specs/2026-03-16-miniapp-e2e-ui-tests-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `tests/e2e/miniapp_helpers.py` | Create | `generate_init_data()`, `build_telegram_mock_script()`, `wait_for_screen()` |
| `tests/e2e/conftest.py` | Modify | Add miniapp fixtures, extend `pytest_collection_modifyitems` |
| `tests/e2e/test_miniapp_ui.py` | Create | All miniapp UI test classes |
| `Makefile` | Modify | Add `e2e-miniapp` target |

---

## Chunk 1: Helpers and Fixtures

### Task 1: Create miniapp_helpers.py

**Files:**
- Create: `tests/e2e/miniapp_helpers.py`

- [ ] **Step 1: Write tests for `generate_init_data`**

Create `tests/unit/test_miniapp_helpers.py`:

```python
"""Tests for miniapp e2e helpers."""

from ugc_bot.miniapp.auth import validate_init_data_and_get_telegram_user_id


def test_generate_init_data_produces_valid_signature():
    from tests.e2e.miniapp_helpers import generate_init_data

    bot_token = "123456:ABC-DEF"
    user_id = 990000001
    username = "test_user"

    init_data = generate_init_data(bot_token, user_id, username)

    # Must pass the real validation from auth.py
    result = validate_init_data_and_get_telegram_user_id(init_data, bot_token)
    assert result == str(user_id)


def test_generate_init_data_contains_username():
    from tests.e2e.miniapp_helpers import generate_init_data

    init_data = generate_init_data("tok:en", 123, "alice")
    assert "alice" in init_data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_miniapp_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement miniapp_helpers.py**

Create `tests/e2e/miniapp_helpers.py`:

```python
"""Helpers for Mini App E2E tests: initData generation and Playwright utilities."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from playwright.sync_api import Page

_WEBAPP_DATA_KEY = "WebAppData"


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

    # HMAC: secret = HMAC(WebAppData, bot_token), hash = HMAC(secret, data_check_string)
    secret_key = hmac.new(
        _WEBAPP_DATA_KEY.encode(), bot_token.encode(), hashlib.sha256
    ).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    params["hash"] = computed_hash
    return urlencode(params)


def build_telegram_mock_script(init_data: str, user_id: int, username: str) -> str:
    """Return JS code that mocks window.Telegram.WebApp for Playwright injection."""
    return f"""
    window.Telegram = {{
        WebApp: {{
            initData: {json.dumps(init_data)},
            initDataUnsafe: {{ user: {{ id: {user_id}, username: {json.dumps(username)} }} }},
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_miniapp_helpers.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add tests/e2e/miniapp_helpers.py tests/unit/test_miniapp_helpers.py
git commit -m "feat: add miniapp e2e helpers (initData generation, Playwright utils)"
```

---

### Task 2: Add miniapp fixtures to conftest.py

**Files:**
- Modify: `tests/e2e/conftest.py`

- [ ] **Step 1: Add miniapp fixtures**

Add to the end of `tests/e2e/conftest.py`:

```python
# --- Mini App E2E fixtures ---

MINIAPP_TEST_USER_IDS = {
    "advertiser": {"ru": 990000001, "en": 990000002},
    "blogger": {"ru": 990000011, "en": 990000012},
}


def _miniapp_base_url() -> str | None:
    return os.environ.get("E2E_MINIAPP_URL", "").strip() or None


def _miniapp_bot_token() -> str | None:
    return os.environ.get("E2E_BOT_TOKEN", "").strip() or None


@pytest.fixture(scope="session")
def miniapp_base_url() -> str:
    """Base URL for Mini App. Skips if E2E_MINIAPP_URL not set."""
    url = _miniapp_base_url()
    if not url:
        pytest.skip("E2E_MINIAPP_URL not set")
    return url


@pytest.fixture(scope="session")
def miniapp_bot_token() -> str:
    """Bot token for signing initData. Skips if E2E_BOT_TOKEN not set."""
    token = _miniapp_bot_token()
    if not token:
        pytest.skip("E2E_BOT_TOKEN not set")
    return token
```

- [ ] **Step 2: Extend `pytest_collection_modifyitems` for miniapp test ordering**

Replace the existing `pytest_collection_modifyitems` function in `tests/e2e/conftest.py` with:

```python
_MINIAPP_CLASS_ORDER = {
    "TestMiniAppAdvertiser": 0,
    "TestMiniAppBlogger": 1,
    "TestMiniAppNavigation": 2,
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Order e2e_telegram and miniapp tests."""
    # --- Telegram e2e ordering (existing) ---
    telegram_items = [
        (i, item)
        for i, item in enumerate(items)
        if item.get_closest_marker("e2e_telegram") is not None
    ]
    if telegram_items:

        def order_key(entry: tuple[int, pytest.Item]) -> tuple[int, int]:
            idx, item = entry
            nodeid = item.nodeid
            if "profile_update" in nodeid:
                return (1, idx)
            return (0, idx)

        telegram_items.sort(key=order_key)
        reordered_ids = [item.nodeid for _, item in telegram_items]
        id_to_item = {item.nodeid: item for item in items}
        remaining = [item for item in items if item.nodeid not in reordered_ids]
        items[:] = remaining + [id_to_item[nid] for nid in reordered_ids]

    # --- Miniapp e2e ordering ---
    miniapp_items = []
    for i, item in enumerate(items):
        cls = getattr(item, "cls", None)
        if cls and cls.__name__ in _MINIAPP_CLASS_ORDER:
            miniapp_items.append((i, item))
    if not miniapp_items:
        return

    def miniapp_order_key(entry: tuple[int, pytest.Item]) -> tuple[int, int]:
        idx, item = entry
        cls = getattr(item, "cls", None)
        cls_order = _MINIAPP_CLASS_ORDER.get(cls.__name__, 99) if cls else 99
        return (cls_order, idx)

    miniapp_items.sort(key=miniapp_order_key)
    reordered_ids = [item.nodeid for _, item in miniapp_items]
    id_to_item = {item.nodeid: item for item in items}
    remaining = [item for item in items if item.nodeid not in reordered_ids]
    items[:] = remaining + [id_to_item[nid] for nid in reordered_ids]
```

- [ ] **Step 3: Run existing e2e tests to ensure no regressions in conftest**

Run: `uv run pytest tests/e2e/test_admin_ui.py --collect-only`
Expected: Tests collected successfully (existing fixtures still work).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/conftest.py
git commit -m "feat: add miniapp e2e fixtures and test ordering to conftest"
```

---

### Task 2.5: Add test data cleanup to conftest.py

**Files:**
- Modify: `tests/e2e/conftest.py`

- [ ] **Step 1: Add cleanup logic to `pytest_sessionstart`**

Extend the existing `pytest_sessionstart` in `tests/e2e/conftest.py` to also clean miniapp test users. Add after the existing telegram cleanup block:

```python
def pytest_sessionstart(session: pytest.Session) -> None:
    """Clean DB users before E2E tests when E2E_DATABASE_URL is set."""
    db_url = os.environ.get("E2E_DATABASE_URL")
    if not db_url:
        return

    # Existing telegram e2e cleanup
    try:
        items = session.items
    except Exception:
        items = []
    has_telegram = any(
        item.get_closest_marker("e2e_telegram") is not None for item in items
    )
    if has_telegram:
        root = Path(__file__).resolve().parent.parent.parent
        script = root / "scripts" / "clean_e2e_users.py"
        if script.exists():
            cmd = [sys.executable, str(script)]
            clean_telegram = os.environ.get("E2E_CLEAN_TELEGRAM", "").strip()
            if clean_telegram:
                cmd.extend(["--telegram", clean_telegram])
            subprocess.run(
                cmd, cwd=str(root), env=os.environ.copy(),
                check=False, capture_output=True,
            )

    # Miniapp e2e cleanup: delete test users by external_id
    miniapp_user_ids = []
    for role_ids in MINIAPP_TEST_USER_IDS.values():
        miniapp_user_ids.extend(str(uid) for uid in role_ids.values())
    if miniapp_user_ids:
        try:
            from sqlalchemy import text

            engine = create_engine(db_url)
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM users WHERE external_id = ANY(:ids)"),
                    {"ids": miniapp_user_ids},
                )
            engine.dispose()
        except Exception:
            pass  # Cleanup is best-effort
```

- [ ] **Step 2: Verify existing tests still collect**

Run: `uv run pytest tests/e2e/test_admin_ui.py --collect-only`
Expected: Tests collected successfully.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/conftest.py
git commit -m "feat: add miniapp e2e test data cleanup"
```

---

## Chunk 2: Advertiser Tests

### Task 3: Advertiser registration test

**Files:**
- Create: `tests/e2e/test_miniapp_ui.py`

- [ ] **Step 1: Create test file with advertiser registration test**

Create `tests/e2e/test_miniapp_ui.py`:

```python
"""E2E UI tests for Telegram Mini App."""

import os

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import MINIAPP_TEST_USER_IDS
from tests.e2e.miniapp_helpers import (
    build_telegram_mock_script,
    generate_init_data,
    wait_for_screen,
)

# Country buttons: text displayed in the country selector grid
_COUNTRY_FOR_LOCALE = {"ru": "Россия", "en": "Georgia"}


def _open_miniapp(
    page: Page, base_url: str, bot_token: str, user_id: int, username: str
) -> None:
    """Open mini app with mocked Telegram.WebApp."""
    init_data = generate_init_data(bot_token, user_id, username)
    script = build_telegram_mock_script(init_data, user_id, username)
    page.add_init_script(script=script)
    page.goto(f"{base_url}/miniapp/app.html")


def _select_country(page: Page, locale: str) -> None:
    """Select country in the country selector screen."""
    country_name = _COUNTRY_FOR_LOCALE[locale]
    wait_for_screen(page, "screen-country-select")
    page.locator(f"#country-grid .btn", has_text=country_name).click()


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppAdvertiser:
    """Advertiser flow: register → create order → view orders."""

    def test_register_advertiser(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        # Country selection
        _select_country(page, locale)

        # Role choice
        wait_for_screen(page, "screen-role-choice")
        page.locator('[data-role="advertiser"]').click()

        # Registration form
        wait_for_screen(page, "screen-register-advertiser")
        page.locator("#adv-name").fill("E2E Advertiser")
        page.locator("#adv-phone").fill("89001234567")
        page.locator("#adv-brand").fill("E2E Brand")
        page.locator("#btn-submit-advertiser").click()

        # Agreements
        wait_for_screen(page, "screen-agreements-advertiser")
        page.locator("#adv-agree-checkbox").check()
        page.locator("#btn-confirm-adv-agreement").click()

        # Dashboard
        wait_for_screen(page, "screen-advertiser-dashboard")
```

- [ ] **Step 2: Run the test (requires dev server)**

Run: `E2E_MINIAPP_URL=http://45.130.145.27:9999 E2E_BOT_TOKEN=<token> uv run pytest tests/e2e/test_miniapp_ui.py::TestMiniAppAdvertiser::test_register_advertiser -v`
Expected: PASS for both locale parametrizations.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_miniapp_ui.py
git commit -m "feat: add miniapp advertiser registration e2e test"
```

---

### Task 4: Create order and view orders tests

**Files:**
- Modify: `tests/e2e/test_miniapp_ui.py`

- [ ] **Step 1: Add create order test to TestMiniAppAdvertiser**

Add after `test_register_advertiser` in the same class:

```python
    def test_create_order(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        # Already registered → should land on dashboard
        wait_for_screen(page, "screen-advertiser-dashboard")

        # Open create order form
        page.locator("#btn-show-create-order").click()
        page.wait_for_selector("#block-create-order", state="visible")

        # Fill order form
        page.locator("#ord-link").fill("https://example.com/product")
        page.locator("#ord-offer").fill("E2E test offer text")
        page.locator("#ord-price").fill("5000")
        page.locator("#btn-submit-order").click()

        # Assert success
        page.wait_for_selector("#ord-success:not(:empty)", timeout=10000)
        success_text = page.locator("#ord-success").inner_text()
        assert success_text  # Non-empty success message

    def test_view_orders(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        wait_for_screen(page, "screen-advertiser-dashboard")

        # Open orders list
        page.locator("#btn-show-orders-list").click()
        page.wait_for_selector("#block-orders-list", state="visible")

        # Should have at least one order from test_create_order
        page.wait_for_selector("#orders-list li", timeout=10000)
        orders = page.locator("#orders-list li")
        assert orders.count() >= 1

        # Click first order to open detail
        orders.first.click()
        wait_for_screen(page, "screen-order-detail")

        # Verify fields are populated
        link_value = page.locator("#ord-detail-link").input_value()
        assert link_value  # Non-empty
```

- [ ] **Step 2: Run all advertiser tests**

Run: `E2E_MINIAPP_URL=http://45.130.145.27:9999 E2E_BOT_TOKEN=<token> uv run pytest tests/e2e/test_miniapp_ui.py::TestMiniAppAdvertiser -v`
Expected: PASS (3 tests × 2 locales = 6 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_miniapp_ui.py
git commit -m "feat: add miniapp order creation and viewing e2e tests"
```

---

## Chunk 3: Blogger and Navigation Tests

### Task 5: Blogger registration test

**Files:**
- Modify: `tests/e2e/test_miniapp_ui.py`

- [ ] **Step 1: Add TestMiniAppBlogger class**

Add after `TestMiniAppAdvertiser`:

```python
@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppBlogger:
    """Blogger (creator) registration flow."""

    def test_register_blogger(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        user_id = MINIAPP_TEST_USER_IDS["blogger"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_blg_{locale}")

        # Country selection
        _select_country(page, locale)

        # Role choice
        wait_for_screen(page, "screen-role-choice")
        page.locator('[data-role="blogger"]').click()

        # Registration form
        wait_for_screen(page, "screen-register-blogger")
        page.locator("#blg-name").fill("E2E Creator")
        page.locator("#blg-instagram").fill(f"e2e_creator_{locale}")
        page.locator("#blg-birth-day").select_option("15")
        page.locator("#blg-birth-month").select_option("6")
        page.locator("#blg-birth-year").select_option("1995")
        page.locator("#blg-topics").fill("beauty, fashion")
        page.locator("#blg-audience-geo").fill("Russia")
        page.locator("#blg-price").fill("10000")

        # City: use search instead of map click
        page.locator("#btn-blogger-city-map").click()
        page.wait_for_selector("#block-blogger-city-map", state="visible")
        page.locator("#blg-city-search").fill("Moscow" if locale == "en" else "Москва")
        page.locator("#btn-blogger-city-search").click()

        # Wait for city field to be populated by geocode API
        page.wait_for_function(
            "document.getElementById('blg-city').value.length > 0",
            timeout=15000,
        )

        # Submit
        page.locator("#btn-submit-blogger").click()

        # Agreements
        wait_for_screen(page, "screen-agreements-blogger")
        page.locator("#blg-agree-checkbox").check()
        page.locator("#btn-confirm-blg-agreement").click()

        # Blogger dashboard
        wait_for_screen(page, "screen-blogger-dashboard")
```

- [ ] **Step 2: Run blogger test**

Run: `E2E_MINIAPP_URL=http://45.130.145.27:9999 E2E_BOT_TOKEN=<token> uv run pytest tests/e2e/test_miniapp_ui.py::TestMiniAppBlogger -v`
Expected: PASS (1 test × 2 locales = 2 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_miniapp_ui.py
git commit -m "feat: add miniapp blogger registration e2e test"
```

---

### Task 6: Navigation / role switching test

**Files:**
- Modify: `tests/e2e/test_miniapp_ui.py`

- [ ] **Step 1: Add TestMiniAppNavigation class**

Add after `TestMiniAppBlogger`:

```python
@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("locale", ["ru", "en"])
class TestMiniAppNavigation:
    """Navigation and role switching (requires existing advertiser profile)."""

    def test_switch_role(
        self, page: Page, miniapp_base_url: str, miniapp_bot_token: str, locale: str
    ) -> None:
        # Use advertiser user_id (has profile from TestMiniAppAdvertiser)
        user_id = MINIAPP_TEST_USER_IDS["advertiser"][locale]
        _open_miniapp(page, miniapp_base_url, miniapp_bot_token, user_id, f"e2e_adv_{locale}")

        # Should land on advertiser dashboard (already registered)
        wait_for_screen(page, "screen-advertiser-dashboard")

        # Switch role
        page.locator("#btn-change-role-from-adv").click()
        wait_for_screen(page, "screen-role-choice")

        # Click blogger — should go to registration (no blogger profile for this user)
        page.locator('[data-role="blogger"]').click()
        wait_for_screen(page, "screen-register-blogger")
```

- [ ] **Step 2: Run navigation test**

Run: `E2E_MINIAPP_URL=http://45.130.145.27:9999 E2E_BOT_TOKEN=<token> uv run pytest tests/e2e/test_miniapp_ui.py::TestMiniAppNavigation -v`
Expected: PASS (1 test × 2 locales = 2 tests).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_miniapp_ui.py
git commit -m "feat: add miniapp navigation/role switching e2e test"
```

---

## Chunk 4: Makefile and Final Verification

### Task 7: Add Makefile target and run full suite

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add `e2e-miniapp` target to Makefile**

Add after existing e2e targets in `Makefile`:

```makefile
e2e-miniapp:  ## Mini App Playwright E2E tests (requires E2E_MINIAPP_URL, E2E_BOT_TOKEN)
	uv run pytest tests/e2e/test_miniapp_ui.py -v -m e2e
```

Also add `e2e-miniapp` to the `.PHONY` declaration on line 16 of the Makefile (append to the existing list).

- [ ] **Step 2: Run full miniapp e2e suite**

Run: `E2E_MINIAPP_URL=http://45.130.145.27:9999 E2E_BOT_TOKEN=<token> make e2e-miniapp`
Expected: 10 tests PASS (5 tests × 2 locales).

- [ ] **Step 3: Run `make all` to verify no regressions**

Run: `make all`
Expected: All format, lint, typecheck, and coverage checks pass. The new unit test for helpers is included in coverage. E2E tests are excluded from coverage (existing behavior).

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "feat: add e2e-miniapp Makefile target"
```
