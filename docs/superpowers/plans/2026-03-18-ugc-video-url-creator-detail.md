# UGC Video URL — Creator Detail Screen Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a UGC video URL field to the manager's creator detail screen in the mini app, stored in `offer_dispatches`, with bot notifications to creator and advertiser on first save.

**Architecture:** Adds one nullable column to `offer_dispatches`, two new repo methods (get + set), two new API endpoints, and a new frontend screen. On first save the API sends bot notifications directly using `send_with_retry`. No new services or tables needed.

**Tech Stack:** Python 3.13, SQLAlchemy 2, FastAPI, Pydantic v2, aiogram 3, Alembic, plain JS (no framework).

---

## File Map

| File | Action |
|------|--------|
| `src/ugc_bot/domain/entities.py` | Modify — add `ugc_video_url` field to `OfferDispatch` |
| `src/ugc_bot/infrastructure/db/models.py` | Modify — add `ugc_video_url` column to `OfferDispatchModel` |
| `src/ugc_bot/infrastructure/db/repositories/interactions.py` | Modify — update mapper + add 2 methods |
| `src/ugc_bot/application/ports.py` | Modify — add 2 abstract methods to `OfferDispatchRepository` |
| `src/ugc_bot/infrastructure/memory_repositories.py` | Modify — implement 2 new methods in `InMemoryOfferDispatchRepository` |
| `src/ugc_bot/bot/texts/defaults.py` | Modify — add 2 text keys for all locales |
| `src/ugc_bot/miniapp/api.py` | Modify — extend `CreatorItem` + add 2 endpoints |
| `src/ugc_bot/miniapp/app.html` | Modify — add creator detail screen + JS |
| `src/ugc_bot/infrastructure/db/migrations/versions/0076_add_ugc_video_url_offer_dispatches.py` | Create — Alembic migration |
| `tests/unit/test_ugc_video_url.py` | Create — unit tests |

---

## Chunk 1: Data Layer

### Task 1: Add `ugc_video_url` to domain entity and ORM

**Files:**
- Modify: `src/ugc_bot/domain/entities.py`
- Modify: `src/ugc_bot/infrastructure/db/models.py`
- Modify: `src/ugc_bot/infrastructure/db/repositories/interactions.py`

- [ ] **Step 1.1 — Add field to `OfferDispatch`**

In `src/ugc_bot/domain/entities.py`, find the `OfferDispatch` dataclass (currently ends with `manager_id: Optional[UUID] = None`). Add one field after it:

```python
# BEFORE (last field):
    manager_id: Optional[UUID] = None

# AFTER:
    manager_id: Optional[UUID] = None
    ugc_video_url: Optional[str] = None
```

- [ ] **Step 1.2 — Add column to `OfferDispatchModel`**

In `src/ugc_bot/infrastructure/db/models.py`, find `OfferDispatchModel`. Add after the `manager_id` column:

```python
# BEFORE (last column in class):
    manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )

# AFTER:
    manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    ugc_video_url: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
```

`Text` is already imported in `models.py`.

- [ ] **Step 1.3 — Update ORM mapper**

In `src/ugc_bot/infrastructure/db/repositories/interactions.py`, find `_to_offer_dispatch_entity` and add the new field:

```python
# BEFORE:
def _to_offer_dispatch_entity(model: OfferDispatchModel) -> OfferDispatch:
    """Map offer dispatch ORM model to domain entity."""
    return OfferDispatch(
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        accepted=model.accepted,
        in_offer=model.in_offer,
        manager_id=model.manager_id,
    )

# AFTER:
def _to_offer_dispatch_entity(model: OfferDispatchModel) -> OfferDispatch:
    """Map offer dispatch ORM model to domain entity."""
    return OfferDispatch(
        order_id=model.order_id,
        blogger_id=model.blogger_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
        accepted=model.accepted,
        in_offer=model.in_offer,
        manager_id=model.manager_id,
        ugc_video_url=model.ugc_video_url,
    )
```

- [ ] **Step 1.4 — Verify typecheck passes**

```bash
uv run mypy src/ugc_bot/domain/entities.py src/ugc_bot/infrastructure/db/models.py src/ugc_bot/infrastructure/db/repositories/interactions.py
```

Expected: `Success: no issues found`

- [ ] **Step 1.5 — Commit**

```bash
git add src/ugc_bot/domain/entities.py src/ugc_bot/infrastructure/db/models.py src/ugc_bot/infrastructure/db/repositories/interactions.py
git commit -m "feat: add ugc_video_url field to OfferDispatch entity and ORM"
```

---

### Task 2: Alembic migration

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0076_add_ugc_video_url_offer_dispatches.py`

- [ ] **Step 2.1 — Create migration file**

```python
"""Add ugc_video_url column to offer_dispatches."""

import sqlalchemy as sa
from alembic import op

revision = "0076_add_ugc_video_url_offer_dispatches"
down_revision = "0075_drop_countries_locale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable ugc_video_url text column to offer_dispatches."""
    op.add_column(
        "offer_dispatches",
        sa.Column("ugc_video_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove ugc_video_url column from offer_dispatches."""
    op.drop_column("offer_dispatches", "ugc_video_url")
```

- [ ] **Step 2.2 — Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0076_add_ugc_video_url_offer_dispatches.py
git commit -m "feat: migration 0076 — add ugc_video_url to offer_dispatches"
```

---

### Task 3: Repository — port + implementations

**Files:**
- Modify: `src/ugc_bot/application/ports.py`
- Modify: `src/ugc_bot/infrastructure/db/repositories/interactions.py`
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py`

- [ ] **Step 3.1 — Write failing tests for in-memory repo**

Create `tests/unit/test_ugc_video_url.py`:

```python
"""Unit tests for UGC video URL feature."""

from uuid import UUID

import pytest

from ugc_bot.infrastructure.memory_repositories import (
    InMemoryOfferDispatchRepository,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000c00")
BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000c01")
ADV_ID = UUID("00000000-0000-0000-0000-000000000c02")


@pytest.mark.asyncio
async def test_get_by_order_and_blogger_returns_none_when_missing() -> None:
    repo = InMemoryOfferDispatchRepository()
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None


@pytest.mark.asyncio
async def test_get_by_order_and_blogger_returns_dispatch() -> None:
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.order_id == ORDER_ID
    assert result.blogger_id == BLOGGER_ID
    assert result.ugc_video_url is None


@pytest.mark.asyncio
async def test_set_ugc_video_url_stores_value() -> None:
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/video")
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.ugc_video_url == "https://example.com/video"


@pytest.mark.asyncio
async def test_set_ugc_video_url_can_update() -> None:
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/v1")
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/v2")
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.ugc_video_url == "https://example.com/v2"


@pytest.mark.asyncio
async def test_set_ugc_video_url_noop_when_dispatch_missing() -> None:
    """Should not raise if dispatch does not exist."""
    repo = InMemoryOfferDispatchRepository()
    await repo.set_ugc_video_url(ORDER_ID, BLOGGER_ID, "https://example.com/v")
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None
```

- [ ] **Step 3.2 — Run tests to confirm they fail**

```bash
uv run pytest tests/unit/test_ugc_video_url.py -v
```

Expected: `FAILED` — `AttributeError: 'InMemoryOfferDispatchRepository' object has no attribute 'get_by_order_and_blogger'`

- [ ] **Step 3.3 — Add abstract methods to port**

In `src/ugc_bot/application/ports.py`, find `OfferDispatchRepository` ABC and add two methods after `count_responses_by_order_and_manager`:

```python
    @abstractmethod
    async def get_by_order_and_blogger(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> Optional["OfferDispatch"]:
        """Fetch a single dispatch by order and blogger composite key."""

    @abstractmethod
    async def set_ugc_video_url(
        self,
        order_id: UUID,
        blogger_id: UUID,
        url: Optional[str],
        session: object | None = None,
    ) -> None:
        """Set ugc_video_url on the dispatch for order+blogger."""
```

`Optional` and `UUID` are already imported in `ports.py`.

- [ ] **Step 3.4 — Implement in SQLAlchemy repo**

In `src/ugc_bot/infrastructure/db/repositories/interactions.py`, add two methods to the concrete `OfferDispatchRepository` class after `count_responses_by_order_and_manager`:

```python
    async def get_by_order_and_blogger(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> OfferDispatch | None:
        """Fetch a single dispatch by order and blogger."""
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
        """Set ugc_video_url for a dispatch."""
        async with _resolve_session(self.session_factory, session) as s:
            await s.execute(
                update(OfferDispatchModel)
                .where(
                    OfferDispatchModel.order_id == order_id,
                    OfferDispatchModel.blogger_id == blogger_id,
                )
                .values(
                    ugc_video_url=url,
                    updated_at=datetime.now(timezone.utc),
                )
            )
```

`update` and `select` are already imported in this file.

- [ ] **Step 3.5 — Implement in InMemory repo**

In `src/ugc_bot/infrastructure/memory_repositories.py`, add two methods to `InMemoryOfferDispatchRepository` after `count_responses_by_order_and_manager`:

```python
    async def get_by_order_and_blogger(
        self,
        order_id: UUID,
        blogger_id: UUID,
        session: object | None = None,
    ) -> OfferDispatch | None:
        """Return dispatch by composite key or None."""
        return self._dispatches.get((order_id, blogger_id))

    async def set_ugc_video_url(
        self,
        order_id: UUID,
        blogger_id: UUID,
        url: str | None,
        session: object | None = None,
    ) -> None:
        """Update ugc_video_url on dispatch in memory."""
        key = (order_id, blogger_id)
        if key not in self._dispatches:
            return
        d = self._dispatches[key]
        self._dispatches[key] = replace(
            d,
            ugc_video_url=url,
            updated_at=datetime.now(timezone.utc),
        )
```

`replace` is already imported (`from dataclasses import replace`) in `memory_repositories.py`.

- [ ] **Step 3.6 — Run tests — expect pass**

```bash
uv run pytest tests/unit/test_ugc_video_url.py -v
```

Expected: `5 passed`

- [ ] **Step 3.7 — Verify typecheck**

```bash
uv run mypy src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/db/repositories/interactions.py src/ugc_bot/infrastructure/memory_repositories.py
```

Expected: `Success: no issues found`

- [ ] **Step 3.8 — Commit**

```bash
git add src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/db/repositories/interactions.py src/ugc_bot/infrastructure/memory_repositories.py tests/unit/test_ugc_video_url.py
git commit -m "feat: add get_by_order_and_blogger and set_ugc_video_url repo methods"
```

---

## Chunk 2: API Layer

### Task 4: Bot notification texts

**Files:**
- Modify: `src/ugc_bot/bot/texts/defaults.py`

- [ ] **Step 4.1 — Add text keys to DEFAULT_TEXTS**

In `src/ugc_bot/bot/texts/defaults.py`, find the `"ru"` dict and add near the contact/offer section (e.g., near `"msg_offer_contacts_header"`):

```python
        # UGC video notification
        "msg_ugc_video_saved_creator": "✅ Ваше видео принято менеджером и сохранено.",
        "msg_ugc_video_saved_advertiser": (
            "✅ Креатор {telegram} успешно выполнил заказ!\nСсылка на видео: {url}"
        ),
```

Find the `"en"` dict and add:

```python
        # UGC video notification
        "msg_ugc_video_saved_creator": "✅ Your video has been accepted by the manager and saved.",
        "msg_ugc_video_saved_advertiser": (
            "✅ Creator {telegram} has successfully completed the order!\nVideo link: {url}"
        ),
```

The `kk`, `be`, `uz` locales are auto-filled at the bottom of the file via the existing loop — no manual changes needed for them.

- [ ] **Step 4.2 — Verify no lint errors**

```bash
uv run ruff check src/ugc_bot/bot/texts/defaults.py
```

Expected: `All checks passed!`

- [ ] **Step 4.3 — Commit**

```bash
git add src/ugc_bot/bot/texts/defaults.py
git commit -m "feat: add ugc_video_saved text keys for creator and advertiser notifications"
```

---

### Task 5: API endpoints

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py`

- [ ] **Step 5.1 — Write failing tests for the notification helper**

Add to `tests/unit/test_ugc_video_url.py` at the bottom:

```python
from tests.helpers.factories import create_test_user
from tests.helpers.fakes import FakeMessengerClient
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


@pytest.mark.asyncio
async def test_first_save_notifies_creator_and_advertiser(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """On first save both creator and advertiser receive a message."""
    from ugc_bot.miniapp.api import _notify_ugc_video_saved

    user_repo = InMemoryUserRepository()
    creator = await create_test_user(
        user_repo,
        user_id=BLOGGER_ID,
        external_id="901",
        username="creator_user",
        telegram="creator_tg",
    )
    advertiser = await create_test_user(
        user_repo,
        user_id=ADV_ID,
        external_id="902",
        username="advertiser_user",
    )

    await _notify_ugc_video_saved(
        creator=creator,
        advertiser=advertiser,
        video_url="https://example.com/video",
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
    )

    creator_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "901"]
    adv_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "902"]
    assert len(creator_msgs) == 1
    assert "принято" in creator_msgs[0]["text"] or "accepted" in creator_msgs[0]["text"]
    assert len(adv_msgs) == 1
    assert "@creator_tg" in adv_msgs[0]["text"]
    assert "https://example.com/video" in adv_msgs[0]["text"]


@pytest.mark.asyncio
async def test_notify_creator_not_found_skips_creator_msg(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """When creator is None only advertiser gets notified."""
    from ugc_bot.miniapp.api import _notify_ugc_video_saved

    user_repo = InMemoryUserRepository()
    advertiser = await create_test_user(
        user_repo,
        user_id=ADV_ID,
        external_id="902",
        username="advertiser_user",
    )

    await _notify_ugc_video_saved(
        creator=None,
        advertiser=advertiser,
        video_url="https://example.com/video",
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
    )

    assert all(s["chat_id"] != "901" for s in messenger_client.sent_text)
    adv_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "902"]
    assert len(adv_msgs) == 1


@pytest.mark.asyncio
async def test_notify_advertiser_not_found_skips_advertiser_msg(
    bot_texts_service,
    messenger_client: FakeMessengerClient,
) -> None:
    """When advertiser is None only creator gets notified."""
    from ugc_bot.miniapp.api import _notify_ugc_video_saved

    user_repo = InMemoryUserRepository()
    creator = await create_test_user(
        user_repo,
        user_id=BLOGGER_ID,
        external_id="901",
        username="creator_user",
        telegram="creator_tg",
    )

    await _notify_ugc_video_saved(
        creator=creator,
        advertiser=None,
        video_url="https://example.com/video",
        messenger_client=messenger_client,
        bot_texts_service=bot_texts_service,
    )

    assert all(s["chat_id"] != "902" for s in messenger_client.sent_text)
    creator_msgs = [s for s in messenger_client.sent_text if s["chat_id"] == "901"]
    assert len(creator_msgs) == 1
```

- [ ] **Step 5.2 — Run notification tests — expect fail**

```bash
uv run pytest tests/unit/test_ugc_video_url.py::test_first_save_notifies_creator_and_advertiser -v
```

Expected: `FAILED` — `ImportError: cannot import name '_notify_ugc_video_saved'`

- [ ] **Step 5.3 — Add imports to `api.py`**

In `src/ugc_bot/miniapp/api.py`, add to the import block at the top:

```python
from typing import Any
from pydantic import AnyHttpUrl
from ugc_bot.bot.handlers.utils import send_with_retry
from ugc_bot.domain.entities import User as UserEntity
```

`Any` is **not** currently imported in `api.py` — it must be added explicitly.
`logger` is already defined at module level (`logger = logging.getLogger(__name__)`) — no change needed.

- [ ] **Step 5.4 — Add `_notify_ugc_video_saved` helper to `api.py`**

Add this function before the route definitions (near other helpers like `_ensure_user_and_get_id`):

```python
async def _notify_ugc_video_saved(
    creator: UserEntity | None,
    advertiser: UserEntity | None,
    video_url: str,
    messenger_client: Any,
    bot_texts_service: Any,
) -> None:
    """Send first-save notifications to creator and advertiser.

    Called only when ugc_video_url was previously None.
    Silently skips a recipient when their User record is None.
    """
    if creator is not None:
        locale = creator.language or "ru"
        text = await bot_texts_service.get("msg_ugc_video_saved_creator", locale)
        await send_with_retry(
            messenger_client,
            chat_id=creator.external_id,
            text=text,
            retries=3,
            delay_seconds=1.0,
            logger=logger,
            extra={"event": "ugc_video_saved_creator"},
        )
    if advertiser is not None:
        locale = advertiser.language or "ru"
        template = await bot_texts_service.get(
            "msg_ugc_video_saved_advertiser", locale
        )
        creator_handle = (
            f"@{creator.telegram}"
            if creator is not None and creator.telegram
            else (creator.username if creator is not None else "—")
        )
        text = template.format(telegram=creator_handle, url=video_url)
        await send_with_retry(
            messenger_client,
            chat_id=advertiser.external_id,
            text=text,
            retries=3,
            delay_seconds=1.0,
            logger=logger,
            extra={"event": "ugc_video_saved_advertiser"},
        )
```

- [ ] **Step 5.5 — Run notification tests — expect pass**

```bash
uv run pytest tests/unit/test_ugc_video_url.py -v
```

Expected: `8 passed`

- [ ] **Step 5.6 — Extend `CreatorItem` with `blogger_id`**

In `src/ugc_bot/miniapp/api.py`, find `CreatorItem`:

```python
# BEFORE:
class CreatorItem(BaseModel):
    """Creator summary for manager view."""

    instagram_url: str | None = None
    telegram: str | None = None

# AFTER:
class CreatorItem(BaseModel):
    """Creator summary for manager view."""

    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
```

- [ ] **Step 5.7 — Update existing `manager_creators` handler**

In `src/ugc_bot/miniapp/api.py`, find the `CreatorItem(...)` instantiation inside `manager_creators`:

```python
# BEFORE:
        creators.append(
            CreatorItem(
                instagram_url=profile.instagram_url if profile else None,
                telegram=user.telegram if user else None,
            )
        )

# AFTER:
        creators.append(
            CreatorItem(
                blogger_id=str(d.blogger_id),
                instagram_url=profile.instagram_url if profile else None,
                telegram=user.telegram if user else None,
            )
        )
```

- [ ] **Step 5.8 — Add request/response models**

In `src/ugc_bot/miniapp/api.py`, add after `ManagerCreatorsResponse`:

```python
class CreatorDetailRequest(BaseModel):
    """Request to fetch a single creator's detail."""

    init_data: str


class CreatorDetailResponse(BaseModel):
    """Creator profile and current UGC video URL."""

    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
    ugc_video_url: str | None = None


class UgcVideoRequest(BaseModel):
    """Request to save a UGC video URL."""

    init_data: str
    url: AnyHttpUrl
```

- [ ] **Step 5.9 — Check dispatcher key names**

Before writing the endpoints, verify the exact key names used in `dispatcher`:

```bash
grep -n "offer_dispatch_repo\|dispatch_repo\|order_repo" src/ugc_bot/container/service_factory.py src/ugc_bot/container/types.py
```

Use the exact key string found there in the endpoint code below.

- [ ] **Step 5.10 — Add `POST /manager/orders/{order_id}/creators/{blogger_id}` endpoint**

Add after the existing `manager_creators` endpoint in `src/ugc_bot/miniapp/api.py`:

```python
@router.post("/manager/orders/{order_id}/creators/{blogger_id}")
async def manager_creator_detail(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: CreatorDetailRequest,
) -> CreatorDetailResponse:
    """Return creator profile and current ugc_video_url for manager."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(status_code=403, detail="Not a manager for this order")

    # Use the key name confirmed in Step 5.9
    dispatch_repo = dispatcher["offer_dispatch_repo"]
    dispatch = await dispatch_repo.get_by_order_and_blogger(order_id, blogger_id)
    if dispatch is None:
        raise HTTPException(status_code=404, detail="Creator not found in this order")

    profile_service = dispatcher["profile_service"]
    user_repo = dispatcher["user_repo"]
    user = await user_repo.get_by_id(blogger_id)
    profile = await profile_service.get_blogger_profile(blogger_id)

    return CreatorDetailResponse(
        blogger_id=str(blogger_id),
        instagram_url=profile.instagram_url if profile else None,
        telegram=user.telegram if user else None,
        ugc_video_url=dispatch.ugc_video_url,
    )
```

- [ ] **Step 5.11 — Add `POST /manager/orders/{order_id}/creators/{blogger_id}/ugc-video` endpoint**

Add immediately after `manager_creator_detail`:

```python
@router.post("/manager/orders/{order_id}/creators/{blogger_id}/ugc-video")
async def manager_set_ugc_video(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: UgcVideoRequest,
) -> dict[str, bool]:
    """Save UGC video URL; on first save notifies creator and advertiser."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(status_code=403, detail="Not a manager for this order")

    # Use the key names confirmed in Step 5.9
    order_repo = dispatcher["order_repo"]
    order = await order_repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    dispatch_repo = dispatcher["offer_dispatch_repo"]
    dispatch = await dispatch_repo.get_by_order_and_blogger(order_id, blogger_id)
    if dispatch is None:
        raise HTTPException(status_code=404, detail="Creator not found in this order")

    previous_url = dispatch.ugc_video_url
    url_str = str(body.url)
    await dispatch_repo.set_ugc_video_url(order_id, blogger_id, url_str)

    if previous_url is None:
        user_repo = dispatcher["user_repo"]
        messenger_client = dispatcher["messenger_client"]
        bot_texts_service = dispatcher["bot_texts_service"]
        creator = await user_repo.get_by_id(blogger_id)
        advertiser = await user_repo.get_by_id(order.advertiser_id)
        await _notify_ugc_video_saved(
            creator=creator,
            advertiser=advertiser,
            video_url=url_str,
            messenger_client=messenger_client,
            bot_texts_service=bot_texts_service,
        )

    return {"ok": True}
```

- [ ] **Step 5.12 — Run full typecheck**

```bash
uv run mypy src/ugc_bot/miniapp/api.py
```

Expected: `Success: no issues found`

- [ ] **Step 5.13 — Run lint and format**

```bash
uv run ruff format src/ugc_bot/miniapp/api.py && uv run ruff check src/ugc_bot/miniapp/api.py
```

Expected: `All checks passed!`

- [ ] **Step 5.14 — Run tests**

```bash
uv run pytest tests/unit/test_ugc_video_url.py tests/bot/handlers/test_offer_responses.py -v
```

Expected: all pass.

- [ ] **Step 5.15 — Commit**

```bash
git add src/ugc_bot/miniapp/api.py src/ugc_bot/bot/texts/defaults.py tests/unit/test_ugc_video_url.py
git commit -m "feat: add creator detail and ugc-video API endpoints with notifications"
```

---

## Chunk 3: Frontend + Final Verification

### Task 6: Frontend — creator detail screen

**Files:**
- Modify: `src/ugc_bot/miniapp/app.html`

All DOM manipulation uses safe methods (`createElement`, `textContent`, `setAttribute`,
`appendChild`) — no string interpolation into markup.

- [ ] **Step 6.1 — Add creator detail screen HTML**

In `src/ugc_bot/miniapp/app.html`, find `<div id="screen-manager-creators" class="screen">` and add a new screen **immediately after** its closing `</div>`:

```html
<div id="screen-creator-detail" class="screen">
  <h1>Детали креатора</h1>
  <div id="creator-detail-body"></div>
  <button type="button" class="btn btn-secondary" id="creator-detail-back">Назад</button>
</div>
```

- [ ] **Step 6.2 — Add `openCreatorDetail` and `saveCreatorUgcVideo` JS functions**

In `src/ugc_bot/miniapp/app.html`, find the `loadManagerCreators` function and add the following **after** it. All values are set via `textContent` or `setAttribute` — no string interpolation into markup:

```javascript
function openCreatorDetail(orderId, bloggerId) {
  window._mgrCurrentBloggerId = bloggerId;
  var body = document.getElementById('creator-detail-body');
  if (body) {
    while (body.firstChild) body.removeChild(body.firstChild);
    var loading = document.createElement('p');
    loading.textContent = 'Загрузка...';
    body.appendChild(loading);
  }
  showScreen('screen-creator-detail');
  api('/manager/orders/' + orderId + '/creators/' + bloggerId, {})
    .then(function(data) {
      if (!body) return;
      while (body.firstChild) body.removeChild(body.firstChild);

      if (data.instagram_url) {
        var p = document.createElement('p');
        var icon = document.createTextNode('📸 ');
        var a = document.createElement('a');
        a.setAttribute('href', data.instagram_url);
        a.setAttribute('target', '_blank');
        a.setAttribute('rel', 'noopener');
        a.textContent = data.instagram_url;
        p.appendChild(icon);
        p.appendChild(a);
        body.appendChild(p);
      }

      if (data.telegram) {
        var p2 = document.createElement('p');
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '16');
        svg.setAttribute('height', '16');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.style.verticalAlign = 'middle';
        svg.style.marginRight = '4px';
        var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('fill', '#2481cc');
        path.setAttribute('d', 'M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm5.894 8.221l-1.97 9.28c-.145.658-.537.818-1.084.508l-3-2.21-1.447 1.394c-.16.16-.295.295-.605.295l.213-3.053 5.56-5.023c.242-.213-.054-.333-.373-.12L7.19 13.984l-2.96-.924c-.643-.204-.657-.643.136-.953l11.57-4.461c.537-.194 1.006.131.958.575z');
        svg.appendChild(path);
        var tgLink = document.createElement('a');
        tgLink.setAttribute('href', 'https://t.me/' + data.telegram);
        tgLink.setAttribute('target', '_blank');
        tgLink.setAttribute('rel', 'noopener');
        tgLink.textContent = '@' + data.telegram;
        p2.appendChild(svg);
        p2.appendChild(tgLink);
        body.appendChild(p2);
      }

      var label = document.createElement('p');
      label.textContent = 'UGC-видео для этого заказа';
      label.style.cssText = 'font-size:12px;font-weight:600;color:#888;text-transform:uppercase;margin-top:16px';
      body.appendChild(label);

      var input = document.createElement('input');
      input.setAttribute('type', 'url');
      input.setAttribute('id', 'ugc-video-input');
      input.setAttribute('placeholder', 'https://...');
      input.style.cssText = 'width:100%;box-sizing:border-box;padding:10px;border:1.5px solid #d0d0d0;border-radius:8px;font-size:14px';
      if (data.ugc_video_url) input.value = data.ugc_video_url;
      body.appendChild(input);

      var hint = document.createElement('p');
      hint.textContent = 'Ссылка на готовое видео (Google Drive, YouTube, и т.д.)';
      hint.style.cssText = 'font-size:12px;color:#999;margin-top:4px';
      body.appendChild(hint);

      var saveBtn = document.createElement('button');
      saveBtn.setAttribute('type', 'button');
      saveBtn.className = 'btn';
      saveBtn.style.cssText = 'width:100%;margin-top:12px';
      saveBtn.textContent = 'Сохранить';
      saveBtn.addEventListener('click', function() {
        saveCreatorUgcVideo(orderId, bloggerId);
      });
      body.appendChild(saveBtn);

      var status = document.createElement('p');
      status.setAttribute('id', 'ugc-save-status');
      status.style.cssText = 'font-size:13px;margin-top:8px';
      body.appendChild(status);
    })
    .catch(function() {
      if (!body) return;
      while (body.firstChild) body.removeChild(body.firstChild);
      var err = document.createElement('p');
      err.className = 'error';
      err.textContent = 'Ошибка загрузки';
      body.appendChild(err);
    });
}

function saveCreatorUgcVideo(orderId, bloggerId) {
  var input = document.getElementById('ugc-video-input');
  var status = document.getElementById('ugc-save-status');
  if (!input) return;
  var url = input.value.trim();
  if (!url) {
    if (status) {
      status.textContent = 'Введите ссылку';
      status.style.color = '#c62828';
    }
    return;
  }
  if (status) status.textContent = '';
  api('/manager/orders/' + orderId + '/creators/' + bloggerId + '/ugc-video', { url: url })
    .then(function(data) {
      if (data.ok && status) {
        status.textContent = '✅ Сохранено';
        status.style.color = '#2e7d32';
      }
    })
    .catch(function() {
      if (status) {
        status.textContent = '❌ Ошибка сохранения';
        status.style.color = '#c62828';
      }
    });
}
```

- [ ] **Step 6.3 — Make creator list items clickable**

In `src/ugc_bot/miniapp/app.html`, find the `loadManagerCreators` function. At the very end of the `creators.forEach` callback, just before `if (ul) ul.appendChild(li);`, add:

```javascript
        (function(bid) {
          li.style.cursor = 'pointer';
          li.addEventListener('click', function() {
            openCreatorDetail(orderId, bid);
          });
        })(c.blogger_id);
        if (ul) ul.appendChild(li);
```

Replace the existing final `if (ul) ul.appendChild(li);` with this block (the IIFE captures `c.blogger_id` to avoid closure-over-loop issues).

- [ ] **Step 6.4 — Add back button listener**

In `src/ugc_bot/miniapp/app.html`, find the `mgr-creators-back` event listener and add immediately after it:

```javascript
document.getElementById('creator-detail-back').addEventListener('click', function() {
  var orderId = window._mgrCurrentOrderId;
  if (orderId) loadManagerCreators(orderId, true, 0);
});
```

- [ ] **Step 6.5 — Lint check**

```bash
uv run ruff check src/ugc_bot/miniapp/
```

Expected: `All checks passed!`

- [ ] **Step 6.6 — Commit**

```bash
git add src/ugc_bot/miniapp/app.html
git commit -m "feat: add creator detail screen with UGC video URL field"
```

---

### Task 7: Final verification

- [ ] **Step 7.1 — Add missing edge-case test**

Add to `tests/unit/test_ugc_video_url.py`:

```python
@pytest.mark.asyncio
async def test_dispatch_not_found_returns_none() -> None:
    """get_by_order_and_blogger on missing dispatch returns None."""
    repo = InMemoryOfferDispatchRepository()
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None
```

- [ ] **Step 7.2 — Run full test suite**

```bash
uv run pytest -m "not e2e" --tb=short 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 7.3 — Run make fix**

```bash
make fix
```

Expected: all checks pass, coverage reported at or above 98%.

If coverage drops below 98%, check which lines are uncovered:

```bash
uv run pytest -m "not e2e" --cov=ugc_bot --cov-report=term-missing 2>&1 | grep -E "miniapp/api|interactions|memory_repo" | grep -v "100%"
```

Add targeted tests as needed.

- [ ] **Step 7.4 — Final commit**

```bash
git add tests/unit/test_ugc_video_url.py
git commit -m "test: add edge-case tests for ugc_video_url feature"
```

- [ ] **Step 7.5 — Push branch**

```bash
git push -u origin feature/manager
```
