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
- User account linking between Telegram and Max (bidirectional, one-time code flow)
- Notifications sent to all linked messengers
- Refactor existing Telegram handlers to be thin (logic → services)
- Media abstraction layer for cross-messenger file references
- Testing: fakes, unit tests, integration tests for all new code

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
    order_id = UUID(incoming.callback_data.split(":")[1])
    result = await order_service.get_order_detail(incoming.user_id, order_id, incoming.locale)
    await messenger_client.edit_text(
        chat_id=incoming.chat_id, message_id=incoming.message_id,
        text=result.text, keyboard=result.keyboard
    )

# bot/max/handlers/orders.py (~10 lines, same pattern)
@router.callback(lambda c: c.callback_data.startswith("order:"))
async def order_detail(incoming, order_service, messenger_client):
    order_id = UUID(incoming.callback_data.split(":")[1])
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

Max has no built-in FSM. Implement `MaxRedisStateStore` using the same Redis instance already used for aiogram FSM storage. A new `MaxRedisStateStore` instance is created per incoming request in the webhook handler middleware, scoped to the current `(chat_id, user_id)` from the parsed event, then passed to the handler as a dependency.

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

**Text formatting:** Max uses its own markup format. `MaxMessengerClient` strips or converts `parse_mode` values (`HTML`, `Markdown`) from Telegram format to Max-compatible format. Conversion logic lives inside the client — services remain unaware of formatting differences.

**Reply/Remove keyboards:** If Max does not support reply keyboards, `MaxMessengerClient` silently ignores `REPLY` and `REMOVE` keyboard types (sends message without keyboard). Documented in client code.

**`send_invoice` (payments):** Raises `NotImplementedError` with a clear message. Callers that send invoices must check `messenger_type` before calling, or catch the error. This will be resolved when payments are added.

**Error handling:** Retry on 5xx and network errors (up to 3 attempts with exponential backoff). On 429 (rate limit) — respect `Retry-After` header. On 403/blocked — log and mark user as unreachable (same pattern as Telegram's `TelegramForbiddenError` handling). Error codes and retry behavior documented in client.

### MaxEventAdapter

Implements `MessengerEventAdapter` protocol. Converts raw Max webhook JSON into neutral DTOs (`IncomingMessage`, `IncomingCallback`).

Max update types:
- `message_created` → `IncomingMessage`
- `message_callback` → `IncomingCallback`

### MaxRedisStateStore

Implements `StateStore` protocol. Keys: `max_fsm:{chat_id}:{user_id}` for state, `max_fsm:{chat_id}:{user_id}:data` for FSM data.

**Per-request scoping:** The webhook handler parses the incoming event first (extracting `chat_id` and `user_id`), then constructs `MaxRedisStateStore(redis, chat_id, user_id)` and passes it to the router as part of the handler dependencies. This mirrors how aiogram's `FSMContext` is scoped per-update automatically.

```python
# In max_webhook_app.py webhook handler:
async def handle_max_webhook(request: Request):
    data = await request.json()
    incoming = event_adapter.parse(data)  # extract chat_id, user_id
    state_store = MaxRedisStateStore(redis, incoming.chat_id, incoming.user_id)
    deps = {**bot_services, "state_store": state_store, "messenger_client": messenger_client}
    await max_router.route(data["update_type"], incoming, deps)
```

## Max Router and DI

Lightweight router for dispatching Max events without a framework.

**Dependency injection:** Max handlers receive dependencies as a `deps: dict` from the router. Each handler explicitly picks what it needs from `deps`. This is simpler than aiogram's magic DI but sufficient for thin handlers.

```python
class MaxRouter:
    def message(self, filter_fn):
        """Decorator: @router.message(lambda m: m.text == "/start")"""

    def callback(self, filter_fn):
        """Decorator: @router.callback(lambda c: c.callback_data.startswith("order:"))"""

    async def route_message(self, incoming: IncomingMessage, deps: dict): ...
    async def route_callback(self, incoming: IncomingCallback, deps: dict): ...
```

**Handler signature for Max:**
```python
# Max handlers receive IncomingMessage/IncomingCallback (already parsed) + deps dict
async def start_handler(incoming: IncomingMessage, deps: dict):
    user_service: UserRoleService = deps["user_role_service"]
    messenger_client: MessengerClient = deps["messenger_client"]
    state_store: StateStore = deps["state_store"]
    # ... thin logic, delegate to service
```

## Entry Point — max_webhook_app.py

FastAPI application on port 8003:
- Lifespan: creates `MaxMessengerClient`, `MaxEventAdapter`, Redis connection, container with bot services
- `POST /webhook/max` — receives Max updates, parses event, creates per-request StateStore, routes to handlers
- Webhook registration with Max API on startup

## Config

New config section:

```python
class MaxBotConfig(BaseSettings):
    token: str = Field(alias="MAX_BOT_TOKEN")
    webhook_url: str = Field(alias="MAX_WEBHOOK_URL")
```

Added to `AppConfig` as `max_bot: MaxBotConfig`.

## Media Abstraction

### Problem

Telegram `file_id` values are Telegram-internal. If a photo is uploaded via Telegram and stored as `file_id`, Max cannot use it. Cross-messenger media sharing requires a neutral format.

### Solution

Introduce a `MediaStorage` service that stores media as URLs (S3/local storage). When a photo is uploaded:
1. Handler downloads the file from the source messenger (Telegram `getFile` API, Max file download API)
2. Uploads to shared storage (S3 or local filesystem)
3. Stores the URL in the database (new `media_url` field alongside existing `file_id`)

When sending a photo:
- If the recipient is on the same messenger as the uploader → use native `file_id` (fast, no re-upload)
- If cross-messenger → use `media_url`, let `MessengerClient` download and send

This avoids re-uploading for same-messenger cases while supporting cross-messenger scenarios.

**Migration:** Add `media_url: str | None` column to relevant tables (orders, products). Backfill optional — existing Telegram-only photos continue to work via `file_id`.

## User Account Linking

### Data model

Migration needed: new `linking_codes` table for one-time codes.

```sql
CREATE TABLE linking_codes (
    code VARCHAR(6) PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(user_id),
    messenger_type VARCHAR(20) NOT NULL,  -- which messenger to link
    external_id VARCHAR(255) NOT NULL,     -- ID in that messenger
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL        -- TTL: created_at + 10 minutes
);
```

### Linking flow (bidirectional)

**Direction 1: Telegram user links Max**
1. User registered in Telegram (`telegram_id="123"`)
2. User starts bot in Max → system finds no user with `max_id="456"`
3. Bot in Max: "Want to link to existing account? Enter /link"
4. User sends `/link` → bot generates 6-digit code (TTL: 10 minutes), stores in `linking_codes`
5. Bot: "Enter this code in your Telegram bot: `483920`"
6. User sends code in Telegram bot → system validates code, checks not expired
7. System sets `user.max_id = "456"`, deletes the code

**Direction 2: Max user links Telegram**
Same flow, reversed — code generated in Telegram, entered in Max.

**Conflict handling:**
- If `external_id` is already linked to another user → reject with error message
- If code is expired → reject, ask to generate new one
- If code is wrong → reject, allow retry (max 3 attempts, then invalidate code)
- Race condition: codes are unique (PK), `link_messenger` uses DB transaction with row-level lock on user

### Service changes

```python
class UserRoleService:
    async def find_user_by_messenger(
        self, messenger_type: MessengerType, external_id: str
    ) -> User | None: ...

    async def generate_linking_code(
        self, user_id: UUID, messenger_type: MessengerType, external_id: str
    ) -> str: ...

    async def redeem_linking_code(
        self, code: str, user_id: UUID
    ) -> bool: ...
```

## Notifications

### Response vs broadcast distinction

Two different notification paths:

1. **Handler response** — reply to user's action in the current messenger only. This is what handlers do: user presses button in Telegram → response goes to Telegram only.

2. **Broadcast notification** — system-initiated notification (new order, status change, scheduled reminder). Goes to all linked messengers.

```python
class NotificationService:
    async def notify_user(self, user: User, text: str, keyboard=None):
        """Broadcast: send to ALL linked messengers."""
        if user.telegram_id:
            await self.telegram_client.send_text(chat_id=user.telegram_id, ...)
        if user.max_id:
            await self.max_client.send_text(chat_id=user.max_id, ...)
```

Handlers do NOT call `notify_user` — they use their own `messenger_client` to reply in the current messenger.

## Handler Refactoring Strategy

### Scope assessment

The existing 19 handler files in `bot/handlers/` vary in complexity:
- **Large handlers** (200-700 lines): `start.py`, `creator.py`, `advertiser.py` — contain significant business logic (referral parsing, country detection, FSM orchestration)
- **Medium handlers** (50-200 lines): order flows, profile, settings
- **Small handlers** (< 50 lines): simple commands, help

### Approach: incremental, handler-by-handler

1. **Phase 1: Move `bot/` → `bot/telegram/`** — pure file move, update all imports. No logic changes. All tests must pass after this step.

2. **Phase 2: Extract service methods** — for each handler file, extract business logic into the corresponding service. Start with the simplest handlers (small), end with the complex ones (start.py). Each handler extraction is a separate commit — Telegram bot remains functional throughout.

3. **Phase 3: Write Max handlers** — using the now-thin Telegram handlers as templates, write Max handlers that call the same services.

### ServiceResponse pattern

Services return a dataclass with everything the handler needs to send:

```python
@dataclass
class ServiceResponse:
    text: str
    keyboard: list[list[Button]] | None = None
    photo_url: str | None = None
    next_state: str | None = None  # FSM state to transition to
    state_data: dict | None = None  # data to store in FSM

@dataclass
class MultiResponse:
    """For scenarios requiring multiple messages."""
    responses: list[ServiceResponse]
```

Handler responsibility after refactoring:
1. Parse incoming event via `EventAdapter`
2. Call service method → get `ServiceResponse`
3. Send response via `MessengerClient`
4. Update FSM state if `next_state` is set

### Import path changes

Moving `bot/` → `bot/telegram/` changes import paths. Affected:
- `telegram_webhook_app.py` — router imports
- `app.py` — dispatcher setup
- All test files in `tests/` referencing `bot.handlers.*`
- Container if it references handlers

Mitigation: single commit with bulk rename, verify with `make all`.

## Utility updates

`bot/utils.py` contains `resolve_messenger_dependencies()` which hardcodes `TelegramEventAdapter` fallback. This function moves to `bot/telegram/utils.py`. Max handlers use their own DI mechanism (deps dict) and do not use this function.

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

## Testing Strategy

### New fakes
- `MaxMessengerClientFake` — in-memory implementation of `MessengerClient` for Max (records sent messages)
- `MaxRedisStateStoreFake` — in-memory FSM state store

### Unit tests
- `MaxRouter` — routing logic, filter matching
- `MaxEventAdapter` — JSON → DTO conversion for all event types
- `MaxMessengerClient` — keyboard building, text format conversion (mock HTTP)
- `MaxRedisStateStore` — state get/set/clear (mock Redis or fakeredis)
- Account linking — code generation, redemption, expiry, conflicts
- All refactored services — `ServiceResponse` correctness

### Integration tests
- `max_webhook_app` — full webhook → handler → service flow (with test DB)
- Account linking end-to-end — generate code in one messenger, redeem in another
- Cross-messenger notifications — verify both clients called

### Coverage
All new code must meet the 98% threshold. Refactored handlers maintain existing coverage.

## Rollout Plan

### Phase 1: Foundation (no user-facing changes)
1. Move `bot/` → `bot/telegram/`, fix imports — verify with `make all`
2. Add `MaxBotConfig` to config
3. Create `infrastructure/messenger/max/` adapters
4. Create `bot/max/router.py`

### Phase 2: Refactor Telegram handlers (Telegram continues working)
5. Extract service methods handler-by-handler (simplest first)
6. Each extraction = separate commit, `make all` after each

### Phase 3: Max bot
7. Write Max handlers (using thin Telegram handlers as templates)
8. Create `max_webhook_app.py`
9. Add Docker service
10. Deploy and test with Max webhook

### Phase 4: Account linking
11. Create `linking_codes` migration
12. Implement linking flow in both bots
13. Update `NotificationService` for broadcast to all messengers

Rollback: each phase is independently deployable. If Max breaks, disable `max_bot` container — Telegram unaffected.

## What stays unchanged

- `domain/` — already messenger-agnostic
- `application/messenger/ports.py` — protocols already defined
- `infrastructure/db/repositories.py` — no changes (queries use `messenger_type` + `external_id`)
- `admin/` — no changes
- `miniapp/` — deferred
