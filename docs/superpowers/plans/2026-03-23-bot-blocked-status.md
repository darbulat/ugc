# Bot Blocked Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a user blocks the Telegram bot, automatically set `UserStatus.BOT_BLOCKED` so no further messages are sent; restore to `ACTIVE` when the user sends `/start`.

**Architecture:** Add a new `UserStatus.BOT_BLOCKED` enum value (separate from the admin-managed `BLOCKED`). Wire an `on_bot_blocked` callback into `send_with_retry` so any caller that knows the `user_id` can mark the user in the database. On `/start`, detect `BOT_BLOCKED` status and restore it to `ACTIVE`.

**Tech Stack:** Python, aiogram 3, SQLAlchemy, Alembic (PostgreSQL native enum migration)

---

## File Map

| File | Change |
|------|--------|
| `src/ugc_bot/domain/enums.py` | Add `BOT_BLOCKED = "bot_blocked"` |
| `src/ugc_bot/infrastructure/db/migrations/versions/0082_user_status_bot_blocked.py` | Add enum value to PostgreSQL |
| `src/ugc_bot/bot/handlers/utils.py` | Add `on_bot_blocked` param to `send_with_retry` |
| `src/ugc_bot/container/__init__.py` | Add `build_user_role_service()` method |
| `src/ugc_bot/kafka_consumer.py` | Pass `user_role_service` down to `_send_offer_via_client` |
| `src/ugc_bot/feedback_scheduler.py` | Pass `on_bot_blocked` to `send_with_retry` calls |
| `src/ugc_bot/role_reminder_scheduler.py` | Pass `on_bot_blocked` to `send_with_retry` calls |
| `src/ugc_bot/bot/handlers/start.py` | Restore `BOT_BLOCKED → ACTIVE` in `_start_command` |
| `src/ugc_bot/bot/handlers/profile.py` | Add `BOT_BLOCKED` entry to `_STATUS_KEY` |
| `tests/unit/test_kafka_consumer.py` | Test BOT_BLOCKED is set on Forbidden |
| `tests/unit/bot/test_start_handler_bot_blocked.py` | Test BOT_BLOCKED is restored on /start |
| `tests/unit/bot/test_send_with_retry.py` | Test `on_bot_blocked` callback |

---

### Task 1: Add `UserStatus.BOT_BLOCKED` to the domain enum

**Files:**
- Modify: `src/ugc_bot/domain/enums.py`
- Modify: `src/ugc_bot/bot/handlers/profile.py`

- [ ] **Step 1: Write a failing test to confirm enum value exists**

Create `tests/unit/test_bot_blocked_status.py`:
```python
from ugc_bot.domain.enums import UserStatus


def test_bot_blocked_status_exists() -> None:
    assert UserStatus.BOT_BLOCKED == "bot_blocked"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
uv run pytest tests/unit/test_bot_blocked_status.py -v
```
Expected: `AttributeError: BOT_BLOCKED`

- [ ] **Step 3: Add enum value**

In `src/ugc_bot/domain/enums.py`, add after `BLOCKED = "blocked"`:
```python
BOT_BLOCKED = "bot_blocked"
```

The `UserStatus` class should look like:
```python
class UserStatus(StrEnum):
    """User status for anti-fraud and access control."""

    NEW = "new"
    ACTIVE = "active"
    PAUSE = "pause"
    BLOCKED = "blocked"
    BOT_BLOCKED = "bot_blocked"
    DELETED = "deleted"
```

- [ ] **Step 4: Add to profile status label map**

In `src/ugc_bot/bot/handlers/profile.py`, locate `_STATUS_KEY` dict (around line 155) and add:
```python
UserStatus.BOT_BLOCKED: "lbl_status_active",  # shown as "active" to user
```

The dict should look like:
```python
_STATUS_KEY: dict[UserStatus, str] = {
    UserStatus.NEW: "lbl_status_new",
    UserStatus.ACTIVE: "lbl_status_active",
    UserStatus.PAUSE: "lbl_status_pause",
    UserStatus.BLOCKED: "lbl_status_blocked",
    UserStatus.BOT_BLOCKED: "lbl_status_active",
}
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_bot_blocked_status.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/unit/test_bot_blocked_status.py src/ugc_bot/domain/enums.py src/ugc_bot/bot/handlers/profile.py
git commit -m "feat: add UserStatus.BOT_BLOCKED enum value"
```

---

### Task 2: Alembic migration for PostgreSQL enum

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0082_user_status_bot_blocked.py`

- [ ] **Step 1: Create migration file**

```python
"""Add bot_blocked value to user_status enum.

Revision ID: 0082
Revises: 0081
"""

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_status ADD VALUE IF NOT EXISTS 'bot_blocked'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # To roll back: recreate the enum without 'bot_blocked' and migrate the column.
    pass
```

- [ ] **Step 2: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0082_user_status_bot_blocked.py
git commit -m "feat: migration 0082 — add bot_blocked to user_status enum"
```

---

### Task 3: Add `on_bot_blocked` callback to `send_with_retry`

**Files:**
- Modify: `src/ugc_bot/bot/handlers/utils.py`
- Create: `tests/unit/bot/test_send_with_retry.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/bot/test_send_with_retry.py`:
```python
"""Tests for send_with_retry on_bot_blocked callback."""

import logging
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from ugc_bot.bot.handlers.utils import send_with_retry

logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_on_bot_blocked_called_when_forbidden() -> None:
    """on_bot_blocked callback is invoked when TelegramForbiddenError."""
    forbidden_exc = TelegramForbiddenError(
        method=SendMessage(chat_id=0, text=""),
        message="Forbidden: bot was blocked by the user",
    )
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=forbidden_exc)
    on_blocked = AsyncMock()

    result = await send_with_retry(
        client,
        chat_id="123",
        text="hi",
        retries=3,
        delay_seconds=0,
        logger=logger,
        on_bot_blocked=on_blocked,
    )

    assert result is False
    on_blocked.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_bot_blocked_not_called_on_other_error() -> None:
    """on_bot_blocked is NOT called for unrelated errors."""
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=RuntimeError("network"))
    on_blocked = AsyncMock()

    result = await send_with_retry(
        client,
        chat_id="123",
        text="hi",
        retries=1,
        delay_seconds=0,
        logger=logger,
        on_bot_blocked=on_blocked,
    )

    assert result is False
    on_blocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_bot_blocked_none_does_not_raise() -> None:
    """No on_bot_blocked callback is fine."""
    forbidden_exc = TelegramForbiddenError(
        method=SendMessage(chat_id=0, text=""),
        message="Forbidden: bot was blocked by the user",
    )
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=forbidden_exc)

    result = await send_with_retry(
        client,
        chat_id="123",
        text="hi",
        retries=1,
        delay_seconds=0,
        logger=logger,
    )

    assert result is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/bot/test_send_with_retry.py -v
```
Expected: `TypeError: send_with_retry() got an unexpected keyword argument 'on_bot_blocked'`

- [ ] **Step 3: Add `on_bot_blocked` to `send_with_retry`**

In `src/ugc_bot/bot/handlers/utils.py`, update the function signature and body (around line 350):

```python
async def send_with_retry(
    messenger_client: Any,
    chat_id: str,
    text: str,
    *,
    retries: int,
    delay_seconds: float,
    logger: logging.Logger,
    extra: dict[str, Any] | None = None,
    on_bot_blocked: Callable[[], Awaitable[None]] | None = None,
    **kwargs: Any,
) -> bool:
    """Send a message with retry on failures."""

    for attempt in range(1, retries + 1):
        try:
            if hasattr(messenger_client, "send_text"):
                await messenger_client.send_text(
                    chat_id=chat_id, text=text, **kwargs
                )
            elif hasattr(messenger_client, "send_message"):
                payload = dict(kwargs)
                if "keyboard" in payload and "reply_markup" not in payload:
                    payload["reply_markup"] = payload.pop("keyboard")
                await messenger_client.send_message(
                    chat_id=int(chat_id), text=text, **payload
                )
            else:
                raise AttributeError("Messenger client lacks send methods")
            return True
        except Exception as exc:
            logger.warning(
                "Send message failed",
                extra={
                    "attempt": attempt,
                    "retries": retries,
                    "chat_id": chat_id,
                    "error": str(exc),
                    **(extra or {}),
                },
            )
            if is_user_blocked_bot(exc):
                if on_bot_blocked is not None:
                    await on_bot_blocked()
                return False
            if attempt < retries:
                await asyncio.sleep(delay_seconds)
    return False
```

Also add the import at the top of `utils.py` (near other imports):
```python
from collections.abc import Awaitable, Callable
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/bot/test_send_with_retry.py -v
```
Expected: all 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/bot/test_send_with_retry.py src/ugc_bot/bot/handlers/utils.py
git commit -m "feat: add on_bot_blocked callback to send_with_retry"
```

---

### Task 4: Mark user BOT_BLOCKED in kafka_consumer offer sending

**Files:**
- Modify: `src/ugc_bot/container/__init__.py`
- Modify: `src/ugc_bot/kafka_consumer.py`
- Modify: `tests/unit/test_kafka_consumer.py`

- [ ] **Step 1: Write failing test**

In `tests/unit/test_kafka_consumer.py`:

1. Add `_send_offer_via_client` to the existing top-level import block (around line 36–45):
```python
from ugc_bot.kafka_consumer import (
    _commit_message_offset,
    _parse_order_id,
    _publish_dlq,
    _send_offer_to_blogger,
    _send_offer_via_client,   # <-- add this
    _send_offers,
    _start_kafka_client_with_retry,
    main,
    run_consumer,
)
```

2. Add the new test after existing tests:
```python
@pytest.mark.asyncio
async def test_send_offer_marks_user_bot_blocked_on_forbidden() -> None:
    """_send_offer_via_client sets BOT_BLOCKED on TelegramForbiddenError."""
    from aiogram.methods import SendMessage
    from ugc_bot.application.messenger.dto import Keyboard, KeyboardKind
    from ugc_bot.application.services.user_role_service import UserRoleService

    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        telegram_id="42",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blogger)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000002"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000003"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=now,
        completed_at=None,
    )
    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        interaction_repo=InMemoryInteractionRepository(),
    )
    user_role_service = UserRoleService(user_repo=user_repo)

    blocked_error = TelegramForbiddenError(
        message="Forbidden: bot was blocked by the user",
        method=SendMessage(chat_id=0, text=""),
    )
    client = AsyncMock()
    client.send_text = AsyncMock(side_effect=blocked_error)

    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=[])

    await _send_offer_via_client(
        chat_id="42",
        messenger_client=client,
        offer_text="hi",
        reply_markup=keyboard,
        order=order,
        blogger=blogger,
        retries=1,
        retry_delay_seconds=0,
        offer_dispatch_service=offer_dispatch_service,
        dlq_producer=None,
        dlq_topic="dlq",
        messenger_label="telegram",
        user_role_service=user_role_service,
    )

    updated = await user_repo.get_by_id(blogger.user_id)
    assert updated is not None
    assert updated.status == UserStatus.BOT_BLOCKED
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_kafka_consumer.py::test_send_offer_marks_user_bot_blocked_on_forbidden -v
```
Expected: `TypeError: _send_offer_via_client() got an unexpected keyword argument 'user_role_service'`

- [ ] **Step 3: Add `build_user_role_service` to Container**

In `src/ugc_bot/container/__init__.py`, add after `build_offer_dispatch_service` (around line 90):
```python
def build_user_role_service(self) -> UserRoleService:
    """UserRoleService for status updates (e.g. bot-blocked marking)."""
    repos = self.build_repos()
    # Verify key: check repository_factory.build_repos() returns "user_repo"
    return UserRoleService(
        user_repo=repos["user_repo"],
        transaction_manager=self._transaction_manager,
    )
```

Note: confirm `repos["user_repo"]` is the correct key by checking `src/ugc_bot/container/repository_factory.py` — the same key is used in `build_admin_services` and `build_feedback_scheduler_deps`.

- [ ] **Step 4: Update `_send_offer_via_client` signature**

In `src/ugc_bot/kafka_consumer.py`, update `_send_offer_via_client` to accept and use `user_role_service`:

```python
async def _send_offer_via_client(
    chat_id: str,
    messenger_client: MessengerClient,
    offer_text: str,
    reply_markup: Keyboard,
    order: Order,
    blogger: User,
    retries: int,
    retry_delay_seconds: float,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    messenger_label: str,
    user_role_service: UserRoleService | None = None,
) -> None:
    """Send offer to one chat_id via one messenger client with retries."""
    for attempt in range(1, retries + 1):
        try:
            if order.product_photo_file_id:
                await messenger_client.send_photo(
                    chat_id=chat_id,
                    file_id=order.product_photo_file_id,
                    caption=offer_text,
                    keyboard=reply_markup,
                )
            else:
                await messenger_client.send_text(
                    chat_id=chat_id,
                    text=offer_text,
                    keyboard=reply_markup,
                )
            logger.info(
                "Offer sent to blogger",
                extra={
                    "order_id": order.order_id,
                    "blogger_id": blogger.user_id,
                    "messenger": messenger_label,
                    "attempt": attempt,
                },
            )
            return
        except Exception as exc:
            logger.warning(
                "Failed to send offer message",
                extra={
                    "order_id": order.order_id,
                    "blogger_id": blogger.user_id,
                    "messenger": messenger_label,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if is_user_blocked_bot(exc):
                if user_role_service is not None:
                    try:
                        await user_role_service.update_status(
                            blogger.user_id, UserStatus.BOT_BLOCKED
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark user as bot_blocked",
                            extra={"blogger_id": str(blogger.user_id)},
                        )
                return
            if attempt >= retries:
                logger.error(
                    "All retries failed for offer send, publishing to DLQ",
                    extra={
                        "order_id": order.order_id,
                        "blogger_id": blogger.user_id,
                        "messenger": messenger_label,
                        "retries": retries,
                    },
                )
                await _publish_dlq(
                    dlq_producer,
                    dlq_topic,
                    {
                        "event": "offer_send_failed",
                        "order_id": str(order.order_id),
                        "blogger_id": str(blogger.user_id),
                        "chat_id": chat_id,
                        "messenger": messenger_label,
                        "error": str(exc),
                    },
                )
            else:
                await asyncio.sleep(retry_delay_seconds)
```

Also add import at the top of `kafka_consumer.py`:
```python
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.enums import UserStatus
```

- [ ] **Step 5: Propagate `user_role_service` through call chain**

Update `_send_offer_to_blogger` signature to accept and pass it:
```python
async def _send_offer_to_blogger(
    blogger: User,
    order: Order,
    advertisers_status: str,
    messenger_clients: dict[str, MessengerClient],
    offer_dispatch_service: OfferDispatchService,
    retries: int,
    retry_delay_seconds: float,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    locale: str = "ru",
    bot_texts_service: BotTextsService | None = None,
    user_role_service: UserRoleService | None = None,
) -> None:
```

And in the `_send_offer_via_client(...)` call block, pass `user_role_service=user_role_service`.

Update `_send_offers` similarly:
```python
async def _send_offers(
    order_id: UUID,
    messenger_clients: dict[str, MessengerClient],
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
    bot_texts_service: BotTextsService | None = None,
    default_locale: str = "ru",
    user_role_service: UserRoleService | None = None,
) -> None:
```

And pass `user_role_service=user_role_service` in the `_send_offer_to_blogger(...)` call.

Update `_consume_forever` to accept and pass `user_role_service`:
```python
async def _consume_forever(
    *,
    consumer: AIOKafkaConsumer,
    dlq_producer: AIOKafkaProducer,
    bot: Bot,
    messenger_clients: dict[str, MessengerClient],
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
    bot_texts_service: BotTextsService | None = None,
    default_locale: str = "ru",
    user_role_service: UserRoleService | None = None,
) -> None:
```

And pass it through to `_send_offers(...)`.

Update `run_consumer` — add `user_role_service` line and pass it to `_consume_forever`. The full body should be:
```python
async def run_consumer() -> None:
    """Run Kafka consumer in single event loop, process messages async."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("kafka-consumer")
    install_asyncio_exception_handler("kafka-consumer")
    log_startup_info(
        logger=logger, service_name="kafka-consumer", config=config
    )
    if not config.kafka.kafka_enabled:
        logger.info("Kafka consumer disabled by config")
        return
    if not config.db.database_url:
        logger.error("DATABASE_URL is required for Kafka consumer")
        return

    container = Container(config)
    offer_dispatch_service = container.build_offer_dispatch_service()
    user_role_service = container.build_user_role_service()   # <-- new
    bot_texts_service = container.build_bot_texts_service()

    dlq_producer, consumer = _create_kafka_clients(config)
    logger.info(
        "Kafka consumer started", extra={"topic": config.kafka.kafka_topic}
    )

    bot = Bot(token=config.bot.bot_token)
    messenger_clients: dict[str, MessengerClient] = {
        "telegram": TelegramMessengerClient(bot),
    }
    try:
        await _consume_forever(
            consumer=consumer,
            dlq_producer=dlq_producer,
            bot=bot,
            messenger_clients=messenger_clients,
            offer_dispatch_service=offer_dispatch_service,
            config=config,
            bot_texts_service=bot_texts_service,
            default_locale=config.market.default_locale,
            user_role_service=user_role_service,   # <-- new
        )
    finally:
        await container.dispose()
```

- [ ] **Step 6: Run test**

```bash
uv run pytest tests/unit/test_kafka_consumer.py::test_send_offer_marks_user_bot_blocked_on_forbidden -v
```
Expected: PASS

- [ ] **Step 7: Run full kafka consumer test suite**

```bash
uv run pytest tests/unit/test_kafka_consumer.py -v
```
Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add src/ugc_bot/kafka_consumer.py src/ugc_bot/container/__init__.py tests/unit/test_kafka_consumer.py
git commit -m "feat: mark user BOT_BLOCKED on Forbidden error in offer sending"
```

---

### Task 5: Mark user BOT_BLOCKED in schedulers

**Files:**
- Modify: `src/ugc_bot/feedback_scheduler.py`
- Modify: `src/ugc_bot/role_reminder_scheduler.py`
- Create: `tests/unit/test_scheduler_bot_blocked.py`

- [ ] **Step 1: Write failing tests for scheduler wiring**

Create `tests/unit/test_scheduler_bot_blocked.py`:
```python
"""Tests: schedulers pass on_bot_blocked callback to send_with_retry."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage

from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.domain.entities import Interaction, User
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    UserStatus,
)
from ugc_bot.feedback_scheduler import _send_advertiser_feedback
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository
from ugc_bot.role_reminder_scheduler import run_once


def _blocked_client() -> AsyncMock:
    client = AsyncMock()
    client.send_text = AsyncMock(
        side_effect=TelegramForbiddenError(
            method=SendMessage(chat_id=0, text=""),
            message="Forbidden: bot was blocked by the user",
        )
    )
    return client


@pytest.mark.asyncio
async def test_feedback_scheduler_marks_advertiser_bot_blocked() -> None:
    """Advertiser is marked BOT_BLOCKED when feedback send raises Forbidden."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000020"),
        telegram_id="20",
        messenger_type=MessengerType.TELEGRAM,
        username="adv",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(advertiser)
    user_role_service = UserRoleService(user_repo=user_repo)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000021"),
        order_id=UUID("00000000-0000-0000-0000-000000000022"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000023"),
        advertiser_id=advertiser.user_id,
        status=InteractionStatus.OK,
        from_advertiser=None,
        from_blogger=None,
    )
    messenger_clients = {"telegram": _blocked_client()}

    await _send_advertiser_feedback(
        messenger_clients=messenger_clients,
        interaction=interaction,
        advertiser=advertiser,
        blogger_profile=None,
        texts={},
        user_role_service=user_role_service,
    )

    updated = await user_repo.get_by_id(advertiser.user_id)
    assert updated is not None
    assert updated.status == UserStatus.BOT_BLOCKED


@pytest.mark.asyncio
async def test_role_reminder_scheduler_marks_user_bot_blocked() -> None:
    """User is marked BOT_BLOCKED when role reminder send raises Forbidden."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000030"),
        telegram_id="30",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(user)
    user_role_service = UserRoleService(user_repo=user_repo)

    messenger_clients = {"telegram": _blocked_client()}

    # `run_once` calls list_pending_role_reminders and update_last_role_reminder_at.
    # Patch them so we control which users are processed without real DB.
    with patch.object(
        user_role_service,
        "list_pending_role_reminders",
        new_callable=AsyncMock,
        return_value=[user],
    ), patch.object(
        user_role_service,
        "update_last_role_reminder_at",
        new_callable=AsyncMock,
    ):
        config = AsyncMock()
        config.market.start_text = "Start"
        config.market.default_locale = "ru"
        # run_once(messenger_clients, user_role_service, reminder_cutoff, config)
        await run_once(
            messenger_clients,
            user_role_service,
            reminder_cutoff=now,
            config=config,
        )

    updated = await user_repo.get_by_id(user.user_id)
    assert updated is not None
    assert updated.status == UserStatus.BOT_BLOCKED
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_scheduler_bot_blocked.py -v
```
Expected: `AssertionError` (status still ACTIVE) — schedulers don't pass `on_bot_blocked` yet.

- [ ] **Step 3: Update `feedback_scheduler.py`**

**3a.** Add `UserStatus` to the existing enums import in `feedback_scheduler.py`:
```python
# find: from ugc_bot.domain.enums import ...  (or add the import line)
from ugc_bot.domain.enums import UserStatus
```

**3b.** Add helper at module level (e.g. after imports, before `_feedback_keyboard`):
```python
async def _mark_bot_blocked(
    user: User, user_role_service: UserRoleService
) -> None:
    """Mark user as BOT_BLOCKED; log and swallow errors."""
    try:
        await user_role_service.update_status(
            user.user_id, UserStatus.BOT_BLOCKED
        )
    except Exception:
        logger.exception(
            "Failed to mark user as bot_blocked",
            extra={"user_id": str(user.user_id)},
        )
```

**3c.** Update `_send_advertiser_feedback` — add `user_role_service` param and `on_bot_blocked`:
```python
async def _send_advertiser_feedback(
    messenger_clients: dict[str, MessengerClient],
    interaction: Interaction,
    advertiser: User,
    blogger_profile: Optional[BloggerProfile],
    texts: dict[str, str],
    user_role_service: UserRoleService,
) -> bool:
    """Send feedback request to advertiser. Return True if sent."""
    targets = _user_messenger_targets(advertiser, messenger_clients)
    if not targets:
        return False
    creator_link = ""
    if blogger_profile and blogger_profile.instagram_url:
        url = blogger_profile.instagram_url.strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        creator_link = f" [{url}]({url})"
    template = texts.get(
        "msg_feedback_request_adv",
        "Хотим убедиться, что всё прошло корректно 🙌\n"
        "Удалось ли вам связаться с креатором{creator_link}?\n"
        "Выберите подходящий вариант:",
    )
    text = template.format(creator_link=creator_link)
    for chat_id, client in targets:
        await send_with_retry(
            client,
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            keyboard=_feedback_keyboard(
                "adv", interaction.interaction_id, texts
            ),
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"interaction_id": str(interaction.interaction_id)},
            on_bot_blocked=lambda _u=advertiser: _mark_bot_blocked(
                _u, user_role_service
            ),
        )
    logger.info(
        "Sent interaction feedback request to advertiser",
        extra={
            "interaction_id": str(interaction.interaction_id),
            "advertiser_id": str(advertiser.user_id),
        },
    )
    return True
```

**3d.** Update `_send_blogger_feedback` — same pattern:
```python
async def _send_blogger_feedback(
    messenger_clients: dict[str, MessengerClient],
    interaction: Interaction,
    blogger: User,
    order: Optional[Order],
    texts: dict[str, str],
    user_role_service: UserRoleService,
) -> bool:
    """Send feedback request to blogger. Return True if sent."""
    targets = _user_messenger_targets(blogger, messenger_clients)
    if not targets:
        return False
    order_link_part = "по заказу?"
    if order and order.product_link:
        url = order.product_link.strip()
        if url and not url.startswith("http"):
            url = "https://" + url
        order_link_part = f"[по заказу]({url})?"
    template = texts.get(
        "msg_feedback_request_blog",
        "Мы хотим убедиться, что всё прошло корректно 🙌\n"
        "Удалось ли вам связаться с заказчиком {order_link_part}",
    )
    text = template.format(order_link_part=order_link_part)
    for chat_id, client in targets:
        await send_with_retry(
            client,
            chat_id=chat_id,
            text=text,
            parse_mode="Markdown",
            keyboard=_feedback_keyboard(
                "blog", interaction.interaction_id, texts
            ),
            retries=_send_retries,
            delay_seconds=_send_retry_delay_seconds,
            logger=logger,
            extra={"interaction_id": str(interaction.interaction_id)},
            on_bot_blocked=lambda _u=blogger: _mark_bot_blocked(
                _u, user_role_service
            ),
        )
    logger.info(
        "Sent interaction feedback request to blogger",
        extra={
            "interaction_id": str(interaction.interaction_id),
            "blogger_id": str(interaction.blogger_id),
        },
    )
    return True
```

**3e.** Update the two call sites in `_send_feedback_requests` (around lines 300 and 320) to pass `user_role_service`:
```python
# Line ~300: advertiser feedback call
sent_to_adv = await _send_advertiser_feedback(
    messenger_clients,
    interaction,
    advertiser,
    blogger_profile,
    adv_texts,
    user_role_service,   # <-- add this
)

# Line ~320: blogger feedback call
sent_to_blog = await _send_blogger_feedback(
    messenger_clients, interaction, blogger, order, blog_texts,
    user_role_service,   # <-- add this
)
```

Note: `_send_feedback_requests` already receives `user_role_service: UserRoleService` in its signature (line 243 of the current file) — no signature change needed there.

- [ ] **Step 4: Update `role_reminder_scheduler.py`**

**4a.** Add import: `from ugc_bot.domain.enums import UserStatus`

**4b.** Add helper at module level:
```python
async def _mark_bot_blocked(
    user: User, user_role_service: UserRoleService
) -> None:
    """Mark user as BOT_BLOCKED; log and swallow errors."""
    try:
        await user_role_service.update_status(
            user.user_id, UserStatus.BOT_BLOCKED
        )
    except Exception:
        logger.exception(
            "Failed to mark user as bot_blocked",
            extra={"user_id": str(user.user_id)},
        )
```

**4c.** In `run_once`, update the inner `for chat_id, client in targets:` loop to pass `on_bot_blocked`. Use default-arg binding to capture `user` at iteration time (avoids stale closure if the loop body is ever made async):
```python
for chat_id, client in targets:
    await send_with_retry(
        client,
        chat_id=chat_id,
        text=start_text,
        keyboard=keyboard,
        retries=_send_retries,
        delay_seconds=_send_retry_delay_seconds,
        logger=logger,
        extra={"user_id": str(user.user_id)},
        on_bot_blocked=lambda _u=user: _mark_bot_blocked(
            _u, user_role_service
        ),
    )
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_scheduler_bot_blocked.py -v
```
Expected: all PASS

- [ ] **Step 6: Run full unit tests**

```bash
make fix
uv run pytest tests/unit/ -v
```

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/feedback_scheduler.py src/ugc_bot/role_reminder_scheduler.py tests/unit/test_scheduler_bot_blocked.py
git commit -m "feat: mark user BOT_BLOCKED in feedback and role reminder schedulers"
```

---

### Task 6: Restore BOT_BLOCKED → ACTIVE on /start

**Files:**
- Modify: `src/ugc_bot/bot/handlers/start.py`
- Create: `tests/unit/bot/test_start_handler_bot_blocked.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/bot/test_start_handler_bot_blocked.py`:
```python
"""Test that BOT_BLOCKED status is restored to ACTIVE on /start."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ugc_bot.application.messenger.dto import IncomingMessage, IncomingUser
from ugc_bot.application.messenger.state import StateStore
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.start import _start_command
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryUserRepository


def _make_incoming(external_id: str = "99") -> IncomingMessage:
    return IncomingMessage(
        chat_id=external_id,
        user=IncomingUser(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=None,
        ),
        text="/start",
        message_id=None,
    )


@pytest.mark.asyncio
async def test_bot_blocked_user_restored_to_active_on_start() -> None:
    """User with BOT_BLOCKED status is set to ACTIVE when they send /start."""
    now = datetime.now(timezone.utc)
    user_repo = InMemoryUserRepository()
    blocked_user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000010"),
        telegram_id="99",
        messenger_type=MessengerType.TELEGRAM,
        username="blocked_user",
        status=UserStatus.BOT_BLOCKED,
        issue_count=0,
        created_at=now,
    )
    await user_repo.save(blocked_user)
    user_role_service = UserRoleService(user_repo=user_repo)

    referral_service = AsyncMock(spec=ReferralService)
    referral_service.parse_referral_code.return_value = None

    messenger_client = AsyncMock()
    state_store = AsyncMock(spec=StateStore)

    from ugc_bot.application.messenger.dto import Keyboard, KeyboardKind
    role_kb = Keyboard(kind=KeyboardKind.INLINE, rows=[])

    await _start_command(
        incoming=_make_incoming("99"),
        state_store=state_store,
        messenger_client=messenger_client,
        user_role_service=user_role_service,
        referral_service=referral_service,
        start_text="Welcome",
        role_kb=role_kb,
    )

    updated = await user_repo.get_by_id(blocked_user.user_id)
    assert updated is not None
    assert updated.status == UserStatus.ACTIVE
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/bot/test_start_handler_bot_blocked.py -v
```
Expected: FAIL — user status is still `BOT_BLOCKED`

- [ ] **Step 3: Restore status in `_start_command`**

In `src/ugc_bot/bot/handlers/start.py`, in `_start_command` (around line 593), after the `user = await user_role_service.set_user(...)` call:

```python
user = await user_role_service.set_user(
    external_id=incoming.user.external_id,
    messenger_type=incoming.user.messenger_type,
    username=username,
    role_chosen=False,
    telegram_username=incoming.user.username,
)
# Restore user who previously blocked and re-opened the bot
if user.status == UserStatus.BOT_BLOCKED:
    user = await user_role_service.update_status(
        user.user_id, UserStatus.ACTIVE
    )
```

Add `UserStatus` import at the top of `start.py` if not already present:
```python
from ugc_bot.domain.enums import UserStatus
```

- [ ] **Step 4: Run test**

```bash
uv run pytest tests/unit/bot/test_start_handler_bot_blocked.py -v
```
Expected: PASS

- [ ] **Step 5: Run full test suite**

```bash
make fix
uv run pytest tests/unit/ -v
```
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/bot/handlers/start.py tests/unit/bot/test_start_handler_bot_blocked.py
git commit -m "feat: restore BOT_BLOCKED user to ACTIVE on /start"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full quality check**

```bash
make all
```
Expected: format-check, lint, typecheck, coverage all PASS (98% threshold)

- [ ] **Step 2: Fix any issues from `make all`**

If typecheck fails: ensure `Callable` and `Awaitable` imports are present in `utils.py`.
If coverage drops: check which branches are untested and add targeted tests.

- [ ] **Step 3: Final commit (if any fixes)**

```bash
git add -p
git commit -m "fix: type annotations and coverage for bot_blocked feature"
```
