# Unified Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate five separate scheduler Docker containers into a single `worker` container that shares one DB pool, one Bot instance, and one Container.

**Architecture:** New `src/ugc_bot/worker.py` entry point calls each scheduler's `run_loop()` via `asyncio.gather`, wrapping each in `_run_with_restart` for fault isolation. A `_NoCloseMessengerClient` wrapper prevents `feedback_scheduler.run_loop`'s `finally` from closing the shared Bot session. A new `Container.build_role_reminder_scheduler_deps()` brings `role_reminder_scheduler` in line with the existing deps-builder pattern.

**Tech Stack:** Python asyncio, aiogram, existing scheduler modules, SQLAlchemy session factory

---

## File Map

| Action | File | Purpose |
|--------|------|---------|
| Create | `src/ugc_bot/worker.py` | New unified entry point |
| Create | `tests/unit/test_worker.py` | Unit tests for worker |
| Modify | `src/ugc_bot/container/service_factory.py` | Add `build_role_reminder_scheduler_deps()` |
| Modify | `src/ugc_bot/container/__init__.py` | Add `Container.build_role_reminder_scheduler_deps()` |
| Modify | `docker-compose.yml` | Replace 5 scheduler services with 1 worker |

`docker-compose.dev.yml` — **no changes needed** (it only overrides `db_backup` profile, has no scheduler entries).

---

### Task 1: Add `build_role_reminder_scheduler_deps` to Container

**Files:**
- Modify: `src/ugc_bot/container/service_factory.py` (append after `build_referral_reconciliation_deps` at line ~528)
- Modify: `src/ugc_bot/container/__init__.py` (add after `build_referral_reconciliation_deps` method, line ~199)
- Test: `tests/unit/test_container.py` (extend existing file)

- [ ] **Step 1: Write the failing test**

Add at the end of `tests/unit/test_container.py`:

```python
def test_container_build_role_reminder_scheduler_deps(mocker) -> None:
    """build_role_reminder_scheduler_deps returns user_role_service and transaction_manager."""
    from unittest.mock import Mock

    container = Container(_config(database_url="postgresql+psycopg://x:x@localhost:5432/x"))
    mock_repos = {"user_repo": Mock()}
    mock_tm = Mock()
    mocker.patch.object(container, "build_repos", return_value=mock_repos)
    container._transaction_manager = mock_tm

    deps = container.build_role_reminder_scheduler_deps()

    assert "user_role_service" in deps
    assert "transaction_manager" in deps
    assert deps["transaction_manager"] is mock_tm
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_container.py::test_container_build_role_reminder_scheduler_deps -v
```

Expected: `FAILED — AttributeError: 'Container' object has no attribute 'build_role_reminder_scheduler_deps'`

- [ ] **Step 3: Add `build_role_reminder_scheduler_deps` to service_factory**

Append to `src/ugc_bot/container/service_factory.py` after `build_referral_reconciliation_deps`:

```python
def build_role_reminder_scheduler_deps(config: AppConfig, repos, transaction_manager):
    """Build deps for role reminder scheduler."""
    return {
        "user_role_service": UserRoleService(
            user_repo=repos["user_repo"],
            transaction_manager=transaction_manager,
        ),
        "transaction_manager": transaction_manager,
    }
```

Note: `config` is accepted for consistency with all other `build_*_deps` functions, even though it is not currently used.

- [ ] **Step 4: Add `Container.build_role_reminder_scheduler_deps()` to container/__init__.py**

Add after `build_referral_reconciliation_deps` method (after line ~199):

```python
    def build_role_reminder_scheduler_deps(self) -> dict:
        """Deps for role reminder scheduler: user_role_service and transaction_manager."""
        repos = self.build_repos()
        return service_factory.build_role_reminder_scheduler_deps(
            self._config, repos, self._transaction_manager
        )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_container.py::test_container_build_role_reminder_scheduler_deps -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/container/service_factory.py src/ugc_bot/container/__init__.py tests/unit/test_container.py
git commit -m "feat: add build_role_reminder_scheduler_deps to Container"
```

---

### Task 2: Create `worker.py` — helpers (`_NoCloseMessengerClient` + `_run_with_restart`)

**Files:**
- Create: `src/ugc_bot/worker.py`
- Create: `tests/unit/test_worker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_worker.py`:

```python
"""Tests for unified worker entry point."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_no_close_messenger_client_close_is_noop() -> None:
    """_NoCloseMessengerClient.close() does not call delegate.close()."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.close()

    delegate.close.assert_not_called()


@pytest.mark.asyncio
async def test_no_close_messenger_client_delegates_send_text() -> None:
    """_NoCloseMessengerClient delegates send_text to the wrapped client."""
    from ugc_bot.worker import _NoCloseMessengerClient

    delegate = AsyncMock()
    wrapper = _NoCloseMessengerClient(delegate)
    await wrapper.send_text(chat_id="123", text="hello")

    delegate.send_text.assert_called_once_with(chat_id="123", text="hello")


@pytest.mark.asyncio
async def test_run_with_restart_restarts_on_exception() -> None:
    """_run_with_restart re-runs coro_factory after an exception."""
    from ugc_bot.worker import _run_with_restart

    call_count = 0

    async def flaky():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("transient error")
        # Second call exits the infinite loop via CancelledError (BaseException)
        raise asyncio.CancelledError

    with patch("ugc_bot.worker.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(asyncio.CancelledError):
            await _run_with_restart("test", flaky, restart_delay=0)

    assert call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_worker.py -v
```

Expected: `ERROR — ModuleNotFoundError: No module named 'ugc_bot.worker'`

- [ ] **Step 3: Create `src/ugc_bot/worker.py` with full module structure**

Create `src/ugc_bot/worker.py` with all imports at the top and the two helper components:

```python
"""Unified worker: runs all background schedulers in one process."""

import asyncio
import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot

from ugc_bot import (
    feedback_scheduler,
    instagram_stats_collector_scheduler,
    instagram_stats_scheduler,
    referral_reconciliation_scheduler,
    role_reminder_scheduler,
)
from ugc_bot.application.messenger.dto import Invoice, Keyboard
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.messenger.telegram.client import TelegramMessengerClient
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


class _NoCloseMessengerClient:
    """Wraps a messenger client; makes close() a no-op.

    Used to prevent feedback_scheduler.run_loop's finally block from closing
    the shared Bot session while other schedulers are still running.
    The real session is closed by worker.main() after all tasks complete.
    """

    def __init__(self, delegate: Any) -> None:
        self._d = delegate

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        await self._d.send_text(
            chat_id=chat_id,
            text=text,
            keyboard=keyboard,
            parse_mode=parse_mode,
            disable_preview=disable_preview,
        )

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        await self._d.send_photo(
            chat_id=chat_id,
            file_id=file_id,
            caption=caption,
            keyboard=keyboard,
            parse_mode=parse_mode,
        )

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        await self._d.edit_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            keyboard=keyboard,
            parse_mode=parse_mode,
        )

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        await self._d.edit_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            keyboard=keyboard,
        )

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        await self._d.answer_callback(
            callback_id=callback_id,
            text=text,
            show_alert=show_alert,
        )

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        await self._d.send_invoice(chat_id=chat_id, invoice=invoice)

    async def close(self) -> None:
        """No-op: the shared Bot session is closed by worker.main()."""


async def _run_with_restart(
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    restart_delay: float = 5.0,
) -> None:
    """Run coro_factory() in an infinite loop; restart after exceptions.

    Only BaseException (e.g. CancelledError on shutdown) escapes this loop.
    That correctly propagates cancellation through asyncio.gather.
    """
    while True:
        try:
            await coro_factory()
        except Exception:
            logger.exception(
                "Scheduler %s crashed, restarting in %.0fs", name, restart_delay
            )
            await asyncio.sleep(restart_delay)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_worker.py -v
```

Expected: all 3 tests `PASSED`

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/worker.py tests/unit/test_worker.py
git commit -m "feat: add _NoCloseMessengerClient and _run_with_restart to worker"
```

---

### Task 3: Implement `main_async` and `main` in `worker.py`

**Files:**
- Modify: `src/ugc_bot/worker.py` (append functions after `_run_with_restart`)
- Modify: `tests/unit/test_worker.py` (add 3 more tests)

**Config construction note:** `AppConfig.model_validate` with a flat dict (containing `BOT_TOKEN` as top-level key) uses `_FLAT_KEYS` to remap keys to nested sections. Since `INSTAGRAM_STATS_UPDATE_ENABLED` and `REFERRAL_RECONCILIATION_ENABLED` are absent from `_FLAT_KEYS`, tests must use **nested dict form** (without top-level `BOT_TOKEN`) to avoid silent drops. When no flat-dict markers (`BOT_TOKEN`, `DATABASE_URL`, `KAFKA_ENABLED`, `LOG_LEVEL`) are at the top level, `AppConfig._handle_flat_dict` passes the dict through as-is.

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_worker.py`:

```python
from ugc_bot.config import (
    AppConfig,
    BotConfig,
    DbConfig,
    FeedbackConfig,
    InstagramConfig,
    KafkaConfig,
    LogConfig,
    MarketConfig,
    ReferralConfig,
    RoleReminderConfig,
)
from ugc_bot.config import (
    AdminConfig,
    DocsConfig,
    GeocoderConfig,
    OrderConfig,
    OutboxConfig,
    RedisConfig,
    WebhookConfig,
)


def _make_config(
    *,
    feedback_enabled: bool = True,
    role_reminder_enabled: bool = True,
    referral_reconciliation_enabled: bool = True,
    instagram_stats_update_enabled: bool = True,
    instagram_stats_collector_enabled: bool = True,
) -> AppConfig:
    """Build AppConfig via nested form to control all scheduler enabled flags."""
    return AppConfig.model_validate(
        {
            "bot": BotConfig.model_validate({"BOT_TOKEN": "test"}),
            "log": LogConfig.model_validate({}),
            "db": DbConfig.model_validate(
                {"DATABASE_URL": "postgresql+psycopg://x:x@localhost:5432/x"}
            ),
            "admin": AdminConfig.model_validate({}),
            "kafka": KafkaConfig.model_validate({"KAFKA_ENABLED": False}),
            "feedback": FeedbackConfig.model_validate(
                {"FEEDBACK_ENABLED": feedback_enabled}
            ),
            "role_reminder": RoleReminderConfig.model_validate(
                {"ROLE_REMINDER_ENABLED": role_reminder_enabled}
            ),
            "redis": RedisConfig.model_validate({}),
            "instagram": InstagramConfig.model_validate(
                {
                    "INSTAGRAM_STATS_UPDATE_ENABLED": instagram_stats_update_enabled,
                    "INSTAGRAM_STATS_COLLECTOR_ENABLED": instagram_stats_collector_enabled,
                }
            ),
            "geocoder": GeocoderConfig.model_validate({}),
            "docs": DocsConfig.model_validate({}),
            "webhook": WebhookConfig.model_validate({}),
            "outbox": OutboxConfig.model_validate({}),
            "order": OrderConfig.model_validate({}),
            "market": MarketConfig.model_validate({}),
            "referral": ReferralConfig.model_validate(
                {"REFERRAL_RECONCILIATION_ENABLED": referral_reconciliation_enabled}
            ),
        }
    )


def _make_mock_container():
    from unittest.mock import MagicMock

    container = MagicMock()
    container.build_feedback_scheduler_deps.return_value = {
        "interaction_repo": MagicMock(),
        "interaction_service": MagicMock(),
        "user_role_service": MagicMock(),
        "profile_service": MagicMock(),
        "order_repo": MagicMock(),
        "transaction_manager": MagicMock(),
    }
    container.build_bot_texts_service.return_value = MagicMock()
    container.build_role_reminder_scheduler_deps.return_value = {
        "user_role_service": MagicMock(),
        "transaction_manager": MagicMock(),
    }
    container.build_referral_reconciliation_deps.return_value = {
        "referral_income_entry_repo": MagicMock(),
        "recorder": MagicMock(),
        "order_repo": MagicMock(),
        "transaction_manager": MagicMock(),
    }
    container.build_instagram_stats_scheduler_deps.return_value = {
        "instagram_stats_update_service": MagicMock(),
        "interval_seconds": 60,
    }
    container.build_instagram_stats_collector_scheduler_deps.return_value = {
        "instagram_stats_collector_service": MagicMock(),
        "interval_seconds": 120,
    }
    return container


@pytest.mark.asyncio
async def test_main_async_starts_all_enabled_schedulers() -> None:
    """main_async launches all 5 schedulers when all are enabled."""
    from ugc_bot.worker import main_async

    config = _make_config()
    container = _make_mock_container()
    messenger = AsyncMock()
    launched = []

    async def fake_restart(name, coro_factory, restart_delay=5.0):
        launched.append(name)

    with patch("ugc_bot.worker._run_with_restart", new=fake_restart):
        await main_async(config, container, messenger)

    assert set(launched) == {
        "feedback",
        "role_reminder",
        "referral_reconciliation",
        "instagram_stats",
        "instagram_stats_collector",
    }


@pytest.mark.asyncio
async def test_main_async_skips_disabled_scheduler() -> None:
    """main_async does not launch a scheduler whose enabled flag is False."""
    from ugc_bot.worker import main_async

    config = _make_config(feedback_enabled=False)
    container = _make_mock_container()
    messenger = AsyncMock()
    launched = []

    async def fake_restart(name, coro_factory, restart_delay=5.0):
        launched.append(name)

    with patch("ugc_bot.worker._run_with_restart", new=fake_restart):
        await main_async(config, container, messenger)

    assert "feedback" not in launched
    assert len(launched) == 4


@pytest.mark.asyncio
async def test_main_async_all_disabled_blocks_indefinitely() -> None:
    """main_async calls asyncio.sleep(inf) when all schedulers are disabled."""
    from ugc_bot.worker import main_async

    config = _make_config(
        feedback_enabled=False,
        role_reminder_enabled=False,
        referral_reconciliation_enabled=False,
        instagram_stats_update_enabled=False,
        instagram_stats_collector_enabled=False,
    )
    container = _make_mock_container()
    messenger = AsyncMock()
    sleep_args = []

    async def fake_sleep(seconds):
        sleep_args.append(seconds)

    with patch("ugc_bot.worker.asyncio.sleep", new=fake_sleep):
        await main_async(config, container, messenger)

    assert float("inf") in sleep_args
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_worker.py::test_main_async_starts_all_enabled_schedulers tests/unit/test_worker.py::test_main_async_skips_disabled_scheduler tests/unit/test_worker.py::test_main_async_all_disabled_blocks_indefinitely -v
```

Expected: `FAILED — ImportError: cannot import name 'main_async' from 'ugc_bot.worker'`

- [ ] **Step 3: Append `main_async` and `main` to `src/ugc_bot/worker.py`**

Append after `_run_with_restart` (all imports are already at the top of the file from Task 2):

```python
async def main_async(
    config: AppConfig,
    container: Container,
    messenger_client: Any,
) -> None:
    """Initialize all enabled schedulers and run them concurrently."""
    install_asyncio_exception_handler("worker")

    tasks = []

    if config.feedback.feedback_enabled:
        deps = container.build_feedback_scheduler_deps()
        bot_texts_service = container.build_bot_texts_service()
        default_locale = (config.market.default_locale or "ru") if config.market else "ru"
        no_close = _NoCloseMessengerClient(messenger_client)
        # Use default-argument capture to freeze values at task-creation time,
        # preventing the classic Python closure-over-mutable-variable bug.
        tasks.append(
            _run_with_restart(
                "feedback",
                lambda d=deps, t=bot_texts_service, c=no_close, loc=default_locale:
                    feedback_scheduler.run_loop(
                        c,
                        d["interaction_repo"],
                        d["interaction_service"],
                        d["user_role_service"],
                        d["profile_service"],
                        d["order_repo"],
                        config.feedback,
                        interval_seconds=config.feedback.feedback_poll_interval_seconds,
                        transaction_manager=d["transaction_manager"],
                        default_locale=loc,
                        bot_texts_service=t,
                    ),
            )
        )
    else:
        logger.info("Feedback scheduler disabled by config")

    if config.role_reminder.role_reminder_enabled:
        deps = container.build_role_reminder_scheduler_deps()
        tasks.append(
            _run_with_restart(
                "role_reminder",
                lambda d=deps: role_reminder_scheduler.run_loop(
                    messenger_client,
                    d["user_role_service"],
                    config,
                ),
            )
        )
    else:
        logger.info("Role reminder scheduler disabled by config")

    if config.referral.referral_reconciliation_enabled:
        deps = container.build_referral_reconciliation_deps()
        tasks.append(
            _run_with_restart(
                "referral_reconciliation",
                lambda d=deps: referral_reconciliation_scheduler.run_loop(
                    income_entry_repo=d["referral_income_entry_repo"],
                    recorder=d["recorder"],
                    order_repo=d["order_repo"],
                    transaction_manager=d["transaction_manager"],
                    interval_seconds=config.referral.referral_reconciliation_interval_seconds,
                ),
            )
        )
    else:
        logger.info("Referral reconciliation scheduler disabled by config")

    if config.instagram.instagram_stats_update_enabled:
        deps = container.build_instagram_stats_scheduler_deps()
        tasks.append(
            _run_with_restart(
                "instagram_stats",
                lambda d=deps: instagram_stats_scheduler.run_loop(
                    d["instagram_stats_update_service"],
                    interval_seconds=d["interval_seconds"],
                ),
            )
        )
    else:
        logger.info("Instagram stats scheduler disabled by config")

    if config.instagram.instagram_stats_collector_enabled:
        deps = container.build_instagram_stats_collector_scheduler_deps()
        tasks.append(
            _run_with_restart(
                "instagram_stats_collector",
                lambda d=deps: instagram_stats_collector_scheduler.run_loop(
                    d["instagram_stats_collector_service"],
                    interval_seconds=d["interval_seconds"],
                ),
            )
        )
    else:
        logger.info("Instagram stats collector scheduler disabled by config")

    if not tasks:
        logger.warning("All schedulers are disabled; worker is idle")
        await asyncio.sleep(float("inf"))
        return

    await asyncio.gather(*tasks)


def main() -> None:  # pragma: no cover
    """Entry point for unified worker process."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("worker")
    log_startup_info(logger=logger, service_name="Worker", config=config)

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for worker")
        return

    container = Container(config)
    bot = Bot(token=config.bot.bot_token)
    messenger_client = TelegramMessengerClient(bot)

    async def _run() -> None:
        try:
            await main_async(config, container, messenger_client)
        finally:
            session = getattr(bot, "session", None)
            if session is not None:
                await session.close()
            await container.dispose()

    asyncio.run(_run())


if __name__ == "__main__":  # pragma: no cover
    main()
```

- [ ] **Step 4: Run all worker tests to verify they pass**

```bash
uv run pytest tests/unit/test_worker.py -v
```

Expected: all 6 tests `PASSED`

- [ ] **Step 5: Run `make all` to check types and lint**

```bash
make all
```

Fix any mypy or ruff errors before continuing. Common issues:
- `make format` if ruff complains about formatting
- mypy may warn about `messenger_client: Any` passed where `MessengerClient` Protocol is expected — this is intentional and can be annotated with `# type: ignore[arg-type]` at the call site in `feedback_scheduler.run_loop(c, ...)` if needed

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/worker.py tests/unit/test_worker.py
git commit -m "feat: add worker.py unified scheduler entry point"
```

---

### Task 4: Update `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Remove `feedback_scheduler`, `role_reminder_scheduler`, and `referral_reconciliation_scheduler` service blocks**

In `docker-compose.yml`, remove lines 206–243 (the three service blocks from `feedback_scheduler:` through the last `restart: unless-stopped` line of `referral_reconciliation_scheduler:`). The content being removed is:

```yaml
  feedback_scheduler:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.feedback_scheduler"]
    restart: unless-stopped

  role_reminder_scheduler:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.role_reminder_scheduler"]
    restart: unless-stopped

  referral_reconciliation_scheduler:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.referral_reconciliation_scheduler"]
    restart: unless-stopped
```

`outbox_processor:` (lines 245–258) stays untouched.

- [ ] **Step 2: Remove `instagram_stats_scheduler` and `instagram_stats_collector_scheduler` service blocks**

After removing the three blocks above and preserving `outbox_processor`, remove the two remaining scheduler blocks (currently lines 260–287):

```yaml
  instagram_stats_scheduler:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.instagram_stats_scheduler"]
    restart: unless-stopped

  instagram_stats_collector_scheduler:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
      INSTAGRAM_STATS_AIOGRAPI_SESSION_PATH: /app/instagram_session/.instagram_session.json
    volumes:
      - instagram_session_data:/app/instagram_session
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.instagram_stats_collector_scheduler"]
    restart: unless-stopped
```

- [ ] **Step 3: Add the new `worker` service**

After `outbox_processor:` service block (currently ending before the blank line before `wal_archive_init:`), insert the new `worker` service:

```yaml
  worker:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
      INSTAGRAM_STATS_AIOGRAPI_SESSION_PATH: /app/instagram_session/.instagram_session.json
    volumes:
      - instagram_session_data:/app/instagram_session
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.worker"]
    restart: unless-stopped
```

- [ ] **Step 4: Validate docker-compose syntax**

```bash
docker compose -f docker-compose.yml config --quiet
```

Expected: no errors

- [ ] **Step 5: Run full test suite**

```bash
make all
```

Expected: all checks pass

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: consolidate 5 scheduler containers into single worker"
```

---

## Notes for Implementer

- **Lambda capture:** Each lambda in `main_async` uses default-argument capture (`lambda d=deps: ...`) to freeze the `deps` reference at task-creation time. Without this, all lambdas would share the same `deps` variable and end up using the value from the last assignment.
- **`_NoCloseMessengerClient`:** Implements all `MessengerClient` Protocol methods explicitly for mypy compatibility. `close()` is a deliberate no-op; the real session closes in `worker.main()`'s `finally`.
- **`docker-compose.dev.yml`:** No changes needed — it only overrides the `db_backup` profile.
- **Existing scheduler files:** Unchanged. Their `main()` entry points remain functional for standalone testing.
