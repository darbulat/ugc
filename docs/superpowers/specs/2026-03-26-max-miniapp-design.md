# Max Mini App — Design Spec

**Date:** 2026-03-26
**Status:** Approved

## Summary

Add mini app support for Max messenger with the same functionality as the existing Telegram mini app. Single HTML/API codebase serves both platforms, using a `platform` query parameter to select the correct bridge script and bot token for authentication.

## Architecture

Single mini app with multi-platform support:

```
app.html?platform=max       → loads max-web-app.js bridge
app.html?platform=telegram  → loads telegram-web-app.js bridge (default)

POST /miniapp/api/* { init_data, platform }
  → auth.py selects bot token by platform
  → validates initData with HMAC-SHA256 (same algorithm for both)
  → finds/creates user by telegram_id or max_id
  → shared business logic
```

### Files to modify

1. **`miniapp/auth.py`** — multi-platform token selection
2. **`miniapp/api.py`** — platform-aware user lookup/creation; `InitDataBody` gets `platform` field
3. **`miniapp/app.html`** — dynamic bridge script loading; skip country selection for Max
4. **`max_webhook_app.py`** — mount miniapp API router and static files
5. **`infrastructure/messenger/max/client.py`** — `open_app` button type support
6. **`bot/max/handlers/start.py`** — `/app` command handler

### What does NOT change

All API endpoints (`/api/orders`, `/api/register/*`, `/api/manager/*`), service-layer business logic, `location_picker.html`, `city_picker.html`.

## Authentication

Max and Telegram use identical HMAC-SHA256 validation with "WebAppData" key + bot_token. Only the token differs.

```python
def validate_init_data(init_data: str, platform: str, config: AppConfig) -> int:
    if platform == "max":
        bot_token = config.max_bot.token
    else:
        bot_token = config.bot.token
    return validate_init_data_and_get_user_id(init_data, bot_token)
```

### Request model

```python
class InitDataBody(BaseModel):
    init_data: str
    platform: str = "telegram"  # "telegram" | "max", backward-compatible
```

## User identification

```python
async def _ensure_user_and_get_id(request, init_data, platform):
    external_id = validate_init_data(init_data, platform, config)

    if platform == "max":
        user = await user_repo.get_by_max_id(str(external_id))
    else:
        user = await user_repo.get_by_telegram_id(external_id)

    if not user:
        user = await user_service.set_user(
            messenger_type=MessengerType.MAX if platform == "max" else MessengerType.TELEGRAM,
            max_id=str(external_id) if platform == "max" else None,
            telegram_id=external_id if platform == "telegram" else None,
            country_code="RU" if platform == "max" else None,
            ...
        )
    return user.id
```

For Max users: country defaults to RU, country selection screen is skipped.

## UI changes (app.html)

### Bridge script loading

```javascript
const params = new URLSearchParams(window.location.search);
const platform = params.get('platform') || 'telegram';

const script = document.createElement('script');
script.src = platform === 'max'
    ? 'https://st.max.ru/js/max-web-app.js'
    : 'https://telegram.org/js/telegram-web-app.js';
document.head.appendChild(script);
```

### API requests include platform

```javascript
function apiRequest(endpoint, body = {}) {
    return fetch(endpoint, {
        method: 'POST',
        body: JSON.stringify({
            init_data: window.Telegram?.WebApp?.initData || window.WebApp?.initData,
            platform: platform,
            ...body
        })
    });
}
```

### Country selection skipped for Max

```javascript
if (platform === 'max') {
    showScreen('role-choice');
} else {
    showScreen('country-select');
}
```

## Infrastructure changes

### Max client — open_app button

In `_build_inline_keyboard()`:

```python
if btn.web_app_url:
    raw = {"type": "open_app", "text": btn.text, "url": btn.web_app_url}
```

### max_webhook_app.py — mount miniapp

```python
app.include_router(miniapp_api_router, prefix="/miniapp")

_miniapp_dir = Path(__file__).resolve().parent / "miniapp"
if _miniapp_dir.is_dir():
    app.mount("/miniapp", StaticFiles(directory=str(_miniapp_dir)), name="miniapp")
```

### /app command in Max handlers

```python
async def app_command(incoming, deps):
    base_url = deps.config.max_bot.webhook_url
    keyboard = miniapp_open_inline_keyboard(base_url, platform="max")
    await deps.messenger.send_text(
        chat_id=incoming.chat_id,
        text="Откройте приложение:",
        keyboard=keyboard,
    )
```

### Shared keyboard builder

```python
def miniapp_open_inline_keyboard(base_url: str, platform: str = "telegram") -> Keyboard:
    url = base_url.rstrip("/") + f"/miniapp/app.html?platform={platform}"
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Открыть приложение", web_app_url=url)]]
    )
```

## Testing

### Unit tests (new)

1. **auth** — validate initData with Max token; invalid signature; unknown platform error
2. **api** — `_ensure_user_and_get_id` for Max: new user created with country=RU; existing user found by max_id; default platform="telegram" backward-compatible
3. **max client** — `_build_inline_keyboard` with `web_app_url` produces `{"type": "open_app"}`
4. **max webhook app** — miniapp routes accessible

### Existing tests unchanged

All Telegram miniapp tests continue to work (platform defaults to "telegram").

### E2E (manual)

- Open mini app in Max via `open_app` button
- Verify Max bridge loads, initData validates
- Complete blogger/advertiser registration
- Confirm country selection is skipped

## Scope exclusions

- No country selection screen for Max (defaults to RU)
- No changes to Telegram mini app behavior
- No new services or containers — reuses existing webhook apps
