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

- `src/ugc_bot/app.py` - app entrypoint
- `src/ugc_bot/bot/` - Telegram bot handlers
- `src/ugc_bot/services/` - business services (stubs)
- `src/ugc_bot/storage/` - storage layer (stubs)
- `src/ugc_bot/scheduler/` - scheduler (stub)

## Logging and Monitoring

The project includes ELK stack (Elasticsearch, Logstash, Kibana) for centralized log viewing and analysis.

### ELK Stack

- **Elasticsearch**: http://localhost:9200 - Log storage and search
- **Kibana**: http://localhost:5601 - Web interface for log visualization
- **Filebeat**: Automatically collects logs from Docker containers

See [docs/LOGGING.md](docs/LOGGING.md) for detailed logging configuration and ELK setup instructions.

## Notes

This is the first milestone: initialization, config templates, logging, and a
working `/start` command. Data storage and full flows will be added next.
