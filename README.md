# UGC Telegram Bot MVP

Minimal backend for the UGC matching bot. This repository currently contains
the project skeleton, configuration templates, and a working `/start` command
powered by `aiogram`.

## Quick start

1. Create a virtual environment and install deps:
   - `python -m venv .venv`
   - `source .venv/bin/activate`
   - `pip install -e .`
2. Copy env template:
   - `cp config/env.example .env`
3. Set `BOT_TOKEN` in `.env`.
4. Run the bot:
   - `python -m ugc_bot.app`

## Database migrations

Set `DATABASE_URL` in `.env`, then run:
- `alembic upgrade head`

## Project structure

The codebase is layered: domain → application (ports, services) → infrastructure; the bot and web apps consume application services.

- `src/ugc_bot/app.py` - main bot entrypoint (polling)
- `src/ugc_bot/config.py` - configuration loading (env)
- `src/ugc_bot/container.py` - DI container (repos, services)
- `src/ugc_bot/application/` - ports (repository interfaces), errors, services
- `src/ugc_bot/domain/` - entities and enums
- `src/ugc_bot/infrastructure/db/` - SQLAlchemy models, repositories, migrations, session
- `src/ugc_bot/infrastructure/kafka/` - Kafka publisher
- `src/ugc_bot/infrastructure/instagram/` - Instagram Graph API client
- `src/ugc_bot/bot/handlers/` - Telegram command and message handlers
- `src/ugc_bot/bot/middleware/` - error handling middleware
- `src/ugc_bot/admin/` - SQLAdmin FastAPI app
- `src/ugc_bot/scheduler/` - feedback scheduler
- `src/ugc_bot/metrics/` - metrics collector
- `src/ugc_bot/instagram_webhook_app.py` - Instagram webhook FastAPI app
- `src/ugc_bot/payment_webhook_app.py` - payment webhook (if present)
- `src/ugc_bot/feedback_scheduler.py`, `kafka_consumer.py`, `outbox_processor.py` - worker entrypoints

## Notes

For production, set `ADMIN_PASSWORD` and `ADMIN_SECRET` in `.env`; the admin app requires them to start.
