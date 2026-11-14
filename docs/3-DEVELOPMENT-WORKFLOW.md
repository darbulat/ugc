---
title: Development Workflow
tags: [workflow, development, guide]
aliases: [Development Workflow, Dev Setup]
---

# Development Workflow

## Setup

### Prerequisites
- Python 3.10+
- PostgreSQL 16
- Redis (for caching & FSM)
- Kafka (optional for local dev, can use fake)

### Local Environment

1. **Create virtual environment:**
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
```

2. **Install dependencies:**
```bash
make install-dev  # Runs: uv sync --all-extras
```

3. **Copy environment template:**
```bash
cp config/env.example .env
```

4. **Set required variables in `.env`:**
```env
BOT_TOKEN=<your_telegram_bot_token>
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/ugc
REDIS_URL=redis://localhost:6379
```

5. **Create database:**
```bash
createdb ugc
make migrate  # Run Alembic migrations
```

## Development Commands

### Code Quality (All-in-One)
```bash
make fix      # Auto-format + lint + typecheck + coverage
make all      # format-check + lint + typecheck + coverage (no auto-format)
```

**This is required before every commit!**

### Individual Quality Checks
```bash
make format            # Auto-format with ruff
make format-check      # Check formatting (don't fix)
make lint              # Lint with ruff
make typecheck         # Type check with mypy
make coverage          # Run tests with coverage (98% threshold)
```

### Testing
```bash
make test              # Unit + integration tests
make e2e               # Playwright E2E tests
make e2e-telegram      # Real Telegram E2E (requires credentials)
```

### Running the Bot Locally
```bash
# Polling mode (good for local development)
python -m ugc_bot.app

# Or webhook mode (for testing webhooks)
uvicorn ugc_bot.telegram_webhook_app:app --reload --port 9999
```

### Admin Panel
```bash
make admin  # Open http://localhost:8001
```

## Git Workflow (REQUIRED)

### Branch Naming
```
feature/name-of-feature     # New feature
fix/description-of-fix      # Bug fix
refactor/area-of-refactoring
docs/what-documentation
test/test-area-or-scenario
```

### Creating a Feature Branch
```bash
# Always create from main
git checkout main
git pull origin main

# Create feature branch
git checkout -b feature/your-feature-name
```

### Making Changes

1. **Write code** following the architecture patterns

2. **Format and verify:**
```bash
make fix  # Auto-format + verify
```

3. **Run tests:**
```bash
make test  # Unit + integration
make e2e   # End-to-end (if applicable)
```

4. **Commit with clear message:**
```bash
git add src/ugc_bot/path/to/file.py
git commit -m "feat: add user verification flow

- Implement phone verification
- Add verification token generation
- Update UserService with verification logic

Closes #123"
```

### Pushing & Pull Request

```bash
git push -u origin feature/your-feature-name
```

Then create a pull request on GitHub (never push directly to main).

### Pull request review

The Lint and Test workflow runs the repository checks. For automatic code
review, connect `darbulat/ugc` in
[Codex code review settings](https://chatgpt.com/settings/code-review) and
enable **Automatic review** for the repository. Confirm setup by checking for
a Codex review on a pull request. To request one on an open PR, comment
`@codex review`.

## Development on Dev Server

### SSH to Dev Server
```bash
ssh root@45.130.145.27
cd /root/ugc
```

### Deploy Your Feature Branch
```bash
git fetch origin
git checkout feature/your-branch-name
git pull origin feature/your-branch-name

make dev-up  # Start dev Docker stack with your changes
```

### Run Tests on Dev Server
```bash
DEV_NETWORK=ugc_default make test-all-docker-dev
```

### Debug
```bash
# Check logs from all containers
docker-compose logs -f

# Check specific service
docker-compose logs -f telegram_bot_app
```

### Rollback
```bash
git checkout main
make dev-up  # Redeploy main
```

## Common Tasks

### Add a New Handler
1. Create file in `src/ugc_bot/bot/handlers/your_handler.py`
2. Define handler function with `@router.message(Command("start"))`
3. Import router in `src/ugc_bot/app.py` and register
4. Write tests in `tests/unit/bot/handlers/test_your_handler.py`
5. Run `make test` to verify

### Add a Service
1. Create `src/ugc_bot/application/services/your_service.py`
2. Define service class with dependency injection in `__init__`
3. Create port interface if needed in `application/ports.py`
4. Register in `src/ugc_bot/container/` DI container
5. Write tests in `tests/unit/application/services/test_your_service.py`

### Add a Database Migration
1. Make changes to model in `src/ugc_bot/infrastructure/db/models.py`
2. Generate migration:
```bash
alembic revision --autogenerate -m "add_new_column_to_users"
```
3. Review generated migration in `infrastructure/db/migrations/versions/`
4. Run `make migrate` to apply

### Add an API Endpoint
1. Add endpoint in `src/ugc_bot/miniapp/api.py` or create router
2. Define request/response DTOs
3. Call services (not repos directly)
4. Write tests in `tests/integration/miniapp/test_api.py`
5. Document in [[API Documentation]]

## Testing Strategy

### Unit Tests
- Mock all dependencies
- Test service logic in isolation
- Location: `tests/unit/`
- No database, no external APIs

### Integration Tests
- Use real database (test DB)
- Use in-memory fake repositories
- Test service + repository layer
- Location: `tests/integration/`
- Marked with `@pytest.mark.integration`

### E2E Tests
- Full stack including UI
- Playwright for admin panel
- Telethon for Telegram bot
- Location: `tests/e2e/`
- Requires real environment or Docker

**Coverage Threshold:** 98% required before merge

## Debugging

### View Test Coverage
```bash
make coverage  # Creates htmlcov/index.html
open htmlcov/index.html
```

### Debug a Single Test
```bash
uv run pytest tests/path/to/test_file.py::test_function_name -v -s
```

### Database Inspection
```bash
# Connect to dev DB
psql postgresql://user:password@45.130.145.27:5432/ugc

# Or via Docker
docker exec -it ugc-db psql -U user -d ugc
```

## Performance Tips

1. **Use indexes** — Add `@pytest.mark.integration` to slow tests
2. **Profile bottlenecks** — Use `make coverage` to identify slow tests
3. **Cache frequently accessed data** — Use Redis via `RedisCache` port
4. **Batch database queries** — Use repository methods that fetch multiple entities

---

## Related Documents
- [[Architecture Overview]]
- [[Git Workflow]]
- [[Code Quality]]
- [[Testing Strategy]]
