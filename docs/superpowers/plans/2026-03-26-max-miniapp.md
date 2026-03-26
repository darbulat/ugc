# Max Mini App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mini app support for Max messenger — same registration/orders/manager functionality as Telegram, single codebase with platform parameter.

**Architecture:** Single HTML + shared API endpoints serve both platforms. A `platform` query/body parameter selects the correct bridge script (client-side) and bot token for HMAC validation (server-side). Max webhook app mounts the same miniapp router.

**Tech Stack:** FastAPI, Pydantic, HMAC-SHA256, JavaScript (bridge loading), Max Platform API (`open_app` button type).

---

### Task 1: Add `open_app` button support in Max client

**Files:**
- Modify: `src/ugc_bot/infrastructure/messenger/max/client.py:48-69`
- Test: `tests/unit/infrastructure/messenger/max/test_client.py`

- [ ] **Step 1: Write the failing test**

```python
# In tests/unit/infrastructure/messenger/max/test_client.py

def test_build_inline_keyboard_open_app_button():
    """web_app_url button produces open_app type."""
    from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
    from ugc_bot.infrastructure.messenger.max.client import _build_inline_keyboard

    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Open App", web_app_url="https://example.com/app")]],
    )
    result = _build_inline_keyboard(kb)
    buttons = result["payload"]["buttons"]
    assert len(buttons) == 1
    assert len(buttons[0]) == 1
    btn = buttons[0][0]
    assert btn["type"] == "open_app"
    assert btn["text"] == "Open App"
    assert btn["url"] == "https://example.com/app"
    assert "payload" not in btn
    assert "callback_data" not in btn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_client.py::test_build_inline_keyboard_open_app_button -v`
Expected: FAIL — button gets `type: "callback"` instead of `"open_app"`

- [ ] **Step 3: Add `web_app_url` handling to `_build_inline_keyboard`**

In `src/ugc_bot/infrastructure/messenger/max/client.py`, modify `_build_inline_keyboard`:

```python
def _build_inline_keyboard(keyboard: Keyboard) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    for row in keyboard.rows:
        max_row: list[dict[str, Any]] = []
        for btn in row:
            max_btn: dict[str, Any] = {
                "text": btn.text,
                "type": "callback",
            }
            if btn.web_app_url:
                max_btn["type"] = "open_app"
                max_btn["url"] = btn.web_app_url
            elif btn.callback_data:
                max_btn["type"] = "callback"
                max_btn["payload"] = btn.callback_data
            elif btn.url:
                max_btn["type"] = "link"
                max_btn["url"] = btn.url
            elif btn.request_contact:
                max_btn["type"] = "request_contact"
            elif btn.request_location:
                max_btn["type"] = "request_geo_location"
            max_row.append(max_btn)
        rows.append(max_row)
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_client.py::test_build_inline_keyboard_open_app_button -v`
Expected: PASS

- [ ] **Step 5: Run all Max client tests**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_client.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/infrastructure/messenger/max/client.py tests/unit/infrastructure/messenger/max/test_client.py
git commit -m "feat: add open_app button type support in Max client"
```

---

### Task 2: Make `auth.py` platform-aware

**Files:**
- Modify: `src/ugc_bot/miniapp/auth.py`
- Test: `tests/unit/test_miniapp_auth.py`

The existing `validate_init_data_and_get_telegram_user_id` uses the same HMAC-SHA256 algorithm that Max uses. We only need a thin wrapper that selects the correct bot token by platform. The existing functions remain unchanged (backward-compatible).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_miniapp_auth.py`:

```python
from ugc_bot.miniapp.auth import validate_init_data_for_platform


class TestValidateInitDataForPlatform:
    """Tests for platform-aware initData validation."""

    def test_telegram_platform_uses_telegram_token(self) -> None:
        """platform='telegram' validates with telegram bot token."""
        tg_token = "tg_token_123"
        max_token = "max_token_456"
        init_data = _make_valid_init_data(tg_token, 111)
        result = validate_init_data_for_platform(
            init_data, platform="telegram",
            telegram_bot_token=tg_token, max_bot_token=max_token,
        )
        assert result == "111"

    def test_max_platform_uses_max_token(self) -> None:
        """platform='max' validates with Max bot token."""
        tg_token = "tg_token_123"
        max_token = "max_token_456"
        init_data = _make_valid_init_data(max_token, 222)
        result = validate_init_data_for_platform(
            init_data, platform="max",
            telegram_bot_token=tg_token, max_bot_token=max_token,
        )
        assert result == "222"

    def test_unknown_platform_raises(self) -> None:
        """Unknown platform raises ValueError."""
        with pytest.raises(ValueError, match="Unknown platform"):
            validate_init_data_for_platform(
                "any", platform="vk",
                telegram_bot_token="t", max_bot_token="m",
            )

    def test_max_with_telegram_token_fails(self) -> None:
        """Max initData validated with Telegram token fails."""
        max_token = "max_token_789"
        init_data = _make_valid_init_data(max_token, 333)
        with pytest.raises(ValueError, match="Invalid init_data signature"):
            validate_init_data_for_platform(
                init_data, platform="telegram",
                telegram_bot_token="wrong_token", max_bot_token=max_token,
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_miniapp_auth.py::TestValidateInitDataForPlatform -v`
Expected: FAIL — `ImportError: cannot import name 'validate_init_data_for_platform'`

- [ ] **Step 3: Implement `validate_init_data_for_platform`**

Add to `src/ugc_bot/miniapp/auth.py`:

```python
def validate_init_data_for_platform(
    init_data: str,
    *,
    platform: str,
    telegram_bot_token: str,
    max_bot_token: str,
) -> str:
    """Validate initData using the correct bot token for the given platform.

    Returns:
        User id as string (external_id).

    Raises:
        ValueError: If platform is unknown or validation fails.
    """
    if platform == "telegram":
        bot_token = telegram_bot_token
    elif platform == "max":
        bot_token = max_bot_token
    else:
        raise ValueError(f"Unknown platform: {platform!r}")
    return validate_init_data_and_get_telegram_user_id(init_data, bot_token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_miniapp_auth.py::TestValidateInitDataForPlatform -v`
Expected: PASS

- [ ] **Step 5: Run all auth tests**

Run: `uv run pytest tests/unit/test_miniapp_auth.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/miniapp/auth.py tests/unit/test_miniapp_auth.py
git commit -m "feat: add platform-aware initData validation"
```

---

### Task 3: Add `platform` field to API request models

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py` (request models only)

All request models that contain `init_data` need a `platform` field with default `"telegram"` for backward compatibility.

- [ ] **Step 1: Update `InitDataBody` base model**

In `src/ugc_bot/miniapp/api.py`, change:

```python
class InitDataBody(BaseModel):
    """Body that includes initData for auth (Telegram or Max)."""

    init_data: str = Field(..., description="WebApp.initData string")
    platform: str = Field(
        default="telegram", description="Platform: 'telegram' or 'max'"
    )
```

- [ ] **Step 2: Add `platform` to all other request models with `init_data`**

Add this field to each of these models (after the `init_data` field):

```python
    platform: str = "telegram"
```

Models to update:
- `RegisterAdvertiserRequest` (line 120)
- `RegisterBloggerRequest` (line 132)
- `CreateOrderRequest` (line 167)
- `GetOrderRequest` (line 201)
- `UpdateOrderRequest` (line 226)
- `ManagerOrdersRequest` (line 242)
- `ManagerCreatorsRequest` (line 257)
- `ConfirmAgreementRequest` (around line 288)
- `SetCountryRequest` (around line 304)
- `OrdersListRequest` (around line 311)
- `ManagerCreatorDetailRequest` (around line 1188)
- `ManagerUgcVideoRequest` (around line 1194)
- `ManagerCreatorActionRequest` (around line 1210)
- `ManagerFeedbackRequest` (around line 1512)

- [ ] **Step 3: Run existing tests to verify backward compatibility**

Run: `uv run pytest tests/unit/test_miniapp_auth.py tests/unit/test_miniapp_helpers.py tests/unit/test_miniapp_api_helpers.py tests/unit/test_miniapp_manager_endpoints.py -v`
Expected: All pass (default `platform="telegram"` preserves existing behavior)

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/miniapp/api.py
git commit -m "feat: add platform field to all miniapp request models"
```

---

### Task 4: Make API helper functions platform-aware

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py` (helper functions)
- Test: `tests/unit/test_miniapp_api_helpers.py`

The key helper functions need to accept `platform` and use the correct token/messenger type.

- [ ] **Step 1: Write failing test for platform-aware `_get_external_id`**

Add to `tests/unit/test_miniapp_api_helpers.py`:

```python
def test_get_external_id_max_platform(monkeypatch):
    """_get_external_id with platform='max' uses Max bot token."""
    from ugc_bot.miniapp import api as api_module

    called_with = {}

    def fake_validate(init_data, *, platform, telegram_bot_token, max_bot_token):
        called_with.update(
            platform=platform,
            telegram_bot_token=telegram_bot_token,
            max_bot_token=max_bot_token,
        )
        return "12345"

    monkeypatch.setattr(api_module, "validate_init_data_for_platform", fake_validate)

    mock_request = _make_mock_request()
    # Add max_bot token to config mock
    mock_request.app.state.config.max_bot = type("Obj", (), {"token": "max_tk"})()

    result = api_module._get_external_id(mock_request, "init", platform="max")
    assert result == "12345"
    assert called_with["platform"] == "max"
    assert called_with["max_bot_token"] == "max_tk"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_miniapp_api_helpers.py::test_get_external_id_max_platform -v`
Expected: FAIL — `_get_external_id` doesn't exist yet

- [ ] **Step 3: Refactor helper functions**

Replace `_get_telegram_user_id`, `_get_telegram_username_from_init_data`, `_ensure_user_and_get_id`, and `_get_user_locale` with platform-aware versions:

```python
from ugc_bot.miniapp.auth import (
    get_telegram_user_id_and_username,
    validate_init_data_and_get_telegram_user_id,
    validate_init_data_for_platform,
)


def _get_bot_tokens(request: Request) -> tuple[str, str]:
    """Return (telegram_bot_token, max_bot_token) from config."""
    config = request.app.state.config
    tg_token = config.bot.bot_token
    max_bot = getattr(config, "max_bot", None)
    max_token = max_bot.token if max_bot else ""
    return tg_token, max_token


def _get_external_id(
    request: Request, init_data: str, *, platform: str = "telegram"
) -> str:
    """Validate init_data and return external user id. Raises HTTPException."""
    tg_token, max_token = _get_bot_tokens(request)
    try:
        return validate_init_data_for_platform(
            init_data,
            platform=platform,
            telegram_bot_token=tg_token,
            max_bot_token=max_token,
        )
    except ValueError as e:
        logger.warning("init_data validation failed: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e


def _get_username_from_init_data(
    request: Request, init_data: str, *, platform: str = "telegram"
) -> str | None:
    """Return username from validated init_data, or None."""
    tg_token, max_token = _get_bot_tokens(request)
    token = tg_token if platform == "telegram" else max_token
    try:
        _, username = get_telegram_user_id_and_username(init_data, token)
        return username
    except ValueError:
        return None


def _get_messenger_type(platform: str) -> MessengerType:
    """Map platform string to MessengerType enum."""
    if platform == "max":
        return MessengerType.MAX
    return MessengerType.TELEGRAM


async def _get_user_locale(
    request: Request, external_id: str, *, platform: str = "telegram"
) -> str:
    """Resolve locale for user by external_id via user.language."""
    config = request.app.state.config
    default: str = config.market.default_locale
    dispatcher = request.app.state.dispatcher
    user_role_service = dispatcher.get("user_role_service")
    if not user_role_service:
        return default
    try:
        user = await user_role_service.get_user(
            external_id, _get_messenger_type(platform)
        )
    except Exception:
        logger.warning("Failed to resolve locale for user %s", external_id)
        return default
    if not user or not user.language:
        return default
    return user.language


async def _ensure_user_and_get_id(
    request: Request, init_data: str, *, platform: str = "telegram"
) -> UUID:
    """Ensure user exists (set_user), return internal user_id."""
    external_id = _get_external_id(request, init_data, platform=platform)
    messenger_type = _get_messenger_type(platform)
    dispatcher = request.app.state.dispatcher
    user_role_service = dispatcher["user_role_service"]
    user = await user_role_service.get_user(
        external_id=external_id, messenger_type=messenger_type
    )
    if user is None:
        username_from_init = _get_username_from_init_data(
            request, init_data, platform=platform
        )
        try:
            await user_role_service.set_user(
                external_id=external_id,
                messenger_type=messenger_type,
                username=f"user_{external_id}",
                role_chosen=False,
                telegram_username=username_from_init,
            )
        except Exception:
            logger.debug(
                "set_user race for %s (probably concurrent request)",
                external_id,
            )
        user = await user_role_service.get_user(
            external_id=external_id, messenger_type=messenger_type
        )
        if user is None:
            raise HTTPException(status_code=500, detail="Failed to create user")

        # Auto-set country for Max users (Russia-only)
        if platform == "max" and user.country is None:
            try:
                await user_role_service.set_country(
                    external_id=external_id,
                    messenger_type=messenger_type,
                    country_code="RU",
                )
            except Exception:
                logger.debug("Failed to auto-set country for Max user %s", external_id)

    return user.id
```

Keep old function names as thin wrappers for any remaining callers:

```python
# Backward-compatible aliases (used in some call sites)
def _get_telegram_user_id(request: Request, init_data: str) -> str:
    return _get_external_id(request, init_data, platform="telegram")


def _get_telegram_username_from_init_data(
    request: Request, init_data: str
) -> str | None:
    return _get_username_from_init_data(request, init_data, platform="telegram")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_miniapp_api_helpers.py::test_get_external_id_max_platform -v`
Expected: PASS

- [ ] **Step 5: Run all miniapp tests**

Run: `uv run pytest tests/unit/test_miniapp_auth.py tests/unit/test_miniapp_helpers.py tests/unit/test_miniapp_api_helpers.py tests/unit/test_miniapp_manager_endpoints.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/miniapp/api.py tests/unit/test_miniapp_api_helpers.py
git commit -m "feat: make miniapp API helpers platform-aware"
```

---

### Task 5: Update API endpoint handlers to pass `platform`

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py` (endpoint functions)

Every endpoint that calls `_ensure_user_and_get_id`, `_get_external_id` (formerly `_get_telegram_user_id`), `_get_username_from_init_data`, or `_get_user_locale` needs to pass `platform=body.platform`.

- [ ] **Step 1: Update all `_ensure_user_and_get_id` calls**

Change every call from:
```python
user_id = await _ensure_user_and_get_id(request, body.init_data)
```
to:
```python
user_id = await _ensure_user_and_get_id(request, body.init_data, platform=body.platform)
```

There are ~20 call sites. Update them all.

- [ ] **Step 2: Update all `_get_telegram_user_id` / `_get_external_id` calls**

Change calls like:
```python
external_id = _get_telegram_user_id(request, body.init_data)
```
to:
```python
external_id = _get_external_id(request, body.init_data, platform=body.platform)
```

- [ ] **Step 3: Update all `_get_user_locale` calls**

Change calls like:
```python
locale = await _get_user_locale(request, external_id)
```
to:
```python
locale = await _get_user_locale(request, external_id, platform=body.platform)
```

- [ ] **Step 4: Update all `_get_telegram_username_from_init_data` calls**

Change calls like:
```python
telegram_username = _get_telegram_username_from_init_data(request, body.init_data)
```
to:
```python
telegram_username = _get_username_from_init_data(request, body.init_data, platform=body.platform)
```

- [ ] **Step 5: Update `get_user_by_external` calls in `/api/me` handler**

The `/api/me` handler calls `profile_service.get_user_by_external` with hardcoded `MessengerType.TELEGRAM`. Change to:
```python
user = await profile_service.get_user_by_external(
    _get_external_id(request, body.init_data, platform=body.platform),
    _get_messenger_type(body.platform),
)
```

- [ ] **Step 6: Run existing tests**

Run: `uv run pytest tests/unit/test_miniapp_auth.py tests/unit/test_miniapp_helpers.py tests/unit/test_miniapp_api_helpers.py tests/unit/test_miniapp_manager_endpoints.py -v`
Expected: All pass (default `platform="telegram"` preserves behavior)

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/miniapp/api.py
git commit -m "feat: pass platform to all miniapp API endpoint handlers"
```

---

### Task 6: Mount miniapp in `max_webhook_app.py`

**Files:**
- Modify: `src/ugc_bot/max_webhook_app.py`
- Test: `tests/unit/test_max_webhook_app.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_max_webhook_app.py`:

```python
@pytest.mark.anyio
async def test_miniapp_api_routes_mounted(max_app_client):
    """Miniapp API routes are accessible under /miniapp/api prefix."""
    # The /miniapp/api/config endpoint should exist (returns 401 without init_data)
    response = await max_app_client.post("/miniapp/api/config", json={})
    # 422 = validation error (missing init_data), not 404 = route exists
    assert response.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_max_webhook_app.py::test_miniapp_api_routes_mounted -v`
Expected: FAIL — returns 404 (route not found)

- [ ] **Step 3: Add miniapp router and static mount to `max_webhook_app.py`**

Add imports and mount after `app = FastAPI(...)`:

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from ugc_bot.miniapp.api import router as miniapp_api_router

app = FastAPI(lifespan=_lifespan)

app.include_router(miniapp_api_router, prefix="/miniapp")

_miniapp_dir = Path(__file__).resolve().parent / "miniapp"
if _miniapp_dir.is_dir():
    app.mount("/miniapp", StaticFiles(directory=str(_miniapp_dir)), name="miniapp")
```

Also in `_lifespan`, set `app.state.dispatcher` so miniapp API helpers can access services:

```python
    # Make bot_services accessible as dispatcher (for miniapp API compatibility)
    app.state.dispatcher = bot_services
```

Add this line after `app.state.bot_services = bot_services` (line 88).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_max_webhook_app.py::test_miniapp_api_routes_mounted -v`
Expected: PASS

- [ ] **Step 5: Run all Max webhook tests**

Run: `uv run pytest tests/unit/test_max_webhook_app.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/max_webhook_app.py tests/unit/test_max_webhook_app.py
git commit -m "feat: mount miniapp API and static files in Max webhook app"
```

---

### Task 7: Add `/app` command to Max bot handlers

**Files:**
- Modify: `src/ugc_bot/bot/max/handlers/start.py`
- Modify: `src/ugc_bot/bot/telegram/handlers/keyboards.py`
- Test: `tests/unit/bot/max/test_start_handlers.py` (or existing test file)

- [ ] **Step 1: Write the failing test for keyboard builder**

Add to the appropriate test file:

```python
def test_miniapp_open_inline_keyboard_with_platform():
    """miniapp_open_inline_keyboard with platform appends query param."""
    from ugc_bot.bot.telegram.handlers.keyboards import miniapp_open_inline_keyboard

    kb = miniapp_open_inline_keyboard("https://bot.example.com", platform="max")
    assert kb.rows
    btn = kb.rows[0][0]
    assert btn.web_app_url == "https://bot.example.com/miniapp/app.html?platform=max"


def test_miniapp_open_inline_keyboard_default_platform():
    """miniapp_open_inline_keyboard without platform keeps URL as-is (backward compat)."""
    from ugc_bot.bot.telegram.handlers.keyboards import miniapp_open_inline_keyboard

    kb = miniapp_open_inline_keyboard("https://bot.example.com")
    btn = kb.rows[0][0]
    assert btn.web_app_url == "https://bot.example.com/miniapp/app.html"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest <test_file>::test_miniapp_open_inline_keyboard_with_platform -v`
Expected: FAIL — `miniapp_open_inline_keyboard` doesn't accept `platform` parameter

- [ ] **Step 3: Update `miniapp_open_inline_keyboard` in keyboards.py**

```python
def miniapp_open_inline_keyboard(
    miniapp_url: str, *, platform: str = "",
) -> Keyboard:
    """Inline keyboard with single button to open Mini App."""
    if not (miniapp_url or miniapp_url.strip()):
        return Keyboard(kind=KeyboardKind.INLINE, rows=[])
    url = miniapp_url.strip().rstrip("/") + "/miniapp/app.html"
    if platform:
        url += f"?platform={platform}"
    return Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=MINIAPP_OPEN_BUTTON_TEXT,
                    web_app_url=url,
                )
            ]
        ],
    )
```

- [ ] **Step 4: Run keyboard tests to verify they pass**

Expected: PASS

- [ ] **Step 5: Add `/app` handler to Max start.py**

Add to `src/ugc_bot/bot/max/handlers/start.py`:

```python
from ugc_bot.bot.telegram.handlers.keyboards import miniapp_open_inline_keyboard


@router.message(lambda m: bool(m.text and m.text.startswith("/app")))
async def app_miniapp_command(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /app — send button to open Mini App."""
    messenger_client = deps["messenger_client"]
    config = deps["config"]

    base_url = config.max_bot.webhook_url if config.max_bot else ""
    if not base_url:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text="Mini App временно недоступен.",
        )
        return

    keyboard = miniapp_open_inline_keyboard(base_url, platform="max")
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text="Откройте приложение для регистрации и работы с заказами:",
        keyboard=keyboard,
    )
```

- [ ] **Step 6: Run all start handler tests**

Run: `uv run pytest tests/unit/bot/max/ -v`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/bot/telegram/handlers/keyboards.py src/ugc_bot/bot/max/handlers/start.py
git commit -m "feat: add /app command for Max and platform param to keyboard builder"
```

---

### Task 8: Update `app.html` for multi-platform bridge loading

**Files:**
- Modify: `src/ugc_bot/miniapp/app.html`

- [ ] **Step 1: Replace static Telegram bridge script with dynamic loader**

Find the existing `<script src="https://telegram.org/js/telegram-web-app.js">` tag in the `<head>` section and replace it with dynamic loading:

```html
<script>
(function() {
    var params = new URLSearchParams(window.location.search);
    var platform = params.get('platform') || 'telegram';
    window.__miniapp_platform = platform;

    var script = document.createElement('script');
    if (platform === 'max') {
        script.src = 'https://st.max.ru/js/max-web-app.js';
    } else {
        script.src = 'https://telegram.org/js/telegram-web-app.js';
    }
    script.onload = function() {
        // Normalize: ensure window.WebApp is available regardless of platform
        if (!window.WebApp && window.Telegram && window.Telegram.WebApp) {
            window.WebApp = window.Telegram.WebApp;
        }
    };
    document.head.appendChild(script);
})();
</script>
```

- [ ] **Step 2: Update `initData` access throughout the file**

Find all places that access `Telegram.WebApp.initData` or `window.Telegram.WebApp` and update to also check `window.WebApp`:

```javascript
function getInitData() {
    if (window.Telegram && window.Telegram.WebApp) {
        return window.Telegram.WebApp.initData;
    }
    if (window.WebApp) {
        return window.WebApp.initData;
    }
    return '';
}
```

- [ ] **Step 3: Add `platform` to all API request bodies**

Find the function(s) that make API calls and ensure `platform` is included in every request body:

```javascript
function apiBody(extra) {
    var body = {
        init_data: getInitData(),
        platform: window.__miniapp_platform || 'telegram'
    };
    if (extra) {
        Object.keys(extra).forEach(function(k) { body[k] = extra[k]; });
    }
    return JSON.stringify(body);
}
```

Update all `fetch()` calls to use this helper (or add `platform` to existing request construction).

- [ ] **Step 4: Skip country selection for Max**

Find the initialization logic that shows the country selection screen and add a platform check:

```javascript
// After loading user data from /api/me
if (window.__miniapp_platform === 'max') {
    // Max is Russia-only: skip country selection, go directly to role choice
    showScreen('role-choice');
} else if (!userData.country) {
    showScreen('country-select');
} else {
    // ... existing logic
}
```

- [ ] **Step 5: Call `WebApp.ready()` for both platforms**

Ensure `WebApp.ready()` is called after initialization, for both Telegram and Max:

```javascript
function signalReady() {
    if (window.Telegram && window.Telegram.WebApp) {
        window.Telegram.WebApp.ready();
    } else if (window.WebApp) {
        window.WebApp.ready();
    }
}
```

- [ ] **Step 6: Verify in browser**

Open `app.html?platform=max` locally and check:
- No JS errors in console
- Bridge script loads from `st.max.ru`
- Country selection screen is skipped

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/miniapp/app.html
git commit -m "feat: add multi-platform bridge loading and Max support to app.html"
```

---

### Task 9: Run full test suite and fix coverage

**Files:**
- Various test files as needed

- [ ] **Step 1: Run make fix**

Run: `make fix`
Expected: format + lint + typecheck + coverage pass. If any fail, fix issues.

- [ ] **Step 2: Run full coverage check**

Run: `make coverage`
Expected: >= 98% coverage. If below, add tests for uncovered lines in the new code.

- [ ] **Step 3: Add any missing tests for coverage**

If coverage is below 98%, identify uncovered lines and write targeted tests. Likely candidates:
- `_get_messenger_type("max")` branch
- `_ensure_user_and_get_id` with `platform="max"` (auto-set country=RU)
- `_get_external_id` with Max token
- `app_miniapp_command` in Max start handlers
- Empty `base_url` branch in Max `/app` handler

- [ ] **Step 4: Commit coverage fixes**

```bash
git add -A
git commit -m "test: add tests to maintain 98% coverage for Max miniapp"
```

---

### Task 10: Final integration check

- [ ] **Step 1: Run `make all`**

Run: `make all`
Expected: format-check + lint + typecheck + coverage all pass.

- [ ] **Step 2: Verify Max webhook app starts**

Check that `max_webhook_app.py` can import and initialize without errors:
```bash
uv run python -c "from ugc_bot.max_webhook_app import app; print('OK')"
```

- [ ] **Step 3: Final commit if needed**

Only if there are remaining uncommitted changes:
```bash
git add -A
git commit -m "chore: final cleanup for Max miniapp support"
```
