# Max Messenger Support — Design Spec

**Date:** 2026-03-25
**Status:** Approved

## Goal

Add Max messenger as a second parallel messenger alongside Telegram with full handler parity (excluding payments and miniapp). Users can be linked to both messengers simultaneously.

## Scope

### In scope
- Full handler parity with Telegram (all bot scenarios)
- Max webhook entry point (separate process, port 8003)
- Max infrastructure adapters (client, event adapter, state store)
- Thin Max handlers calling shared services
- User account linking between Telegram and Max (one-time code flow)
- Notifications sent to all linked messengers
- Refactor existing Telegram handlers to be thin (logic → services)

### Out of scope (deferred)
- Payments in Max (Max API does not support payments)
- Miniapp in Max (separate auth scheme, deferred)
- FSM state migration between messengers
- Third messenger support (architecture ready, not planned)
- Unified inbox in admin panel

## Architecture Overview

```
Entry points:
  telegram_webhook_app.py (:9999)  — existing, no changes
  instagram_webhook_app.py (:8002) — existing, no changes
  admin/app.py (:8001)             — existing, no changes
  max_webhook_app.py (:8003)       — NEW

bot/
├── telegram/              # Existing handlers, refactored to thin
│   ├── handlers/
│   ├── middleware/
│   └── router.py
├── max/                   # NEW — thin handlers
│   ├── handlers/
│   ├── middleware/
│   └── router.py
└── shared/
    └── keyboards.py       # Shared keyboard DTOs

infrastructure/messenger/
├── telegram/              # Existing, no changes
│   ├── adapter.py
│   ├── client.py
│   ├── state.py
│   └── payments.py
└── max/                   # NEW
    ├── adapter.py         # MaxEventAdapter implements MessengerEventAdapter
    ├── client.py          # MaxMessengerClient implements MessengerClient
    └── state.py           # MaxRedisStateStore implements StateStore
```

## Design Decisions

### 1. Thin handlers + thick services (Hybrid approach)

Handlers are messenger-specific but thin (5-15 lines each). All business logic lives in services. This avoids:
- Building a custom framework abstraction over aiogram (leaky abstraction)
- Duplicating business logic across messengers
- Losing messenger-specific features

Pattern:
```python
# bot/telegram/handlers/orders.py (~10 lines)
@router.callback_query(F.data.startswith("order:"))
async def order_detail(callback, order_service, messenger_client, event_adapter):
    incoming = event_adapter.from_callback(callback)
    result = await order_service.get_order_detail(incoming.user_id, order_id, incoming.locale)
    await messenger_client.edit_text(
        chat_id=incoming.chat_id, message_id=incoming.message_id,
        text=result.text, keyboard=result.keyboard
    )

# bot/max/handlers/orders.py (~10 lines, same pattern)
@router.callback(lambda c: c.callback_data.startswith("order:"))
async def order_detail(incoming, order_service, messenger_client):
    result = await order_service.get_order_detail(incoming.user_id, order_id, incoming.locale)
    await messenger_client.edit_text(
        chat_id=incoming.chat_id, message_id=incoming.message_id,
        text=result.text, keyboard=result.keyboard
    )
```

### 2. Separate entry point per messenger

`max_webhook_app.py` runs as a separate process/container (port 8003). Reasons:
- Fault isolation (Max downtime does not affect Telegram)
- Independent scaling
- Independent deployment
- Follows existing pattern (`telegram_webhook_app.py`, `instagram_webhook_app.py`)

### 3. No aiogram for Max — raw HTTP + custom router

Max has no Python SDK. Use `aiohttp.ClientSession` for API calls. Custom lightweight router for dispatching incoming events.

### 4. Redis-based FSM for Max

Max has no built-in FSM. Implement `MaxRedisStateStore` using the same Redis instance already used for aiogram FSM storage.

## Infrastructure Adapters

### MaxMessengerClient

Implements `MessengerClient` protocol. Communicates with `https://platform-api.max.ru`.

Key endpoints:
- `POST /messages?chat_id={id}` — send message
- `PUT /messages?message_id={id}` — edit message
- `DELETE /messages?message_id={id}` — delete message

Authentication: `Authorization: {token}` header.
Rate limit: 30 req/s.

Keyboard mapping: `Button` DTOs → Max `InlineKeyboardAttachment` with button types: `callback`, `link`, `request_contact`, `request_geo_location`, `open_app`.

### MaxEventAdapter

Implements `MessengerEventAdapter` protocol. Converts raw Max webhook JSON into neutral DTOs (`IncomingMessage`, `IncomingCallback`).

Max update types:
- `message_created` → `IncomingMessage`
- `message_callback` → `IncomingCallback`

### MaxRedisStateStore

Implements `StateStore` protocol. Keys: `max_fsm:{chat_id}:{user_id}` for state, `max_fsm:{chat_id}:{user_id}:data` for FSM data.

## Max Router

Lightweight router for dispatching Max events without a framework:

```python
class MaxRouter:
    def message(self, filter_fn):
        """Decorator: @router.message(lambda m: m.text == "/start")"""

    def callback(self, filter_fn):
        """Decorator: @router.callback(lambda c: c.callback_data.startswith("order:"))"""

    async def route_message(self, incoming: IncomingMessage, deps: dict): ...
    async def route_callback(self, incoming: IncomingCallback, deps: dict): ...
```

## Entry Point — max_webhook_app.py

FastAPI application on port 8003:
- Lifespan: creates `MaxMessengerClient`, `MaxEventAdapter`, Redis connection, container with bot services
- `POST /webhook/max` — receives Max updates, routes to handlers
- Webhook registration with Max API on startup

## Config

New config section:

```python
class MaxBotConfig(BaseSettings):
    token: str = Field(alias="MAX_BOT_TOKEN")
    webhook_url: str = Field(alias="MAX_WEBHOOK_URL")
```

Added to `AppConfig` as `max_bot: MaxBotConfig`.

## User Account Linking

### Data model

No DB migration needed. `User` entity already has optional `telegram_id` and `max_id` fields.

### Linking flow

1. User registered in Telegram (`telegram_id="123"`)
2. User starts bot in Max → Max provides `max_id="456"`
3. Bot: "Link to existing account?"
4. User confirms → bot generates one-time code
5. User enters code in Telegram bot
6. System sets `user.max_id = "456"`

### Service changes

```python
class UserRoleService:
    async def find_user_by_messenger(
        self, messenger_type: MessengerType, external_id: str
    ) -> User | None: ...

    async def link_messenger(
        self, user_id: UUID, messenger_type: MessengerType, external_id: str
    ) -> None: ...
```

## Notifications

`NotificationService` sends to all linked messengers:

```python
class NotificationService:
    async def notify_user(self, user: User, text: str, keyboard=None):
        if user.telegram_id:
            await self.telegram_client.send_text(chat_id=user.telegram_id, ...)
        if user.max_id:
            await self.max_client.send_text(chat_id=user.max_id, ...)
```

Requires injecting both `MessengerClient` instances into `NotificationService`.

## Docker

New service in docker-compose:

```yaml
max_bot:
  build: .
  command: uvicorn ugc_bot.max_webhook_app:app --host 0.0.0.0 --port 8003
  ports:
    - "8003:8003"
  env_file: .env
  depends_on:
    - postgres
    - redis
```

## Refactoring Summary

| Area | Change |
|------|--------|
| `bot/` → `bot/telegram/` | Move existing handlers into subdirectory |
| Telegram handlers | Refactor to thin (logic → services) |
| Services | Add `ServiceResponse` return pattern where missing |
| `UserRoleService` | Add `find_user_by_messenger()`, `link_messenger()` |
| `NotificationService` | Send to all linked messengers |
| `config.py` | Add `MaxBotConfig` |
| docker-compose | Add `max_bot` service |

## What stays unchanged

- `domain/` — already messenger-agnostic
- `application/messenger/ports.py` — protocols already defined
- `infrastructure/db/` — no new migrations needed
- `admin/` — no changes
- `miniapp/` — deferred
