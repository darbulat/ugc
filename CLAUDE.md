# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
make install-dev           # uv sync --all-extras

# Code quality (run all: make all)
make format                # ruff format
make format-check          # ruff format --check
make lint                  # ruff check
make typecheck             # mypy

# Testing
make test                  # unit + integration tests (excludes e2e)
make coverage              # tests with coverage (98% threshold)
make e2e                   # Playwright E2E tests
make e2e-telegram          # Real Telegram E2E (requires credentials)

# Run a single test file
uv run pytest tests/path/to/test_file.py -v

# Database
make migrate               # Run Alembic migrations

# Local dev
python -m ugc_bot.app      # Polling bot (dev mode)
make admin                 # Admin panel on port 8001

# Docker
make docker-up             # Full production stack
make dev-up                # Dev stack (no backup service)
make deploy-apps           # Zero-downtime rolling deploy
```

## Architecture

**Hexagonal architecture (Ports & Adapters) with DDD layering:**

```
src/ugc_bot/
├── domain/          # Pure entities & enums, no dependencies
├── application/     # Use cases: ports.py (ABC interfaces), services/, errors.py
├── infrastructure/  # Concrete adapters: db/, kafka/, instagram/, redis_cache.py
├── bot/             # aiogram handlers, middleware, keyboards, texts/
├── admin/           # SQLAdmin FastAPI app
├── miniapp/         # Telegram Mini App FastAPI endpoints + HTML templates
├── container/       # Dependency injection container
└── config.py        # pydantic-settings config
```

**Key principle:** Services depend only on abstract ports (`application/ports.py`), never on infrastructure directly. Infrastructure adapters implement those ports.

**Entry points:**
- `telegram_webhook_app.py` — production Telegram webhook (port 9999)
- `instagram_webhook_app.py` — Instagram webhook (port 8002)
- `admin/app.py` — admin dashboard (port 8001)
- `kafka_consumer.py`, `*_scheduler.py`, `outbox_processor.py` — background workers

## Infrastructure

- **DB:** PostgreSQL 16 + PostGIS, accessed via PgBouncer (port 6432); 64 Alembic migrations in `infrastructure/db/migrations/`
- **Cache/FSM:** Redis (aiogram FSM state storage + caching)
- **Events:** Kafka (Confluent 7.6.1) with outbox pattern for distributed consistency
- **Monitoring:** Prometheus + Grafana + Loki + AlertManager; configs in `config/monitoring/`

## Testing

Test types and markers:
- `tests/unit/` — pure unit tests
- `tests/integration/` — tests with real DB (`@pytest.mark.integration`)
- `tests/e2e/` — Playwright browser tests + Telethon real-Telegram tests
- `tests/admin/` — admin panel tests

**In-memory fakes** for repositories are in `infrastructure/memory_repositories.py` and `tests/helpers/fakes.py` — use these when testing services without a real DB.

Pytest timeout is 5 seconds per test. Coverage threshold is 98%.

## Workflow

### Development workflow (REQUIRED)

**NEVER make changes directly in `main` branch.** Always use a feature branch:

```bash
# 1. Create and switch to a feature branch
git checkout -b feature/your-branch-name

# 2. Make changes, then verify locally
make fix  # format + format-check + lint + typecheck + coverage (use before committing)

# 3. Commit and push
git add <files>
git commit -m "..."
git push -u origin feature/your-branch-name

# 4. SSH to dev server and deploy
ssh root@45.130.145.27
cd ugc
git pull
git checkout feature/your-branch-name
make dev-up

# 5. Run tests on dev server
DEV_NETWORK=ugc_default make test-all-docker-dev

# 6. Review test results; fix any failures and repeat from step 2
```

### Local code quality

After making any code changes, always run `make fix` to auto-format and verify (matches CI):

```bash
make fix  # format + format-check + lint + typecheck + coverage (use before committing)
make all  # format-check + lint + typecheck + coverage (exact replica of GitHub Actions)
```

`make all` is identical to GitHub Actions — no auto-format. Run `make fix` to auto-format first, then verify.

## Compact Instructions

During compaction, preserve in priority order:
1. Architectural decisions (NEVER summarize)
2. Changed files and key modifications
3. Current verification status (pass/fail)
4. Open TODOs and rollback notes
5. Tool outputs (can be dropped, keep pass/fail only)

## Key Patterns

- **Repository pattern:** 20+ abstract repos in `application/ports.py`, SQLAlchemy implementations in `infrastructure/db/repositories.py`, in-memory implementations for tests. **Repositories use `_resolve_session(self.session_factory, session)` context manager** — if `session` is provided it's used as-is, if `None` the repo opens its own session from `session_factory`. This means repos can be called without an explicit session (they'll manage their own transaction), but passing a session keeps multiple operations in one transaction.
- **Service layer is preferred over direct repo calls** in endpoints. If a service method doesn't exist, add one to the service rather than calling repos directly from `miniapp/api.py` or `bot/` handlers.
- **Outbox pattern:** `OutboxRepository` + `outbox_processor.py` for event-driven consistency
- **Zero-downtime deploy:** `scripts/deploy_apps_zero_downtime.sh` rolling deploy between `app` and `app_2` replicas
- **Session pooling:** PgBouncer in session mode (required for Alembic compatibility)
- **Instagram integration:** Graph API for official stats, `aiograpi` for web scraping (`infrastructure/instagram/`)
