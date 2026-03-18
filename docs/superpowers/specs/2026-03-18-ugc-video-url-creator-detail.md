# UGC Video URL — Creator Detail Screen

**Date:** 2026-03-18
**Status:** Approved

## Summary

Managers need to attach a UGC video link (shot by a creator for a specific order) via the
mini app. The link is stored on the existing `offer_dispatches` record. On first save, the
bot notifies both the creator and the advertiser.

## User Flow

Mini app → Менеджер → Мои заказы → Детали заказа → Креаторы в заказе → *click creator* →
Детали креатора → enter URL → Сохранить

## Decisions

| Question | Answer |
|---|---|
| Who sets the link? | Manager only (via mini app) |
| Notifications on save? | Creator + advertiser (always the advertiser, even if manager assigned) |
| Repeat saves? | Allowed; notifications sent only on the first save (when URL was previously `NULL`) |
| Storage | New column on `offer_dispatches`; no new table |

---

## Data Layer

### Migration

New Alembic migration file: `0076_add_ugc_video_url_offer_dispatches.py`

```sql
ALTER TABLE offer_dispatches
    ADD COLUMN ugc_video_url TEXT NULL;
```

### Domain Entity

`OfferDispatch` (`domain/entities.py`) — add optional field:

```python
ugc_video_url: str | None = None
```

Per the existing pattern (`frozen=True` dataclass), all updates use
`dataclasses.replace(dispatch, ugc_video_url=url)`.

### ORM Model

`OfferDispatchModel` (`infrastructure/db/models.py`) — add mapped column:

```python
ugc_video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
```

### ORM Mapper

Update `_to_offer_dispatch_entity` (or the equivalent mapper function in
`infrastructure/db/repositories/interactions.py`) to pass `ugc_video_url` when
constructing the `OfferDispatch` entity. Omitting this will silently drop the field
from all returned entities.

---

## Repository

### New port method (`application/ports.py`)

Add to the `OfferDispatchRepository` ABC:

```python
@abstractmethod
async def get_by_order_and_blogger(
    self,
    order_id: UUID,
    blogger_id: UUID,
    session: object | None = None,
) -> OfferDispatch | None: ...

@abstractmethod
async def set_ugc_video_url(
    self,
    order_id: UUID,
    blogger_id: UUID,
    url: str | None,
    session: object | None = None,
) -> None: ...
```

`get_by_order_and_blogger` is needed by the API to read the current `ugc_video_url`
before saving (to detect first-save and trigger notifications).

### SQLAlchemy implementation (`infrastructure/db/repositories/interactions.py`)

```python
async def get_by_order_and_blogger(
    self,
    order_id: UUID,
    blogger_id: UUID,
    session: object | None = None,
) -> OfferDispatch | None:
    async with _resolve_session(self.session_factory, session) as s:
        result = await s.execute(
            select(OfferDispatchModel).where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
        )
        row = result.scalar_one_or_none()
        return _to_offer_dispatch_entity(row) if row else None

async def set_ugc_video_url(
    self,
    order_id: UUID,
    blogger_id: UUID,
    url: str | None,
    session: object | None = None,
) -> None:
    async with _resolve_session(self.session_factory, session) as s:
        await s.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            .values(ugc_video_url=url, updated_at=datetime.now(timezone.utc))
        )
```

### In-memory implementation (`infrastructure/memory_repositories.py`)

Both methods operate on the in-memory dict of `OfferDispatch` instances
(frozen dataclasses replaced via `dataclasses.replace`).

---

## API

Both endpoints follow the existing mini-app pattern: POST with `init_data` in the request
body for Telegram WebApp auth. Manager must be assigned to the order
(existing `is_manager_for_order` check).

### `CreatorItem` response model — add `blogger_id`

The existing `CreatorItem` must be extended with `blogger_id: str` so the frontend can
construct the detail URL:

```python
class CreatorItem(BaseModel):
    blogger_id: str          # new
    instagram_url: str | None = None
    telegram: str | None = None
```

### `POST /api/manager/orders/{order_id}/creators/{blogger_id}`

Returns creator profile and current video URL.

**Request body:**
```json
{ "init_data": "<telegram-init-data>" }
```

**Response:**
```json
{
  "blogger_id": "uuid-string",
  "instagram_url": "https://instagram.com/creator" | null,
  "telegram": "@creator_tg" | null,
  "ugc_video_url": "https://drive.google.com/..." | null
}
```

Response model: `CreatorDetailResponse(BaseModel)`.

### `POST /api/manager/orders/{order_id}/creators/{blogger_id}/ugc-video`

Saves URL; sends notifications on first save.

**Request body:**
```json
{ "init_data": "<telegram-init-data>", "url": "https://..." }
```

`url` is validated as `AnyHttpUrl` by Pydantic (must be a valid HTTP/HTTPS URL, non-empty).
Pydantic coerces it to `str` before passing to the repo.

**Response:**
```json
{ "ok": true }
```

**Logic:**
1. Validate manager is assigned to the order (`is_manager_for_order`).
2. Fetch order via `order_repo.get_by_id(order_id)`.
   - If `None`: return HTTP 404.
3. Call `dispatch_repo.get_by_order_and_blogger(order_id, blogger_id)`.
   - If `None`: return HTTP 404.
4. Read `dispatch.ugc_video_url` (previous value).
5. Call `dispatch_repo.set_ugc_video_url(order_id, blogger_id, str(url))`.
6. If previous value was `None` (first save):
   a. Obtain `messenger_client = dispatcher["messenger_client"]`.
   b. Fetch creator `User` via `user_repo.get_by_id(blogger_id)`.
   c. Fetch advertiser `User` via `user_repo.get_by_id(order.advertiser_id)`.
   d. Determine creator locale: `creator.language or "ru"`.
   e. Determine advertiser locale: `advertiser.language or "ru"` (if advertiser found).
   f. Fetch texts via `bot_texts_service.get(key, locale)` with `DEFAULT_TEXTS` fallback.
   g. Send bot messages via `send_with_retry(messenger_client, chat_id=user.external_id, ...)`.
      Use `retries=3, delay_seconds=1` (existing convention in handlers).
   - If creator not found: log warning, skip creator notification.
   - If advertiser not found: log warning, skip advertiser notification.

---

## Notifications

Sent **only on first save** (previous `ugc_video_url` was `None`).
Text fetched via `bot_texts_service.get(key, locale)`.
Sent via existing `send_with_retry` helper.

### To creator

Bot text key: `msg_ugc_video_saved_creator`

Default (ru): `"✅ Ваше видео принято менеджером и сохранено."`
Default (en): `"✅ Your video has been accepted by the manager and saved."`

### To advertiser

Bot text key: `msg_ugc_video_saved_advertiser`

Default (ru): `"✅ Креатор {telegram} успешно выполнил заказ!\nСсылка на видео: {url}"`
Default (en): `"✅ Creator {telegram} has successfully completed the order!\nVideo link: {url}"`

`{telegram}` — formatted as `@{creator.telegram}` if `creator.telegram` is not `None`,
else `creator.username` (no `@` prefix, since `username` is an internal name, not a handle).
`{url}` — the saved video URL string.
`chat_id` for each notification — `user.external_id` (Telegram chat ID, stored as `str`).

---

## Frontend (`miniapp/app.html`)

### `CreatorItem` list — add `blogger_id`

In `loadManagerCreators`, each creator `<li>` becomes a clickable button.
`blogger_id` is included in each item's data from the API response and passed to
`openCreatorDetail`.

### New screen `#screen-creator-detail`

```html
<div id="screen-creator-detail" class="screen">
    <h1>Детали креатора</h1>
    <div id="creator-detail-body"></div>
    <button id="creator-detail-back" class="btn-secondary">Назад</button>
</div>
```

Dynamic content rendered by JS into `#creator-detail-body`:
- Instagram URL row (📸 icon, clickable link or «—»)
- Telegram row (Telegram SVG icon, clickable link or «—»)
- Section label «UGC-видео для этого заказа»
- `<input type="url" id="ugc-video-input">` pre-filled with current `ugc_video_url` (empty if null)
- Hint: «Ссылка на готовое видео (Google Drive, YouTube, и т.д.)»
- «Сохранить» button

### JavaScript additions

**`openCreatorDetail(orderId, bloggerId)`**
- Sets `window._mgrCurrentBloggerId = bloggerId`
- Calls `POST /api/manager/orders/{orderId}/creators/{bloggerId}`
- Renders profile info and video URL input
- Shows `#screen-creator-detail`

**`saveCreatorUgcVideo(orderId, bloggerId)`**
- Reads value from `#ugc-video-input`
- Calls `POST /api/manager/orders/{orderId}/creators/{bloggerId}/ugc-video`
- Shows success toast on `ok: true`; shows error toast on failure

**Back button `#creator-detail-back`**
- Returns to `#screen-manager-creators`

---

## Testing

### Unit tests (`tests/unit/test_ugc_video_url.py`)

- `test_in_memory_set_and_get_ugc_video_url` — InMemory repo stores and retrieves URL.
- `test_first_save_sends_notifications` — mock `bot_texts_service` and `messenger_client`;
  assert creator and advertiser each receive one message with correct content.
- `test_second_save_no_notifications` — URL already set; assert no messages sent.
- `test_creator_not_found_skips_notification` — creator User is None; assert only
  advertiser is notified (no exception raised).
- `test_advertiser_not_found_skips_notification` — advertiser User is None; assert only
  creator is notified.
- `test_dispatch_not_found_returns_404` — `get_by_order_and_blogger` returns `None`;
  assert HTTP 404 is raised.

### Integration test (`tests/integration/`)

- `test_set_ugc_video_url_persists` — real SQLAlchemy repo; call `set_ugc_video_url`,
  then `get_by_order_and_blogger`; assert `ugc_video_url` matches saved value.

### Existing suite

Run `make fix` after implementation; 98% coverage threshold must pass.
