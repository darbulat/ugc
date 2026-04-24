---
title: Quick Reference
tags: [reference, quick-start, cheatsheet]
aliases: [Quick Reference, Cheatsheet]
---

# Quick Reference Guide

## Essential Commands

### Setup & Dependencies
```bash
make install-dev          # Install all dependencies
make migrate              # Run database migrations
python -m ugc_bot.app     # Start bot locally (polling)
```

### Code Quality (BEFORE EVERY COMMIT!)
```bash
make fix                  # Auto-format + lint + typecheck
make all                  # Verify without auto-format (like CI)
```

### Testing
```bash
make test                 # Unit + integration tests
make e2e                  # End-to-end tests
make coverage             # Tests with coverage report
```

### Docker
```bash
make dev-up               # Start full dev stack
make dev-down             # Stop dev stack
docker-compose logs -f    # View live logs
```

### Git
```bash
git checkout -b feature/name   # Create feature branch
git add src/...
git commit -m "feat: description"
git push -u origin feature/name
```

---

## Project Structure

```
src/ugc_bot/
├── domain/              # Pure business logic
│   ├── entities.py      # User, Offer, BloggerRating
│   └── enums.py         # UserRole, OfferStatus, MessengerType
├── application/         # Use cases & ports
│   ├── ports.py         # Abstract interfaces (20+)
│   ├── services/        # Business logic (20+ services)
│   │   ├── user_service.py
│   │   ├── offer_service.py
│   │   └── ...
│   ├── messenger/       # Multi-messenger DTOs & contexts
│   │   ├── dto.py       # IncomingMessage, IncomingCallback
│   │   ├── ports.py     # MessengerClient, EventAdapter
│   │   └── context.py   # MessageContext, CallbackContext
│   └── errors.py        # Custom exceptions
├── infrastructure/      # Concrete implementations
│   ├── db/              # PostgreSQL + SQLAlchemy
│   │   ├── models.py    # ORM models
│   │   ├── repositories.py
│   │   └── migrations/  # Alembic SQL migrations
│   ├── kafka/           # Event publishing
│   ├── instagram/       # Instagram API integration
│   ├── redis_cache.py   # Caching
│   └── messenger/       # Adapter implementations
│       ├── telegram/    # TelegramMessengerClient
│       ├── max/         # MaxMessengerClient (in progress)
│       └── instagram/   # Instagram DM adapter
├── bot/                 # Telegram handlers & middleware
│   ├── handlers/        # Handler functions
│   │   ├── start.py
│   │   ├── registration.py
│   │   ├── offers.py
│   │   └── ...
│   ├── middleware/      # Error handling, logging
│   └── keyboards/       # Inline keyboards
├── miniapp/             # FastAPI Telegram Mini App
│   ├── app.py           # FastAPI app
│   ├── api.py           # API endpoints
│   ├── schemas.py       # Request/response schemas
│   └── templates/       # HTML templates
├── admin/               # SQLAdmin dashboard
│   └── app.py
├── container/           # Dependency injection container
│   └── __init__.py      # Container class with service factories
├── scheduler/           # Background schedulers
│   ├── feedback_scheduler.py
│   └── role_reminder_scheduler.py
├── config.py            # Pydantic config from environment
├── app.py               # Bot dispatcher factory
├── telegram_webhook_app.py  # Production Telegram webhook
├── instagram_webhook_app.py # Instagram webhook
├── max_webhook_app.py       # Max webhook (in progress)
├── kafka_consumer.py    # Event consumer
└── outbox_processor.py  # Outbox → Kafka worker
```

---

## Common Patterns

### Creating a Service
```python
# application/services/my_service.py
from application.ports import MyRepository

class MyService:
    def __init__(self, repo: MyRepository):
        self.repo = repo  # Injected, not imported
    
    async def do_something(self, id: UUID) -> Entity:
        entity = await self.repo.get_by_id(id)
        # Apply business logic
        return entity
```

### Implementing a Repository
```python
# infrastructure/db/repositories.py
class MyEntitySQLRepository(MyEntityRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory
    
    async def get_by_id(self, id: UUID) -> MyEntity | None:
        async with self._resolve_session(self.session_factory, None) as session:
            result = await session.execute(
                select(MyEntityModel).where(MyEntityModel.id == id)
            )
            model = result.scalar_one_or_none()
            return model.to_entity() if model else None
```

### Writing a Handler
```python
# bot/handlers/my_handler.py
from aiogram import Router, types
from aiogram.filters import Command

router = Router()

@router.message(Command("mycommand"))
async def handle_my_command(message: types.Message, container: Container):
    user = await container.user_service.get_or_create_user(
        external_id=message.from_user.id,
        messenger_type=MessengerType.TELEGRAM,
        username=message.from_user.username
    )
    await message.answer(f"Hello, {user.username}!")
```

### Database Transaction
```python
# Using session manager for atomic operations
async with self.session_factory() as session:
    user = await self.user_repo.save(user, session=session)
    offer = await self.offer_repo.save(offer, session=session)
    # Both commit together or both rollback on error
```

### Kafka Outbox Pattern
```python
# Save entity + emit event atomically
async with self.session_factory() as session:
    offer = await self.offer_repo.update_status(
        offer_id, OfferStatus.ACCEPTED, session=session
    )
    
    # Create outbox entry in same transaction
    await self.outbox_repo.save(
        OutboxEntry(
            event_type="OfferAccepted",
            aggregate_id=offer.id,
            payload={"offer_id": str(offer.id)}
        ),
        session=session
    )
```

---

## Key Files to Know

| File | Purpose |
|------|---------|
| `src/ugc_bot/config.py` | Configuration from environment |
| `src/ugc_bot/container/__init__.py` | DI container with service factories |
| `src/ugc_bot/app.py` | Bot dispatcher setup |
| `src/ugc_bot/telegram_webhook_app.py` | Production webhook entry point |
| `src/ugc_bot/bot/handlers/` | Telegram command handlers |
| `src/ugc_bot/application/ports.py` | All repository + client interfaces |
| `src/ugc_bot/application/services/` | Business logic services |
| `src/ugc_bot/infrastructure/db/models.py` | SQLAlchemy ORM models |
| `src/ugc_bot/infrastructure/db/repositories.py` | Repository implementations |
| `Makefile` | Build commands |
| `pyproject.toml` | Python dependencies |
| `.env.example` | Environment template |

---

## Database Essentials

### Common Queries
```bash
# Connect locally
psql postgresql://user:password@localhost:5432/ugc

# Common commands
\d                  # List tables
\d table_name       # Describe table
SELECT * FROM users LIMIT 10;
```

### Connection String Format
```
postgresql+psycopg://username:password@host:port/database
```

### Migrations
```bash
make migrate          # Apply all pending migrations
alembic current       # Show current revision
alembic downgrade -1  # Downgrade one revision
```

---

## Environment Variables

### Essential
```env
BOT_TOKEN=<from BotFather>
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/ugc
REDIS_URL=redis://localhost:6379
```

### Optional
```env
WEBHOOK_BASE_URL=https://yourdomain.com
WEBHOOK_SECRET=<random_string>
ADMIN_PASSWORD=<admin_panel_pass>
LOG_LEVEL=INFO
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Import error** | Check `__init__.py` exports, verify virtual env activated |
| **Database connection fails** | Check `.env` DATABASE_URL, ensure PostgreSQL running |
| **Type errors** | Run `make typecheck`, check mypy output |
| **Tests fail** | Run `make fix` first, then `make test -v` |
| **Docker can't start** | Check port availability, run `docker system prune` |
| **Redis connection fails** | Ensure Redis running, check REDIS_URL in `.env` |

---

## Development Workflow (TL;DR)

1. **Create branch:** `git checkout -b feature/my-feature`
2. **Code:** Write feature following patterns above
3. **Verify:** `make fix` then `make test`
4. **Commit:** `git add . && git commit -m "feat: description"`
5. **Push:** `git push -u origin feature/my-feature`
6. **Deploy to dev:** SSH to dev server, checkout branch, `make dev-up`
7. **Test:** `DEV_NETWORK=ugc_default make test-all-docker-dev`
8. **Create PR:** Submit on GitHub, get reviewed
9. **Merge:** GitHub auto-merge after approval + CI passes

---

## Related Documents
- [[Architecture Overview]]
- [[Development Workflow]]
- [[Patterns & Principles]]
- [[Glossary]]
