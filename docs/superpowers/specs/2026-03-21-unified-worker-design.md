# Unified Worker: Consolidated Background Schedulers

**Date:** 2026-03-21
**Status:** Approved

## Problem

The project runs five separate Docker containers for background schedulers:
`feedback_scheduler`, `role_reminder_scheduler`, `referral_reconciliation_scheduler`,
`instagram_stats_scheduler`, and `instagram_stats_collector_scheduler`. Each has its
own process, DB connection pool, Bot instance, and Container. This wastes resources
and increases operational complexity without providing meaningful isolation.

## Goal

Consolidate all five schedulers into a single `worker` container that shares one
Container, one DB pool, and one Bot instance. `outbox_processor` and `kafka_consumer`
remain separate (different responsibility domain).

## Solution

### New file: `src/ugc_bot/worker.py`

A single entry point that:

1. Loads config and initializes one `Container` and one `Bot`
2. Builds deps for all schedulers (skipping disabled ones)
3. Runs all `run_loop()` coroutines via `asyncio.gather`
4. Wraps each coroutine in `_run_with_restart` for fault isolation

```
worker.py
├── _NoCloseMessengerClient(delegate)
│     Wraps a MessengerClient; delegates all calls except close().
│     close() is a no-op. Used to prevent feedback_scheduler.run_loop
│     from closing the shared Bot session in its finally block.
├── _run_with_restart(name, coro_factory, restart_delay=5.0)
│     Catches any exception, logs it, sleeps restart_delay, then re-runs.
│     This isolates scheduler failures: one crash does not cancel others.
├── main_async(config, container, messenger_client)
│     1. Calls install_asyncio_exception_handler("worker") once.
│     2. Checks each scheduler's enabled flag; builds enabled task list.
│     3. If task list is empty: logs a warning and blocks indefinitely
│        (asyncio.sleep(float("inf"))) to avoid a Docker restart loop.
│     4. Calls asyncio.gather(*tasks) without return_exceptions=True.
│        Since _run_with_restart catches all Exception, only BaseException
│        (e.g. CancelledError on SIGTERM) can escape, which correctly
│        propagates and cancels remaining tasks.
└── main()
      load_config → configure_logging → install_exception_hooks("worker")
      → Container → Bot → TelegramMessengerClient
      → asyncio.run(main_async(...))
      → finally: dispose container, close bot session
```

### Enabled-flag logic

Each scheduler has its own `enabled` config flag. If `False`, the task is not
added to the gather list and a log message is emitted. This preserves existing
per-scheduler enable/disable behavior.

| Scheduler | Config flag |
|---|---|
| feedback | `config.feedback.feedback_enabled` |
| role_reminder | `config.role_reminder.role_reminder_enabled` |
| referral_reconciliation | `config.referral.referral_reconciliation_enabled` |
| instagram_stats | `config.instagram.instagram_stats_update_enabled` |
| instagram_stats_collector | `config.instagram.instagram_stats_collector_enabled` |

**All-disabled edge case:** If no schedulers are enabled, `asyncio.gather` would
return immediately and the worker process would exit, causing Docker to restart it
in a loop. Instead, if the task list is empty, `main_async` logs a warning and
calls `await asyncio.sleep(float("inf"))` so the container stays alive.

### Messenger client teardown

`feedback_scheduler.run_loop` has a `finally` block that closes the messenger
client (Bot HTTP session). In the unified worker all schedulers share one Bot.
If `feedback_scheduler.run_loop` exits or is cancelled, its `finally` would close
the shared session while other schedulers are still running.

**Fix:** `worker.py` passes a `_NoCloseMessengerClient` wrapper to
`feedback_scheduler.run_loop`. The wrapper delegates all operations but makes
`close()` a no-op. The shared Bot session is closed only in `worker.main()`'s
`finally` block after all tasks have completed.

### Asyncio exception handler

Each scheduler's `run_loop` calls `install_asyncio_exception_handler(service_name)`
internally. When run via `asyncio.gather`, they overwrite the loop's exception
handler in sequence. `worker.py` calls `install_asyncio_exception_handler("worker")`
once at the start of `main_async` before any tasks are created. The subsequent
per-scheduler registrations overwrite it, but all handlers behave identically
(they log the exception), so this has no practical effect. The handler name in logs
will reflect whichever scheduler registered last, which is acceptable.

### Container change: `build_role_reminder_scheduler_deps()`

`role_reminder_scheduler` currently builds `SqlAlchemyUserRepository` and
`SessionTransactionManager` directly without using `Container`. Add
`Container.build_role_reminder_scheduler_deps()` following the existing delegation
pattern: the method on `Container` delegates to a new function
`service_factory.build_role_reminder_scheduler_deps(session_factory)`, consistent
with all other `build_*_deps()` methods. The method returns:

```python
{
    "user_role_service": UserRoleService,
    "transaction_manager": SessionTransactionManager,
}
```

`messenger_client` is NOT included (it requires a Bot instance, which lives
outside Container). `config` is NOT included (passed directly). Worker.py
calls `run_loop(messenger_client, deps["user_role_service"], config)`.

### Existing scheduler files

All `*_scheduler.py` files remain **unchanged**. Only their `run_loop()` functions
are called from `worker.py`. The individual `main()` entry points remain functional
for standalone use or testing.

## Docker Compose changes

### docker-compose.yml

Remove five scheduler service definitions and replace with one. The `depends_on`
matches the existing pattern (`db: service_healthy`, `pgbouncer: service_started`):

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

### docker-compose.dev.yml

Apply the same change: remove the five scheduler services, add the `worker` service
with the same definition as above. The dev file has no scheduler-specific overrides,
so it mirrors the production snippet exactly.

Services removed from both files: `feedback_scheduler`, `role_reminder_scheduler`,
`referral_reconciliation_scheduler`, `instagram_stats_scheduler`,
`instagram_stats_collector_scheduler`.

Services unchanged: `outbox_processor`, `kafka_consumer`, `app`, `app_2`,
and all infrastructure services.

## Error handling

`_run_with_restart` wraps each `run_loop` call:

```python
async def _run_with_restart(name: str, coro_factory, restart_delay: float = 5.0):
    while True:
        try:
            await coro_factory()
        except Exception:
            logger.exception("Scheduler %s crashed, restarting in %.0fs", name, restart_delay)
            await asyncio.sleep(restart_delay)
```

If a scheduler's `run_loop` raises, the exception is logged and that scheduler
restarts after 5 seconds. Other schedulers continue unaffected.

## Testing

New test file: `tests/unit/test_worker.py`

- `test_worker_runs_all_enabled_schedulers` — mock all `run_loop` functions,
  assert each is called once
- `test_worker_skips_disabled_scheduler` — set one `enabled` flag to False,
  assert its `run_loop` is not called
- `test_run_with_restart_restarts_on_exception` — coro_factory raises once then
  returns; assert it was called twice (one failure + one success)
- `test_worker_all_disabled_does_not_exit` — set all enabled flags to False;
  assert `asyncio.sleep(float("inf"))` is called (i.e., process does not exit
  immediately)
- `test_no_close_messenger_client_does_not_close_delegate` — call `close()` on
  `_NoCloseMessengerClient`; assert the underlying delegate's `close()` is NOT
  called

Existing `test_*_scheduler.py` files remain unchanged.

## Resource impact

| Before | After |
|---|---|
| 5 Container instances | 1 Container instance |
| 5 DB pools (5×pool_size connections) | 1 DB pool |
| 5 Bot instances | 1 Bot instance |
| 5 Docker containers | 1 Docker container |
