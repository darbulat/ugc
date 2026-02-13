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

## Database migrations

Set `DATABASE_URL` in `.env`, then run:
- `alembic upgrade head`

## E2E tests

- **Local** (admin started automatically on port 8001): `make e2e`
- **Against deployed dev**: set `E2E_BASE_URL` (and optionally `E2E_ADMIN_USERNAME` / `E2E_ADMIN_PASSWORD`) in `.env` or the environment, then run `make e2e-dev`
- **Docker** (Postgres + admin in containers): `make e2e-docker`

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
