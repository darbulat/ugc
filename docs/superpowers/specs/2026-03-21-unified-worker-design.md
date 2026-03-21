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
├── _run_with_restart(name, coro_factory, restart_delay=5.0)
│     Catches any exception, logs it, sleeps restart_delay, then re-runs.
│     This isolates scheduler failures: one crash does not cancel others.
├── main_async(config, container, bot, messenger_client)
│     Checks each scheduler's enabled flag.
│     Builds task list and calls asyncio.gather(*tasks).
└── main()
      load_config → configure_logging → install_exception_hooks
      → Container → Bot → asyncio.run(main_async(...))
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

### Container change: `build_role_reminder_scheduler_deps()`

`role_reminder_scheduler` currently builds its deps manually (not via Container).
Add `Container.build_role_reminder_scheduler_deps()` returning a dict with
`user_role_service`, `transaction_manager`, and `messenger_client` (or the
relevant deps that `role_reminder_scheduler.run_loop` needs). This makes the
pattern uniform across all schedulers.

### Existing scheduler files

All `*_scheduler.py` files remain **unchanged**. Only their `run_loop()` functions
are called from `worker.py`. The individual `main()` entry points remain functional
for standalone use or testing.

## Docker Compose changes

### docker-compose.yml and docker-compose.dev.yml

Remove five scheduler service definitions and replace with one:

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
    - pgbouncer
    - redis
  command: ["python", "-m", "ugc_bot.worker"]
  restart: unless-stopped
```

Services removed: `feedback_scheduler`, `role_reminder_scheduler`,
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

Existing `test_*_scheduler.py` files remain unchanged.

## Resource impact

| Before | After |
|---|---|
| 5 Container instances | 1 Container instance |
| 5 DB pools (5×pool_size connections) | 1 DB pool |
| 5 Bot instances | 1 Bot instance |
| 5 Docker containers | 1 Docker container |
