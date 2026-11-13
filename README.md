# UGC Telegram Bot MVP

Minimal backend for the UGC matching bot. This repository contains the project
skeleton, configuration templates, and a working bot powered by `aiogram`.

## Quick start

1. Create a virtual environment and install deps:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -e .`
2. Copy env template:
   - `cp config/env.example .env`
3. Set `BOT_TOKEN` in `.env`.
4. Run the bot (local polling):
   - `python -m ugc_bot.app`
5. For production: use webhook mode via `uvicorn ugc_bot.telegram_webhook_app:app`.
   Set `WEBHOOK_BASE_URL` and optionally `WEBHOOK_SECRET` in `.env`.

## Production deploy (zero-downtime for app / app_2)

To update the Telegram webhook app without taking both instances down at once, use rolling deploy:

- **From repo root:** `make deploy-apps`  
  Builds the app image, then updates `app`, waits for it to be healthy, then updates `app_2`. Nginx keeps routing traffic to the instance that is still up.
- **With compose overlay:**  
  `make deploy-apps COMPOSE_ARGS="-f docker-compose.yml -f docker-compose.prod.yml"`  
  Or run the script directly:  
  `./scripts/deploy_apps_zero_downtime.sh -f docker-compose.yml -f docker-compose.prod.yml`

Ensure migrations are applied before or during your deploy (e.g. run `migrate` or your migration job first).

## Database migrations

Set `DATABASE_URL` in `.env`, then run:
- `alembic upgrade head`

In the Docker stack, app services connect to PostgreSQL via PgBouncer
(pgbouncer:6432); backup and postgres_exporter use a direct connection to db:5432.
PgBouncer uses session pooling so Alembic migrations work without changes.

## Local tests

- Run `make test-local-full` for unit and integration tests, including the PostgreSQL financial suite. The runner and PostgreSQL share the Docker VM clock, so host and VM clock drift cannot invalidate timestamp checks. The test stack uses a fresh database.
- Run `make e2e-synthetic` for browser tests with the synthetic Mini App and admin services.

## E2E tests

- **Local** (admin starts automatically on a free loopback port): `make e2e`
- **Against deployed dev (Playwright)**: set `E2E_BASE_URL` (and optionally `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD`) in `.env` or the environment, then run `make e2e-dev`
- **Against deployed dev (Telegram)**: set `E2E_DATABASE_URL` to the dev DB and `E2E_CLEAN_TELEGRAM=darbulat` in `.env`, then run `make e2e-telegram-dev` (or `make e2e-telegram`). Only the user with that telegram is removed before tests so the rest of dev data is untouched.
- **Full suite against dev** (unit + integration + Playwright e2e + Telegram e2e, no Docker): set `E2E_BASE_URL` in `.env`; for Telegram e2e also set `E2E_DATABASE_URL` and `E2E_CLEAN_TELEGRAM=darbulat`. Then run `make test-all-dev`.
- **Full suite in container on dev network** (no Python on host): dev stack and tests run in Docker; the test container joins the dev stack network. In `.env` set `DEV_NETWORK=ugc_default`, `E2E_BASE_URL=http://admin:8001`, `E2E_ADMIN_USERNAME` and `E2E_ADMIN_PASSWORD` to match the dev admin (or leave unset if `ADMIN_USERNAME`/`ADMIN_PASSWORD` are in `.env`), `E2E_DATABASE_URL=postgresql+psycopg://user:pass@db:5432/ugc`, `E2E_CLEAN_TELEGRAM=darbulat`, and Telegram E2E vars. Then run `make test-all-docker-dev`.
- **Docker** (Postgres + admin in containers): `make e2e-docker`
- **Telegram bot E2E** (Docker): set `TELEGRAM_E2E_*` and once `make e2e-telegram-docker-auth`; then `make e2e-telegram-docker`. To start with a clean DB on each run, set `E2E_DATABASE_URL` to the same DB as the bot — pytest will clean users before tests; or run `make e2e-telegram-clean` manually.

## Project structure

The codebase is layered: domain → application (ports, services) → infrastructure;
the bot and web apps consume application services.

- `src/ugc_bot/app.py` - bot dispatcher factory, used by webhook app
- `src/ugc_bot/config.py` - configuration loading (env)
- `src/ugc_bot/container/` - DI container (repos, services)
- `src/ugc_bot/application/` - ports (repository interfaces), errors, services
- `src/ugc_bot/domain/` - entities and enums
- `src/ugc_bot/infrastructure/db/` - SQLAlchemy models, repositories, migrations
- `src/ugc_bot/infrastructure/kafka/` - Kafka publisher
- `src/ugc_bot/infrastructure/instagram/` - Instagram Graph API client
- `src/ugc_bot/bot/handlers/` - Telegram command and message handlers
- `src/ugc_bot/bot/middleware/` - error handling middleware
- `src/ugc_bot/admin/` - SQLAdmin FastAPI app
- `src/ugc_bot/scheduler/` - APScheduler utilities
- `src/ugc_bot/metrics/` - metrics collector
- `src/ugc_bot/telegram_webhook_app.py` - production webhook (FastAPI)
- `src/ugc_bot/instagram_webhook_app.py` - Instagram webhook (FastAPI)
- `src/ugc_bot/feedback_scheduler.py`, `role_reminder_scheduler.py`,
  `kafka_consumer.py`, `outbox_processor.py` - worker entrypoints

## Notes

For production, set `ADMIN_PASSWORD` and `ADMIN_SECRET` in `.env`; the admin app
requires them to start. Payments are handled via `TelegramPaymentProvider` in
the Telegram webhook app.
