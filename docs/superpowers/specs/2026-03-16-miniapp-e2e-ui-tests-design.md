# Mini App UI E2E Tests — Design Spec

**Date:** 2026-03-16
**Status:** Approved

## Goal

Add Playwright-based UI E2E tests for the Telegram Mini App, covering registration (advertiser + blogger), order management, and navigation flows. Tests run against a live dev server (`make dev-up`) and are parametrized by locale (`ru`, `en`).

## Approach

**Full UI E2E via Playwright** — tests open the real mini app in a browser, with `window.Telegram.WebApp` mocked via `page.add_init_script()`. The mock includes a valid `initData` HMAC signature so the backend accepts requests normally.

No changes to production code. No new dependencies.

**Note:** The mini app SPA is served by `telegram_webhook_app.py` on port 9999 (same as the Telegram webhook). The HTML is at `/miniapp/app.html`, API at `/miniapp/api/*`.

## Infrastructure

### Env vars

| Variable | Required | Description |
|----------|----------|-------------|
| `E2E_MINIAPP_URL` | Yes | Base URL of running mini app (e.g. `http://45.130.145.27:9999`) |
| `E2E_BOT_TOKEN` | Yes | Bot token for signing `initData` |

Tests are skipped if `E2E_MINIAPP_URL` is not set.

### initData generation

`tests/e2e/miniapp_helpers.py` provides `generate_init_data(bot_token, user_id, username)`:

- Builds query string: `auth_date=<ts>&user={"id":<user_id>,"username":"<username>"}&hash=<hmac>`
- Signs with HMAC-SHA256 using `WebAppData` + bot_token (same algorithm as `miniapp/auth.py`)
- Returns raw query string ready for `Telegram.WebApp.initData`

### Telegram.WebApp mock

Injected via `page.add_init_script()` before page load:

```javascript
window.Telegram = {
  WebApp: {
    initData: "<generated_init_data>",
    initDataUnsafe: { user: { id: USER_ID, username: "test_user" } },
    ready: () => {},
    expand: () => {},
    close: () => {},
    openLink: (url) => window.open(url, '_blank'),
    themeParams: {},
    colorScheme: "light",
    MainButton: { show: ()=>{}, hide: ()=>{}, setText: ()=>{}, onClick: ()=>{} }
  }
};
```

### Fixtures (in `tests/e2e/conftest.py`)

- `miniapp_base_url` — reads `E2E_MINIAPP_URL`, skips if not set
- `bot_token` — reads `E2E_BOT_TOKEN`, skips if not set
- `miniapp_page(page, bot_token, user_id, username)` — returns Playwright page with injected Telegram.WebApp mock

### Locale parametrization

Tests are parametrized with `@pytest.mark.parametrize("locale", ["ru", "en"])`. The locale affects which country is selected (Russia for `ru`, Georgia for `en`), which in turn determines the locale returned by `/me` API.

## Test Scenarios

### File: `tests/e2e/test_miniapp_ui.py`

All tests marked with `@pytest.mark.e2e` and `@pytest.mark.timeout(60)`.

### Class: `TestMiniAppAdvertiser`

Tests use a fixed `user_id` per locale (e.g. `990000001` for ru, `990000002` for en).

**test_register_advertiser:**
1. Open mini app → loading screen → country select screen
2. Select country (Russia / Georgia depending on locale)
3. Role choice screen → click "Advertiser" button (`[data-role="advertiser"]`)
4. Fill form: `#adv-name`, `#adv-phone`, `#adv-brand`
5. Submit (`#btn-submit-advertiser`) → agreements screen (`#screen-agreements-advertiser.active`)
6. Check agreement checkbox (`#adv-agree-checkbox`) → click confirm (`#btn-confirm-adv-agreement`)
7. Assert: advertiser dashboard visible (`#screen-advertiser-dashboard.active`)

**test_create_order:**
1. Open mini app (same user_id, already registered)
2. Assert: advertiser dashboard
3. Click "Create order" (`#btn-show-create-order`)
4. Fill: `#ord-link`, `#ord-offer`, `#ord-price`
5. Submit → assert success message in `#ord-success`

**test_view_orders:**
1. On dashboard, click "My orders" (`#btn-show-orders-list`)
2. Assert: `#orders-list` has at least one `li` element
3. Click on order → assert order detail screen (`#screen-order-detail.active`)
4. Assert: fields populated

### Class: `TestMiniAppBlogger`

Uses different `user_id` per locale (e.g. `990000011` for ru, `990000012` for en).

**test_register_blogger:**
1. Open mini app → country select → select country
2. Role choice → click "Creator" (`[data-role="blogger"]`)
3. Fill form:
   - `#blg-name` — `fill()`
   - `#blg-instagram` — `fill()` (username only, prefix is static)
   - `#blg-birth-day` — `select_option()` (select element)
   - `#blg-birth-month` — `select_option()` (select element)
   - `#blg-birth-year` — `select_option()` (select element)
   - `#blg-topics` — `fill()`
   - `#blg-audience-geo` — `fill()`
   - `#blg-price` — `fill()`
4. City: click `#btn-blogger-city-map` to show map block, type in `#blg-city-search`, click `#btn-blogger-city-search`, wait for `#blg-city` value to be non-empty
5. Submit (`#btn-submit-blogger`) → agreements screen (`#screen-agreements-blogger.active`)
6. Check checkbox (`#blg-agree-checkbox`) → click confirm (`#btn-confirm-blg-agreement`)
7. Assert: blogger dashboard visible (`#screen-blogger-dashboard.active`)

### Class: `TestMiniAppNavigation`

Uses user_id that has both profiles (advertiser from TestMiniAppAdvertiser).

**test_switch_role:**
1. Open mini app → advertiser dashboard
2. Click "Switch role" (`#btn-change-role-from-adv`)
3. Assert: role choice screen
4. Click "Creator" → assert blogger registration or dashboard

## Test Ordering

The existing `pytest_collection_modifyitems` in `conftest.py` already orders `e2e_telegram` tests. Extend the same function to also order miniapp tests:
1. `TestMiniAppAdvertiser` runs first (creates advertiser)
2. `TestMiniAppBlogger` runs second (creates blogger)
3. `TestMiniAppNavigation` runs last (uses existing profiles)

Ordering logic: assign priority by class name prefix matching, sort miniapp tests among themselves without affecting existing e2e_telegram ordering.

## Test Data Cleanup

Tests use hardcoded `user_id` values (e.g. `990000001`–`990000012`). To support re-runs:
- Add a `clean_miniapp_e2e_users` fixture (session-scoped, autouse for miniapp tests) that deletes test users from DB before the test session starts
- Uses `E2E_DATABASE_URL` env var (same pattern as existing `pytest_sessionstart` cleanup for telegram e2e)
- If `E2E_DATABASE_URL` is not set, cleanup is skipped (tests may fail on re-run if users already exist)

## Selectors Strategy

All selectors use element `id` attributes — the HTML has unique ids on all key elements:
- Screens: `#screen-country-select`, `#screen-role-choice`, `#screen-register-advertiser`, etc.
- Active screen detection: `#screen-xxx.active` (CSS class toggle)
- Form fields: `#adv-name`, `#adv-phone`, `#blg-instagram`, etc.
- Buttons: `#btn-submit-advertiser`, `#btn-show-create-order`, `[data-role="advertiser"]`, etc.
- Errors/success: `#adv-error`, `#ord-success`, etc.

## Timeouts

- Per-test: `@pytest.mark.timeout(60)`
- Screen waits: `page.wait_for_selector("#screen-xxx.active", timeout=10000)`
- API response waits: implicit via screen transitions

## File Structure

```
tests/e2e/
├── conftest.py              # + miniapp fixtures
├── miniapp_helpers.py       # NEW: initData generation, screen wait utils
├── test_miniapp_ui.py       # NEW: all miniapp UI tests
├── test_admin_ui.py         # existing
├── test_telegram_bot_e2e.py # existing
└── telegram_client.py       # existing
```

## Run Command

```bash
E2E_MINIAPP_URL=http://45.130.145.27:9999 \
E2E_BOT_TOKEN=<token> \
uv run pytest tests/e2e/test_miniapp_ui.py -v -m e2e
```

Optional Makefile target:
```makefile
e2e-miniapp:
	uv run pytest tests/e2e/test_miniapp_ui.py -v -m e2e
```
