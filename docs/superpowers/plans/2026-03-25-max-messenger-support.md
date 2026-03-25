# Max Messenger Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Max messenger as a second parallel messenger alongside Telegram with full handler parity (excluding payments and miniapp).

**Architecture:** Thin handlers + thick services. Max gets its own entry point (`max_webhook_app.py` on port 8003), infrastructure adapters (`infrastructure/messenger/max/`), and handler layer (`bot/max/`). Existing Telegram handlers are restructured under `bot/telegram/`. Services contain all business logic — handlers are thin wrappers.

**Tech Stack:** Python 3.12, FastAPI, aiohttp (Max API client), Redis (FSM for Max), PostgreSQL, aiogram (Telegram only)

**Spec:** `docs/superpowers/specs/2026-03-25-max-messenger-support-design.md`

---

## File Structure

### New files
- `src/ugc_bot/infrastructure/messenger/max/__init__.py`
- `src/ugc_bot/infrastructure/messenger/max/client.py` — MaxMessengerClient
- `src/ugc_bot/infrastructure/messenger/max/adapter.py` — MaxEventAdapter
- `src/ugc_bot/infrastructure/messenger/max/state.py` — MaxRedisStateStore
- `src/ugc_bot/bot/max/__init__.py`
- `src/ugc_bot/bot/max/router.py` — MaxRouter lightweight framework
- `src/ugc_bot/bot/max/handlers/__init__.py`
- `src/ugc_bot/bot/max/handlers/start.py` — /start handler for Max
- `src/ugc_bot/bot/max/middleware.py` — Locale, error handling for Max
- `src/ugc_bot/max_webhook_app.py` — Entry point (port 8003)
- `tests/unit/infrastructure/messenger/max/test_client.py`
- `tests/unit/infrastructure/messenger/max/test_adapter.py`
- `tests/unit/infrastructure/messenger/max/test_state.py`
- `tests/unit/bot/max/test_router.py`

### Modified files
- `src/ugc_bot/config.py` — Add `MaxBotConfig`
- `src/ugc_bot/app.py` — Update import paths from `bot.handlers.*` → `bot.telegram.handlers.*`
- `src/ugc_bot/telegram_webhook_app.py` — Update import paths
- `docker-compose.yml` — Add `max_bot` service
- `docker-compose.dev.yml` — Add `max_bot` service

### Restructured (move)
- `src/ugc_bot/bot/handlers/` → `src/ugc_bot/bot/telegram/handlers/` (includes `utils.py`, `keyboards.py`, `order_creation_states.py`)
- `src/ugc_bot/bot/middleware/` → `src/ugc_bot/bot/telegram/middleware/`
- `src/ugc_bot/bot/filters.py` → `src/ugc_bot/bot/telegram/filters.py`
- `src/ugc_bot/bot/validators.py` → `src/ugc_bot/bot/telegram/validators.py`

---

## Phase 1: Foundation (no user-facing changes)

### Task 1: Add MaxBotConfig to config.py

**Files:**
- Modify: `src/ugc_bot/config.py`
- Test: `tests/unit/test_config_max.py`

- [ ] **Step 1: Write test for MaxBotConfig**

```python
# tests/unit/test_config_max.py
import os
import pytest
from ugc_bot.config import MaxBotConfig


def test_max_bot_config_from_env(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", "test-token-123")
    monkeypatch.setenv("MAX_WEBHOOK_URL", "https://example.com/webhook/max")
    config = MaxBotConfig()
    assert config.token == "test-token-123"
    assert config.webhook_url == "https://example.com/webhook/max"


def test_max_bot_config_optional_when_disabled(monkeypatch):
    """MaxBotConfig should be None in AppConfig when env vars are absent."""
    # This tests that AppConfig.max_bot is Optional
    pass  # Will be refined after seeing AppConfig pattern
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config_max.py -v`
Expected: FAIL — `MaxBotConfig` does not exist

- [ ] **Step 3: Add MaxBotConfig to config.py**

Add after `WebhookConfig` class in `src/ugc_bot/config.py`:

```python
class MaxBotConfig(BaseSettings):
    """Max messenger bot configuration."""

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    token: str = Field(alias="MAX_BOT_TOKEN")
    webhook_url: str = Field(alias="MAX_WEBHOOK_URL")
```

Add to `AppConfig`:
```python
max_bot: MaxBotConfig | None = None
```

Update `load_config()` to try loading MaxBotConfig:
```python
try:
    max_bot = MaxBotConfig()
except Exception:
    max_bot = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config_max.py -v`
Expected: PASS

- [ ] **Step 5: Run full checks**

Run: `make fix`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/config.py tests/unit/test_config_max.py
git commit -m "feat: add MaxBotConfig for Max messenger"
```

---

### Task 2: Create MaxRedisStateStore

**Files:**
- Create: `src/ugc_bot/infrastructure/messenger/max/__init__.py`
- Create: `src/ugc_bot/infrastructure/messenger/max/state.py`
- Test: `tests/unit/infrastructure/messenger/max/test_state.py`

Reference: `src/ugc_bot/application/messenger/state.py` (StateStore protocol, 23 lines)
Reference: `src/ugc_bot/infrastructure/messenger/telegram/state.py` (AiogramStateStore, 39 lines)

- [ ] **Step 1: Write failing tests for MaxRedisStateStore**

```python
# tests/unit/infrastructure/messenger/max/test_state.py
import pytest
from unittest.mock import AsyncMock
from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore


@pytest.fixture
def fake_redis():
    """Minimal fake Redis with get/set/delete."""
    store = {}

    class FakeRedis:
        async def get(self, key):
            return store.get(key)

        async def set(self, key, value):
            store[key] = value

        async def delete(self, key):
            store.pop(key, None)

    return FakeRedis()


@pytest.fixture
def state_store(fake_redis):
    return MaxRedisStateStore(redis=fake_redis, chat_id="chat_1", user_id="user_1")


@pytest.mark.asyncio
async def test_initial_state_is_none(state_store):
    assert await state_store.get_state() is None


@pytest.mark.asyncio
async def test_set_and_get_state(state_store):
    await state_store.set_state("waiting_name")
    assert await state_store.get_state() == "waiting_name"


@pytest.mark.asyncio
async def test_set_state_none_clears(state_store):
    await state_store.set_state("waiting_name")
    await state_store.set_state(None)
    assert await state_store.get_state() is None


@pytest.mark.asyncio
async def test_update_and_get_data(state_store):
    await state_store.update_data(name="Alice", age=30)
    data = await state_store.get_data()
    assert data == {"name": "Alice", "age": 30}


@pytest.mark.asyncio
async def test_update_data_merges(state_store):
    await state_store.update_data(name="Alice")
    await state_store.update_data(age=30)
    data = await state_store.get_data()
    assert data == {"name": "Alice", "age": 30}


@pytest.mark.asyncio
async def test_clear(state_store):
    await state_store.set_state("some_state")
    await state_store.update_data(key="val")
    await state_store.clear()
    assert await state_store.get_state() is None
    assert await state_store.get_data() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_state.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement MaxRedisStateStore**

Create `src/ugc_bot/infrastructure/messenger/max/__init__.py` (empty).

```python
# src/ugc_bot/infrastructure/messenger/max/state.py
"""Redis-backed FSM state store for Max messenger."""

import json
from typing import Any


class MaxRedisStateStore:
    """StateStore implementation using Redis for Max messenger.

    Scoped per (chat_id, user_id) — create a new instance per incoming request.
    """

    def __init__(self, redis: Any, chat_id: str, user_id: str) -> None:
        self._redis = redis
        self._state_key = f"max_fsm:{chat_id}:{user_id}:state"
        self._data_key = f"max_fsm:{chat_id}:{user_id}:data"

    async def get_state(self) -> str | None:
        return await self._redis.get(self._state_key)

    async def set_state(self, state: str | None) -> None:
        if state is None:
            await self._redis.delete(self._state_key)
        else:
            await self._redis.set(self._state_key, state)

    async def update_data(self, **kwargs: Any) -> None:
        data = await self.get_data()
        data.update(kwargs)
        await self._redis.set(self._data_key, json.dumps(data))

    async def get_data(self) -> dict[str, Any]:
        raw = await self._redis.get(self._data_key)
        if raw is None:
            return {}
        return json.loads(raw)

    async def clear(self) -> None:
        await self._redis.delete(self._state_key)
        await self._redis.delete(self._data_key)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_state.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run full checks**

Run: `make fix`

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/infrastructure/messenger/max/ tests/unit/infrastructure/messenger/max/
git commit -m "feat: add MaxRedisStateStore for Max messenger FSM"
```

---

### Task 3: Create MaxEventAdapter

**Files:**
- Create: `src/ugc_bot/infrastructure/messenger/max/adapter.py`
- Test: `tests/unit/infrastructure/messenger/max/test_adapter.py`

Reference: `src/ugc_bot/infrastructure/messenger/telegram/adapter.py` (121 lines)
Reference: `src/ugc_bot/application/messenger/dto.py` — IncomingMessage, IncomingCallback, IncomingUser

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/infrastructure/messenger/max/test_adapter.py
import pytest
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.messenger.max.adapter import MaxEventAdapter


@pytest.fixture
def adapter():
    return MaxEventAdapter()


class TestFromMessage:
    def test_text_message(self, adapter):
        event = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 12345, "username": "alice"},
                "recipient": {"chat_id": 67890},
                "body": {"mid": "msg_1", "text": "Hello"},
            },
        }
        result = adapter.from_message(event)
        assert result.chat_id == "67890"
        assert result.user.external_id == "12345"
        assert result.user.messenger_type == MessengerType.MAX
        assert result.user.username == "alice"
        assert result.text == "Hello"
        assert result.message_id == "msg_1"

    def test_message_without_text(self, adapter):
        event = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1, "username": None},
                "recipient": {"chat_id": 2},
                "body": {"mid": "msg_2"},
            },
        }
        result = adapter.from_message(event)
        assert result.text is None
        assert result.user.username is None

    def test_message_with_contact(self, adapter):
        event = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1, "username": "bob"},
                "recipient": {"chat_id": 2},
                "body": {
                    "mid": "msg_3",
                    "contact": {"phone": "+79001234567"},
                },
            },
        }
        result = adapter.from_message(event)
        assert result.contact_phone == "+79001234567"

    def test_message_with_location(self, adapter):
        event = {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 1, "username": "bob"},
                "recipient": {"chat_id": 2},
                "body": {
                    "mid": "msg_4",
                    "location": {"latitude": 55.75, "longitude": 37.62},
                },
            },
        }
        result = adapter.from_message(event)
        assert result.location_lat == 55.75
        assert result.location_lon == 37.62


class TestFromCallback:
    def test_callback(self, adapter):
        event = {
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb_1",
                "user": {"user_id": 12345, "username": "alice"},
                "message": {
                    "recipient": {"chat_id": 67890},
                    "body": {"mid": "msg_1", "text": "old text"},
                },
                "payload": "order:abc123",
            },
        }
        result = adapter.from_callback(event)
        assert result.callback_id == "cb_1"
        assert result.chat_id == "67890"
        assert result.user.external_id == "12345"
        assert result.user.messenger_type == MessengerType.MAX
        assert result.data == "order:abc123"
        assert result.message_id == "msg_1"
        assert result.message_text == "old text"


class TestFromPreCheckout:
    def test_raises_not_implemented(self, adapter):
        with pytest.raises(NotImplementedError):
            adapter.from_pre_checkout({})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_adapter.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement MaxEventAdapter**

```python
# src/ugc_bot/infrastructure/messenger/max/adapter.py
"""Max messenger event adapter — converts raw webhook JSON to neutral DTOs."""

from ugc_bot.application.messenger.dto import (
    IncomingCallback,
    IncomingMessage,
    IncomingUser,
)
from ugc_bot.domain.enums import MessengerType


class MaxEventAdapter:
    """Converts Max webhook events into messenger-neutral DTOs."""

    def from_message(self, event: object) -> IncomingMessage:
        data = event if isinstance(event, dict) else {}
        msg = data.get("message", {})
        sender = msg.get("sender", {})
        recipient = msg.get("recipient", {})
        body = msg.get("body", {})
        contact = body.get("contact")
        location = body.get("location")

        return IncomingMessage(
            chat_id=str(recipient.get("chat_id", "")),
            user=IncomingUser(
                external_id=str(sender.get("user_id", "")),
                messenger_type=MessengerType.MAX,
                username=sender.get("username"),
            ),
            text=body.get("text"),
            message_id=body.get("mid"),
            contact_phone=contact.get("phone") if contact else None,
            location_lat=location.get("latitude") if location else None,
            location_lon=location.get("longitude") if location else None,
            raw=data,
        )

    def from_callback(self, event: object) -> IncomingCallback:
        data = event if isinstance(event, dict) else {}
        cb = data.get("callback", {})
        user = cb.get("user", {})
        message = cb.get("message", {})
        recipient = message.get("recipient", {})
        body = message.get("body", {})

        return IncomingCallback(
            callback_id=str(cb.get("callback_id", "")),
            chat_id=str(recipient.get("chat_id", "")),
            user=IncomingUser(
                external_id=str(user.get("user_id", "")),
                messenger_type=MessengerType.MAX,
                username=user.get("username"),
            ),
            data=cb.get("payload"),
            message_id=body.get("mid"),
            message_text=body.get("text"),
            raw=data,
        )

    def from_pre_checkout(self, query: object):
        raise NotImplementedError("Max does not support payments")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Run full checks, commit**

```bash
make fix
git add src/ugc_bot/infrastructure/messenger/max/adapter.py tests/unit/infrastructure/messenger/max/
git commit -m "feat: add MaxEventAdapter for Max webhook events"
```

---

### Task 4: Create MaxMessengerClient

**Files:**
- Create: `src/ugc_bot/infrastructure/messenger/max/client.py`
- Test: `tests/unit/infrastructure/messenger/max/test_client.py`

Reference: `src/ugc_bot/infrastructure/messenger/telegram/client.py` (294 lines)
Reference: `src/ugc_bot/application/messenger/ports.py` — MessengerClient protocol
Reference: Max API docs: `https://dev.max.ru/docs-api`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/infrastructure/messenger/max/test_client.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ugc_bot.application.messenger.dto import (
    Button, Keyboard, KeyboardKind, Invoice, InvoiceItem,
)
from ugc_bot.infrastructure.messenger.max.client import MaxMessengerClient


@pytest.fixture
def mock_session():
    session = AsyncMock()
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"success": True})
    session.post = AsyncMock(return_value=response)
    session.put = AsyncMock(return_value=response)
    session.delete = AsyncMock(return_value=response)
    # Context manager support
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session.post.return_value = response
    session.put.return_value = response
    session.delete.return_value = response
    return session


@pytest.fixture
def client(mock_session):
    return MaxMessengerClient(token="test-token", session=mock_session)


@pytest.mark.asyncio
async def test_send_text_plain(client, mock_session):
    await client.send_text(chat_id="123", text="Hello")
    mock_session.post.assert_called_once()
    call_kwargs = mock_session.post.call_args
    assert "chat_id=123" in str(call_kwargs)


@pytest.mark.asyncio
async def test_send_text_with_inline_keyboard(client, mock_session):
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Click", callback_data="btn:1")]],
    )
    await client.send_text(chat_id="123", text="Choose:", keyboard=kb)
    mock_session.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_photo_falls_back_to_text(client, mock_session):
    """Max client sends caption as text instead of photo."""
    await client.send_photo(chat_id="123", file_id="abc", caption="My photo")
    mock_session.post.assert_called_once()
    call_args = mock_session.post.call_args
    # Should send text, not photo
    body = call_args.kwargs.get("json", {})
    assert body.get("text") == "My photo"


@pytest.mark.asyncio
async def test_edit_text(client, mock_session):
    await client.edit_text(chat_id="123", message_id="msg_1", text="Updated")
    mock_session.put.assert_called_once()


@pytest.mark.asyncio
async def test_answer_callback(client, mock_session):
    await client.answer_callback(callback_id="cb_1", text="Done")
    mock_session.post.assert_called_once()


@pytest.mark.asyncio
async def test_send_invoice_raises(client):
    invoice = Invoice(
        title="Test", description="Desc", payload="pay_1",
        provider_token="tok", currency="RUB",
        items=[InvoiceItem(label="Item", amount_minor=10000)],
    )
    with pytest.raises(NotImplementedError):
        await client.send_invoice(chat_id="123", invoice=invoice)


@pytest.mark.asyncio
async def test_edit_reply_markup(client, mock_session):
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="New", callback_data="new:1")]],
    )
    await client.edit_reply_markup(chat_id="123", message_id="msg_1", keyboard=kb)
    mock_session.put.assert_called_once()


@pytest.mark.asyncio
async def test_reply_keyboard_ignored(client, mock_session):
    """Reply keyboards are not supported in Max — send text without keyboard."""
    kb = Keyboard(kind=KeyboardKind.REPLY, rows=[[Button(text="Share contact", request_contact=True)]])
    await client.send_text(chat_id="123", text="Hello", keyboard=kb)
    mock_session.post.assert_called_once()
    body = mock_session.post.call_args.kwargs.get("json", {})
    assert "attachments" not in body  # no keyboard sent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_client.py -v`
Expected: FAIL

- [ ] **Step 3: Implement MaxMessengerClient**

```python
# src/ugc_bot/infrastructure/messenger/max/client.py
"""Max messenger client — sends messages via Max Platform API."""

import asyncio
import logging
import re
from typing import Any

import aiohttp

from ugc_bot.application.messenger.dto import (
    Button,
    Invoice,
    Keyboard,
    KeyboardKind,
)

logger = logging.getLogger(__name__)

MAX_API_BASE_URL = "https://platform-api.max.ru"
MAX_RETRY_ATTEMPTS = 3
MAX_RETRY_BASE_DELAY = 0.5

# Regex to strip HTML tags for Max (which doesn't support HTML parse_mode)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags from text for Max messenger."""
    return _HTML_TAG_RE.sub("", text)


def _build_inline_keyboard(keyboard: Keyboard) -> dict[str, Any]:
    """Convert neutral Keyboard DTO to Max InlineKeyboardAttachment."""
    buttons = []
    for row in keyboard.rows:
        for btn in row:
            max_btn: dict[str, Any] = {"text": btn.text, "type": "callback"}
            if btn.callback_data:
                max_btn["type"] = "callback"
                max_btn["payload"] = btn.callback_data
            elif btn.url:
                max_btn["type"] = "link"
                max_btn["url"] = btn.url
            elif btn.request_contact:
                max_btn["type"] = "request_contact"
            elif btn.request_location:
                max_btn["type"] = "request_geo_location"
            buttons.append(max_btn)
    return {"type": "inline_keyboard", "payload": {"buttons": buttons}}


class MaxMessengerClient:
    """MessengerClient implementation for Max messenger."""

    def __init__(self, token: str, session: aiohttp.ClientSession) -> None:
        self._token = token
        self._session = session
        self._base_url = MAX_API_BASE_URL

    async def _request(
        self, method: str, path: str, json_body: dict | None = None
    ) -> dict:
        """Make HTTP request with retry on 5xx and rate limit handling."""
        url = f"{self._base_url}{path}"
        headers = {"Authorization": self._token}
        last_exc: Exception | None = None

        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                async with self._session.request(
                    method, url, json=json_body, headers=headers
                ) as resp:
                    if resp.status == 429:
                        retry_after = float(resp.headers.get("Retry-After", "1"))
                        logger.warning("Max API rate limited, retry after %s s", retry_after)
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status == 403:
                        logger.warning("Max API 403 (user blocked bot?): %s", await resp.text())
                        return {}
                    if resp.status >= 500:
                        text = await resp.text()
                        logger.error("Max API 5xx error %s: %s", resp.status, text)
                        await asyncio.sleep(MAX_RETRY_BASE_DELAY * (2 ** attempt))
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.error("Max API error %s: %s", resp.status, text)
                    return await resp.json()
            except aiohttp.ClientError as exc:
                last_exc = exc
                logger.error("Max API network error (attempt %d): %s", attempt + 1, exc)
                await asyncio.sleep(MAX_RETRY_BASE_DELAY * (2 ** attempt))

        logger.error("Max API request failed after %d attempts", MAX_RETRY_ATTEMPTS)
        if last_exc:
            raise last_exc
        return {}

    async def _post(self, path: str, json_body: dict | None = None) -> dict:
        return await self._request("POST", path, json_body)

    async def _put(self, path: str, json_body: dict | None = None) -> dict:
        return await self._request("PUT", path, json_body)

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        # Strip HTML tags — Max doesn't support Telegram's HTML parse_mode
        clean_text = _strip_html(text) if parse_mode and "html" in parse_mode.lower() else text
        body: dict[str, Any] = {"text": clean_text}
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"] = [_build_inline_keyboard(keyboard)]
        # REPLY and REMOVE keyboards are not supported — silently ignore
        await self._post(f"/messages?chat_id={chat_id}", body)

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        # Max: send caption as text, ignore photo
        text = caption or ""
        await self.send_text(chat_id=chat_id, text=text, keyboard=keyboard)

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"text": text}
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"] = [_build_inline_keyboard(keyboard)]
        await self._put(f"/messages?message_id={message_id}", body)

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"] = [_build_inline_keyboard(keyboard)]
        await self._put(f"/messages?message_id={message_id}", body)

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        body: dict[str, Any] = {}
        if text:
            body["message"] = {"text": text}
        await self._post(f"/answers/callback?callback_id={callback_id}", body)

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        raise NotImplementedError(
            "Max messenger does not support payments. "
            "Check messenger_type before calling send_invoice."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/infrastructure/messenger/max/test_client.py -v`
Expected: PASS

- [ ] **Step 5: Run full checks, commit**

```bash
make fix
git add src/ugc_bot/infrastructure/messenger/max/client.py tests/unit/infrastructure/messenger/max/
git commit -m "feat: add MaxMessengerClient for Max Platform API"
```

---

### Task 5: Create MaxRouter

**Files:**
- Create: `src/ugc_bot/bot/max/router.py`
- Create: `src/ugc_bot/bot/max/__init__.py`
- Test: `tests/unit/bot/max/test_router.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/bot/max/test_router.py
import pytest
from ugc_bot.application.messenger.dto import IncomingMessage, IncomingCallback, IncomingUser
from ugc_bot.domain.enums import MessengerType
from ugc_bot.bot.max.router import MaxRouter


@pytest.fixture
def router():
    return MaxRouter()


@pytest.fixture
def incoming_message():
    return IncomingMessage(
        chat_id="1",
        user=IncomingUser(external_id="1", messenger_type=MessengerType.MAX),
        text="/start",
        message_id="msg_1",
    )


@pytest.fixture
def incoming_callback():
    return IncomingCallback(
        callback_id="cb_1",
        chat_id="1",
        user=IncomingUser(external_id="1", messenger_type=MessengerType.MAX),
        data="order:123",
        message_id="msg_1",
    )


@pytest.mark.asyncio
async def test_route_message_matching(router, incoming_message):
    called = []

    @router.message(lambda m: m.text == "/start")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_route_message_no_match(router, incoming_message):
    called = []

    @router.message(lambda m: m.text == "/help")
    async def handler(msg, deps):
        called.append(msg)

    await router.route_message(incoming_message, {})
    assert len(called) == 0


@pytest.mark.asyncio
async def test_route_callback_matching(router, incoming_callback):
    called = []

    @router.callback(lambda c: (c.data or "").startswith("order:"))
    async def handler(cb, deps):
        called.append(cb)

    await router.route_callback(incoming_callback, {})
    assert len(called) == 1


@pytest.mark.asyncio
async def test_first_matching_handler_wins(router, incoming_message):
    called = []

    @router.message(lambda m: True)
    async def first(msg, deps):
        called.append("first")

    @router.message(lambda m: True)
    async def second(msg, deps):
        called.append("second")

    await router.route_message(incoming_message, {})
    assert called == ["first"]


@pytest.mark.asyncio
async def test_include_router(router, incoming_message):
    child = MaxRouter()
    called = []

    @child.message(lambda m: m.text == "/start")
    async def handler(msg, deps):
        called.append(msg)

    router.include(child)
    await router.route_message(incoming_message, {})
    assert len(called) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/bot/max/test_router.py -v`
Expected: FAIL

- [ ] **Step 3: Implement MaxRouter**

```python
# src/ugc_bot/bot/max/router.py
"""Lightweight router for Max messenger events."""

from collections.abc import Awaitable, Callable
from typing import Any

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage

FilterFn = Callable[[Any], bool]
MessageHandler = Callable[[IncomingMessage, dict], Awaitable[None]]
CallbackHandler = Callable[[IncomingCallback, dict], Awaitable[None]]


class MaxRouter:
    """Routes incoming Max events to registered handlers."""

    def __init__(self) -> None:
        self._message_handlers: list[tuple[FilterFn, MessageHandler]] = []
        self._callback_handlers: list[tuple[FilterFn, CallbackHandler]] = []

    def message(self, filter_fn: FilterFn):
        """Register a message handler with a filter."""
        def decorator(handler: MessageHandler) -> MessageHandler:
            self._message_handlers.append((filter_fn, handler))
            return handler
        return decorator

    def callback(self, filter_fn: FilterFn):
        """Register a callback handler with a filter."""
        def decorator(handler: CallbackHandler) -> CallbackHandler:
            self._callback_handlers.append((filter_fn, handler))
            return handler
        return decorator

    def include(self, other: "MaxRouter") -> None:
        """Include handlers from another router."""
        self._message_handlers.extend(other._message_handlers)
        self._callback_handlers.extend(other._callback_handlers)

    async def route_message(self, incoming: IncomingMessage, deps: dict) -> None:
        for filter_fn, handler in self._message_handlers:
            if filter_fn(incoming):
                await handler(incoming, deps)
                return

    async def route_callback(self, incoming: IncomingCallback, deps: dict) -> None:
        for filter_fn, handler in self._callback_handlers:
            if filter_fn(incoming):
                await handler(incoming, deps)
                return
```

Create `src/ugc_bot/bot/max/__init__.py` (empty).
Create `src/ugc_bot/bot/max/handlers/__init__.py` (empty).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/bot/max/test_router.py -v`
Expected: PASS

- [ ] **Step 5: Run full checks, commit**

```bash
make fix
git add src/ugc_bot/bot/max/ tests/unit/bot/max/
git commit -m "feat: add MaxRouter for Max messenger event dispatching"
```

---

## Phase 2: Restructure bot/ directory

### Task 6: Move bot/ → bot/telegram/

This is a pure file move with import updates. No logic changes. Broken into sub-steps to reduce error risk.

**Files to move:**
- `src/ugc_bot/bot/handlers/` → `src/ugc_bot/bot/telegram/handlers/` (all 19 handler files + `utils.py`, `keyboards.py`, `order_creation_states.py`, `__init__.py`)
- `src/ugc_bot/bot/middleware/` → `src/ugc_bot/bot/telegram/middleware/`
- `src/ugc_bot/bot/filters.py` → `src/ugc_bot/bot/telegram/filters.py`
- `src/ugc_bot/bot/validators.py` → `src/ugc_bot/bot/telegram/validators.py`

**Files to update imports:**
- `src/ugc_bot/app.py` — 15 router imports + middleware imports
- `src/ugc_bot/telegram_webhook_app.py` — if it imports from bot.*
- All handler files with cross-imports (e.g. `from ugc_bot.bot.handlers.keyboards import ...`)
- All test files in `tests/` referencing `bot.handlers` or `bot.middleware`

- [ ] **Step 1: Create bot/telegram/ directory and move files**

```bash
mkdir -p src/ugc_bot/bot/telegram
touch src/ugc_bot/bot/telegram/__init__.py
git mv src/ugc_bot/bot/handlers src/ugc_bot/bot/telegram/handlers
git mv src/ugc_bot/bot/middleware src/ugc_bot/bot/telegram/middleware
git mv src/ugc_bot/bot/filters.py src/ugc_bot/bot/telegram/filters.py
git mv src/ugc_bot/bot/validators.py src/ugc_bot/bot/telegram/validators.py
```

- [ ] **Step 2: Find all imports to update**

```bash
grep -rn "ugc_bot\.bot\.handlers\|ugc_bot\.bot\.middleware\|ugc_bot\.bot\.filters\|ugc_bot\.bot\.validators" src/ tests/
```

Record all files and line numbers that need updating.

- [ ] **Step 3: Update imports in app.py**

Replace all 15+ imports in `src/ugc_bot/app.py`:
- `ugc_bot.bot.handlers.` → `ugc_bot.bot.telegram.handlers.`
- `ugc_bot.bot.middleware.` → `ugc_bot.bot.telegram.middleware.`

- [ ] **Step 4: Update imports in telegram_webhook_app.py**

If any imports reference `bot.handlers` or `bot.middleware`, update them.

- [ ] **Step 5: Update internal cross-handler imports**

Handler files import from each other (e.g. `from ugc_bot.bot.handlers.keyboards import ...`).
Update all internal imports within `src/ugc_bot/bot/telegram/handlers/`.

- [ ] **Step 6: Update test imports**

Update all test files in `tests/` that import from `bot.handlers` or `bot.middleware`.

- [ ] **Step 7: Verify all checks pass**

Run: `make fix`
Expected: All pass — format, lint, typecheck, coverage

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: move bot handlers/middleware under bot/telegram/"
```

---

## Phase 3: Max webhook entry point

### Task 7: Create max_webhook_app.py

**Files:**
- Create: `src/ugc_bot/max_webhook_app.py`
- Create: `src/ugc_bot/bot/max/middleware.py`
- Test: `tests/unit/test_max_webhook_app.py`

Reference: `src/ugc_bot/telegram_webhook_app.py` (263 lines)

- [ ] **Step 1: Write test for webhook endpoint**

```python
# tests/unit/test_max_webhook_app.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_max_webhook_routes_message():
    """Verify webhook endpoint parses message_created and routes it."""
    # This will be an integration-style test once the app is built.
    # For now, test the routing logic in isolation.
    from ugc_bot.bot.max.router import MaxRouter
    from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
    from ugc_bot.domain.enums import MessengerType
    from ugc_bot.infrastructure.messenger.max.adapter import MaxEventAdapter

    adapter = MaxEventAdapter()
    router = MaxRouter()
    called = []

    @router.message(lambda m: m.text == "/start")
    async def start(msg, deps):
        called.append("start")

    event = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 1, "username": "test"},
            "recipient": {"chat_id": 2},
            "body": {"mid": "m1", "text": "/start"},
        },
    }

    incoming = adapter.from_message(event)
    await router.route_message(incoming, {})
    assert called == ["start"]
```

- [ ] **Step 2: Run test to verify it passes** (uses already-built components)

Run: `uv run pytest tests/unit/test_max_webhook_app.py -v`
Expected: PASS

- [ ] **Step 3: Create bot/max/middleware.py**

```python
# src/ugc_bot/bot/max/middleware.py
"""Middleware functions for Max messenger handlers."""

import logging

from ugc_bot.application.messenger.dto import IncomingMessage, IncomingCallback
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import MessengerType

logger = logging.getLogger(__name__)


async def resolve_locale(
    incoming: IncomingMessage | IncomingCallback,
    user_role_service: UserRoleService,
    default_locale: str = "ru",
) -> str:
    """Resolve user locale from DB, fallback to default."""
    user = await user_role_service.find_user_by_messenger(
        messenger_type=MessengerType.MAX,
        external_id=incoming.user.external_id,
    )
    if user and user.language:
        return user.language
    return default_locale
```

- [ ] **Step 4: Create max_webhook_app.py**

```python
# src/ugc_bot/max_webhook_app.py
"""Max messenger webhook application.

Entry point for Max bot. Runs as a separate process on port 8003.
Usage: uvicorn ugc_bot.max_webhook_app:app --host 0.0.0.0 --port 8003
"""

import logging
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.infrastructure.messenger.max.adapter import MaxEventAdapter
from ugc_bot.infrastructure.messenger.max.client import MAX_API_BASE_URL, MaxMessengerClient
from ugc_bot.infrastructure.messenger.max.state import MaxRedisStateStore

logger = logging.getLogger(__name__)

# Import Max handlers (registers routes on import)
# from ugc_bot.bot.max.handlers import start as _  # noqa: F401

max_router = MaxRouter()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    config = load_config()

    if not config.max_bot:
        logger.error("MAX_BOT_TOKEN not configured, exiting")
        yield
        return

    redis = Redis.from_url(config.redis.redis_url, decode_responses=True)
    http_session = aiohttp.ClientSession()

    container = Container(config)
    bot_services = container.build_bot_services()

    messenger_client = MaxMessengerClient(
        token=config.max_bot.token, session=http_session
    )
    event_adapter = MaxEventAdapter()

    app.state.config = config
    app.state.redis = redis
    app.state.bot_services = bot_services
    app.state.messenger_client = messenger_client
    app.state.event_adapter = event_adapter
    app.state.container = container
    app.state.max_router = max_router

    # Register webhook with Max API
    webhook_url = config.max_bot.webhook_url
    try:
        async with http_session.post(
            f"{MAX_API_BASE_URL}/subscriptions",
            json={"url": webhook_url},
            headers={"Authorization": config.max_bot.token},
        ) as resp:
            if resp.status < 300:
                logger.info("Max webhook registered: %s", webhook_url)
            else:
                logger.error("Failed to register Max webhook: %s", await resp.text())
    except Exception:
        logger.exception("Error registering Max webhook")

    logger.info("Max webhook app started")

    yield

    await http_session.close()
    await redis.aclose()
    container.dispose()


app = FastAPI(lifespan=_lifespan)


@app.post("/webhook/max")
async def handle_max_webhook(request: Request) -> JSONResponse:
    data = await request.json()
    update_type = data.get("update_type")
    state = request.app.state
    event_adapter: MaxEventAdapter = state.event_adapter

    # Build deps dict for handlers
    deps = {
        **state.bot_services,
        "messenger_client": state.messenger_client,
        "config": state.config,
    }

    try:
        if update_type == "message_created":
            incoming = event_adapter.from_message(data)
            # Create per-request state store
            state_store = MaxRedisStateStore(
                redis=state.redis,
                chat_id=incoming.chat_id,
                user_id=incoming.user.external_id,
            )
            deps["state_store"] = state_store
            await state.max_router.route_message(incoming, deps)

        elif update_type == "message_callback":
            incoming = event_adapter.from_callback(data)
            state_store = MaxRedisStateStore(
                redis=state.redis,
                chat_id=incoming.chat_id,
                user_id=incoming.user.external_id,
            )
            deps["state_store"] = state_store
            await state.max_router.route_callback(incoming, deps)

        else:
            logger.debug("Unhandled Max update type: %s", update_type)

    except Exception:
        logger.exception("Error processing Max update: %s", update_type)

    return JSONResponse({"ok": True})
```

- [ ] **Step 5: Run full checks**

Run: `make fix`

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/max_webhook_app.py src/ugc_bot/bot/max/middleware.py tests/unit/test_max_webhook_app.py
git commit -m "feat: add Max webhook entry point on port 8003"
```

---

### Task 8: Add Docker service for Max bot

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.dev.yml` (if exists)

- [ ] **Step 1: Add max_bot service to docker-compose.yml**

Add after the `app_2` service:

```yaml
  max_bot:
    build: .
    command: uvicorn ugc_bot.max_webhook_app:app --host 0.0.0.0 --port 8003
    ports:
      - "8003:8003"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: unless-stopped
```

- [ ] **Step 2: Add to dev compose if exists**

Check `docker-compose.dev.yml` and add the same service.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml docker-compose.dev.yml
git commit -m "infra: add max_bot service to docker-compose"
```

---

## Phase 4: First Max handler — /start

### Task 9: Write Max /start handler

This is the first real Max handler. It demonstrates the thin handler pattern and proves the full stack works end-to-end (webhook → adapter → router → handler → service → client).

**Files:**
- Create: `src/ugc_bot/bot/max/handlers/start.py`
- Test: `tests/unit/bot/max/handlers/test_start.py`

Reference: `src/ugc_bot/bot/telegram/handlers/start.py` — for business logic to delegate to services

- [ ] **Step 1: Write failing test**

```python
# tests/unit/bot/max/handlers/test_start.py
import pytest
from unittest.mock import AsyncMock
from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.domain.enums import MessengerType
from ugc_bot.bot.max.handlers.start import router


@pytest.fixture
def incoming_start():
    return IncomingMessage(
        chat_id="100",
        user=IncomingUser(external_id="42", messenger_type=MessengerType.MAX, username="alice"),
        text="/start",
        message_id="msg_1",
    )


@pytest.fixture
def deps():
    return {
        "messenger_client": AsyncMock(),
        "user_role_service": AsyncMock(),
        "bot_texts_service": AsyncMock(),
        "state_store": AsyncMock(),
        "config": AsyncMock(),
    }


@pytest.mark.asyncio
async def test_start_handler_sends_welcome(incoming_start, deps):
    deps["user_role_service"].get_or_create_user = AsyncMock(return_value=AsyncMock(language="ru"))
    deps["bot_texts_service"].get = AsyncMock(return_value="Добро пожаловать!")

    await router.route_message(incoming_start, deps)

    deps["messenger_client"].send_text.assert_called_once()
    call_kwargs = deps["messenger_client"].send_text.call_args.kwargs
    assert call_kwargs["chat_id"] == "100"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/bot/max/handlers/test_start.py -v`
Expected: FAIL

- [ ] **Step 3: Implement /start handler for Max**

```python
# src/ugc_bot/bot/max/handlers/start.py
"""Max messenger /start handler."""

from ugc_bot.application.messenger.dto import IncomingMessage
from ugc_bot.bot.max.router import MaxRouter

router = MaxRouter()


@router.message(lambda m: m.text and m.text.startswith("/start"))
async def start_handler(incoming: IncomingMessage, deps: dict) -> None:
    """Handle /start command in Max messenger."""
    messenger_client = deps["messenger_client"]
    user_role_service = deps["user_role_service"]

    # Get or create user
    user = await user_role_service.get_or_create_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        username=incoming.user.username,
    )

    locale = user.language or "ru"
    bot_texts_service = deps.get("bot_texts_service")
    welcome = "Добро пожаловать!"
    if bot_texts_service:
        welcome = await bot_texts_service.get("start_welcome", locale) or welcome

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=welcome,
    )
```

- [ ] **Step 4: Register start router in max_webhook_app.py**

In `src/ugc_bot/max_webhook_app.py`, uncomment/add the handler import and include the router:

```python
from ugc_bot.bot.max.handlers.start import router as start_router

max_router = MaxRouter()
max_router.include(start_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/bot/max/handlers/test_start.py -v`
Expected: PASS

- [ ] **Step 6: Run full checks, commit**

```bash
make fix
git add src/ugc_bot/bot/max/handlers/start.py src/ugc_bot/max_webhook_app.py tests/unit/bot/max/handlers/
git commit -m "feat: add Max /start handler — first working handler"
```

---

## Phase 4b: Service preparation for thin handlers

### Task 10: Add find_user_by_messenger to UserRoleService

**Files:**
- Modify: `src/ugc_bot/application/services/user_role_service.py`
- Test: `tests/unit/application/services/test_user_role_service.py` (existing file)

Reference: `src/ugc_bot/application/services/user_role_service.py` (338 lines)

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_find_user_by_messenger_telegram():
    user_repo = MemoryUserRepository()
    user = make_user(telegram_id="123", messenger_type=MessengerType.TELEGRAM)
    await user_repo.add(user)
    service = UserRoleService(user_repo=user_repo, ...)
    found = await service.find_user_by_messenger(MessengerType.TELEGRAM, "123")
    assert found is not None
    assert found.telegram_id == "123"

@pytest.mark.asyncio
async def test_find_user_by_messenger_max():
    user_repo = MemoryUserRepository()
    user = make_user(max_id="456", messenger_type=MessengerType.MAX)
    await user_repo.add(user)
    service = UserRoleService(user_repo=user_repo, ...)
    found = await service.find_user_by_messenger(MessengerType.MAX, "456")
    assert found is not None
    assert found.max_id == "456"

@pytest.mark.asyncio
async def test_find_user_by_messenger_not_found():
    user_repo = MemoryUserRepository()
    service = UserRoleService(user_repo=user_repo, ...)
    found = await service.find_user_by_messenger(MessengerType.MAX, "999")
    assert found is None
```

- [ ] **Step 2: Implement find_user_by_messenger**

Add to `UserRoleService`:
```python
async def find_user_by_messenger(
    self, messenger_type: MessengerType, external_id: str
) -> User | None:
    if messenger_type == MessengerType.TELEGRAM:
        return await self._user_repo.get_by_telegram_id(external_id)
    elif messenger_type == MessengerType.MAX:
        return await self._user_repo.get_by_max_id(external_id)
    return None
```

Check that `get_by_telegram_id` and `get_by_max_id` exist on the repository. If `get_by_max_id` doesn't exist, add it to both the abstract port and the SQLAlchemy + memory implementations.

- [ ] **Step 3: Run tests, commit**

```bash
make fix
git commit -m "feat: add find_user_by_messenger to UserRoleService"
```

---

### Task 11: Create ServiceResponse dataclass

**Files:**
- Create: `src/ugc_bot/application/messenger/response.py`
- Test: `tests/unit/application/messenger/test_response.py`

- [ ] **Step 1: Write test**

```python
# tests/unit/application/messenger/test_response.py
from ugc_bot.application.messenger.response import ServiceResponse
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind


def test_service_response_text_only():
    r = ServiceResponse(text="Hello")
    assert r.text == "Hello"
    assert r.keyboard is None
    assert r.next_state is None


def test_service_response_with_keyboard():
    kb = Keyboard(kind=KeyboardKind.INLINE, rows=[[Button(text="OK", callback_data="ok")]])
    r = ServiceResponse(text="Choose:", keyboard=kb)
    assert r.keyboard is not None
```

- [ ] **Step 2: Implement ServiceResponse**

```python
# src/ugc_bot/application/messenger/response.py
"""Service response DTOs for thin handler pattern."""

from dataclasses import dataclass, field

from ugc_bot.application.messenger.dto import Keyboard


@dataclass(frozen=True, slots=True)
class ServiceResponse:
    """What a service method returns to a handler."""
    text: str
    keyboard: Keyboard | None = None
    photo_url: str | None = None
    next_state: str | None = None
    state_data: dict | None = None


@dataclass(frozen=True, slots=True)
class MultiResponse:
    """For scenarios requiring multiple messages."""
    responses: list[ServiceResponse] = field(default_factory=list)
```

- [ ] **Step 3: Run tests, commit**

```bash
make fix
git commit -m "feat: add ServiceResponse dataclass for thin handler pattern"
```

---

## Phase 5: Remaining Max handlers

**Note on `bot_services` dict:** `Container.build_bot_services()` returns a `BotServices` TypedDict with keys like `"user_role_service"`, `"bot_texts_service"`, `"order_service"`, `"interaction_service"`, etc. These get unpacked into the `deps` dict for Max handlers. Check `src/ugc_bot/container/service_factory.py` for the complete key list.

### Task 12+: Port remaining Telegram handlers to Max

For each handler file in `bot/telegram/handlers/`, create a corresponding thin handler in `bot/max/handlers/`. Follow this template per handler:

**Pattern for each handler:**

1. Read the Telegram handler to understand what services it calls
2. Identify the service methods and what they return
3. If service method doesn't return a `ServiceResponse`-like result (text + keyboard), refactor the service first
4. Write a failing test for the Max handler
5. Implement the thin Max handler (~10-15 lines per route)
6. Register the router in `max_webhook_app.py`
7. Run `make fix`, commit

**Handler priority order** (simplest first):
1. `survey_messenger.py` (157 lines) — simplest
2. `security_warnings.py` (119 lines)
3. `admin_moderation.py` (173 lines)
4. `instagram_verification.py` (217 lines)
5. `admin_message_to_user.py` (259 lines)
6. `payments.py` (520 lines) — skip for Max (no payments)
7. `complaints.py` (515 lines)
8. `my_orders.py` (691 lines)
9. `offer_responses.py` (930 lines)
10. `referral.py` (1044 lines)
11. `advertiser_registration.py` (784 lines)
12. `order_creation.py` (1514 lines)
13. `feedback.py` (1433 lines)
14. `blogger_registration.py` (2039 lines)
15. `profile.py` (2458 lines)

**Each handler is a separate task and separate commit.** For large handlers (1000+ lines), split into multiple subtasks (one per major route/flow).

**Refactoring pattern** (for each handler):
```
1. Read Telegram handler → identify service calls
2. If logic is inline in handler → extract to service method first (commit)
3. Write Max handler test (commit)
4. Write thin Max handler (commit)
```

---

## Phase 6: Account linking

### Task N+1: Create linking_codes migration

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0085_linking_codes.py`

- [ ] **Step 1: Generate migration**

```bash
cd src/ugc_bot && uv run alembic revision --autogenerate -m "add linking_codes table"
```

- [ ] **Step 2: Edit migration to create linking_codes table**

```python
def upgrade():
    op.create_table(
        "linking_codes",
        sa.Column("code", sa.String(6), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("messenger_type", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

def downgrade():
    op.drop_table("linking_codes")
```

- [ ] **Step 3: Run migration**

```bash
make migrate
```

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/
git commit -m "feat: add linking_codes table for cross-messenger account linking"
```

### Task N+2: Implement linking service

**Files:**
- Modify: `src/ugc_bot/application/services/user_role_service.py`
- Create: `src/ugc_bot/infrastructure/db/repositories/linking_code_repository.py`
- Test: `tests/unit/application/services/test_linking_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/application/services/test_linking_service.py
import pytest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock
from ugc_bot.domain.enums import MessengerType


@pytest.fixture
def linking_repo():
    """In-memory linking code repository."""
    codes = {}

    class FakeLinkingCodeRepo:
        async def save(self, code, user_id, messenger_type, external_id, expires_at):
            codes[code] = {
                "user_id": user_id, "messenger_type": messenger_type,
                "external_id": external_id, "expires_at": expires_at, "attempts": 0,
            }

        async def get(self, code):
            return codes.get(code)

        async def increment_attempts(self, code):
            if code in codes:
                codes[code]["attempts"] += 1

        async def delete(self, code):
            codes.pop(code, None)

    return FakeLinkingCodeRepo()


@pytest.fixture
def user_repo():
    return AsyncMock()


@pytest.mark.asyncio
async def test_generate_linking_code(linking_repo, user_repo):
    service = UserRoleService(user_repo=user_repo, linking_code_repo=linking_repo, ...)
    code = await service.generate_linking_code(
        user_id=uuid4(), messenger_type=MessengerType.MAX, external_id="456"
    )
    assert len(code) == 6
    assert code.isdigit()
    stored = await linking_repo.get(code)
    assert stored is not None
    assert stored["external_id"] == "456"


@pytest.mark.asyncio
async def test_redeem_valid_code(linking_repo, user_repo):
    user_id = uuid4()
    service = UserRoleService(user_repo=user_repo, linking_code_repo=linking_repo, ...)
    code = await service.generate_linking_code(
        user_id=user_id, messenger_type=MessengerType.MAX, external_id="456"
    )
    result = await service.redeem_linking_code(code=code, user_id=user_id)
    assert result is True
    user_repo.link_messenger.assert_called_once()


@pytest.mark.asyncio
async def test_redeem_expired_code(linking_repo, user_repo):
    service = UserRoleService(user_repo=user_repo, linking_code_repo=linking_repo, ...)
    # Manually insert expired code
    await linking_repo.save(
        code="000000", user_id=uuid4(), messenger_type=MessengerType.MAX,
        external_id="456",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    result = await service.redeem_linking_code(code="000000", user_id=uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_redeem_wrong_code_three_times(linking_repo, user_repo):
    service = UserRoleService(user_repo=user_repo, linking_code_repo=linking_repo, ...)
    # Non-existent code
    for _ in range(3):
        result = await service.redeem_linking_code(code="999999", user_id=uuid4())
        assert result is False


@pytest.mark.asyncio
async def test_redeem_already_linked(linking_repo, user_repo):
    user_repo.get_by_max_id = AsyncMock(return_value=AsyncMock())  # already linked
    service = UserRoleService(user_repo=user_repo, linking_code_repo=linking_repo, ...)
    await linking_repo.save(
        code="111111", user_id=uuid4(), messenger_type=MessengerType.MAX,
        external_id="456",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    result = await service.redeem_linking_code(code="111111", user_id=uuid4())
    assert result is False
```

- [ ] **Step 2: Implement LinkingCodeRepository (port + memory impl)**

Add abstract port to `application/ports.py` and in-memory implementation to `infrastructure/memory_repositories.py`.

- [ ] **Step 3: Implement generate_linking_code and redeem_linking_code in UserRoleService**

```python
async def generate_linking_code(
    self, user_id: UUID, messenger_type: MessengerType, external_id: str
) -> str:
    import random
    code = f"{random.randint(0, 999999):06d}"
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    await self._linking_code_repo.save(
        code=code, user_id=user_id, messenger_type=messenger_type,
        external_id=external_id, expires_at=expires_at,
    )
    return code

async def redeem_linking_code(self, code: str, user_id: UUID) -> bool:
    record = await self._linking_code_repo.get(code)
    if not record:
        return False
    if record["expires_at"] < datetime.now(timezone.utc):
        await self._linking_code_repo.delete(code)
        return False
    if record["attempts"] >= 3:
        await self._linking_code_repo.delete(code)
        return False
    # Check not already linked
    existing = await self._user_repo.get_by_max_id(record["external_id"])
    if existing:
        return False
    await self._user_repo.link_messenger(
        user_id=record["user_id"],
        messenger_type=record["messenger_type"],
        external_id=record["external_id"],
    )
    await self._linking_code_repo.delete(code)
    return True
```

- [ ] **Step 4: Run tests, commit**

```bash
make fix
git commit -m "feat: add account linking code generation and redemption"
```

### Task N+3: Add /link handlers to both bots

**Files:**
- Modify: `src/ugc_bot/bot/telegram/handlers/start.py` — add code entry handler
- Create: `src/ugc_bot/bot/max/handlers/linking.py` — /link command + code entry
- Tests for both

---

## Phase 7: NotificationService for broadcast

### Task N+4: Create NotificationService

**Files:**
- Create: `src/ugc_bot/application/services/notification_service.py`
- Modify: `src/ugc_bot/application/ports.py` — add NotificationPort if needed
- Test: `tests/unit/application/services/test_notification_service.py`

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.asyncio
async def test_notify_user_both_messengers():
    """When user has both telegram_id and max_id, notify both."""
    telegram_client = AsyncMock()
    max_client = AsyncMock()
    service = NotificationService(
        telegram_client=telegram_client,
        max_client=max_client,
    )
    user = make_user(telegram_id="123", max_id="456")
    await service.notify_user(user, text="New order!")
    telegram_client.send_text.assert_called_once()
    max_client.send_text.assert_called_once()


@pytest.mark.asyncio
async def test_notify_user_telegram_only():
    """When user has only telegram_id, notify Telegram only."""
    telegram_client = AsyncMock()
    max_client = AsyncMock()
    service = NotificationService(
        telegram_client=telegram_client,
        max_client=max_client,
    )
    user = make_user(telegram_id="123", max_id=None)
    await service.notify_user(user, text="New order!")
    telegram_client.send_text.assert_called_once()
    max_client.send_text.assert_not_called()
```

- [ ] **Step 2: Implement NotificationService**
- [ ] **Step 3: Wire into container**
- [ ] **Step 4: Replace direct notification calls in schedulers/workers**
- [ ] **Step 5: Run full checks, commit**
