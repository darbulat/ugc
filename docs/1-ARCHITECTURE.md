---
title: Architecture Overview
tags: [architecture, core, index]
aliases: [Architecture Overview, System Design]
---

# Architecture Overview

The UGC Bot follows **Hexagonal Architecture (Ports & Adapters)** with **Domain-Driven Design (DDD)** layering.

## Layer Structure

```
┌─────────────────────────────────────────────────────────────┐
│  Bot Handlers, Admin Panel, Mini App, Webhooks              │
│  (Telegram, Instagram, Max, FastAPI endpoints)              │
├─────────────────────────────────────────────────────────────┤
│  Application Layer (Use Cases)                              │
│  ├─ Services (20+ business logic classes)                   │
│  ├─ Ports (Abstract interfaces for repositories/clients)    │
│  └─ DTOs & Errors                                           │
├─────────────────────────────────────────────────────────────┤
│  Domain Layer (Pure entities & business rules)              │
│  ├─ Entity classes (User, Offer, BloggerRating, etc.)       │
│  └─ Enums (UserRole, OfferStatus, MessengerType, etc.)      │
├─────────────────────────────────────────────────────────────┤
│  Infrastructure Layer (Concrete adapters)                   │
│  ├─ Database (SQLAlchemy models, repositories)              │
│  ├─ External APIs (Instagram, Telegram, Kafka)              │
│  ├─ Cache (Redis)                                           │
│  └─ Event Bus (Kafka with outbox pattern)                   │
└─────────────────────────────────────────────────────────────┘
```

## Key Principles

### 1. **Dependency Inversion**
- Services depend only on abstract **Ports** (interfaces)
- Infrastructure adapters **implement** those ports
- Never import infrastructure directly in services

### 2. **No Framework Leakage**
- Domain entities have **no dependencies** on frameworks
- Services don't import aiogram, fastapi, or sqlalchemy
- Controllers/handlers translate framework events to DTOs

### 3. **Separation of Concerns**
- **Domain:** Pure business logic (no I/O, no state)
- **Application:** Use cases, orchestration, error handling
- **Infrastructure:** Concrete implementations, DB, APIs
- **Interface:** Controllers, handlers, endpoints

## Core Components

### Domain Layer (`src/ugc_bot/domain/`)
```
├── entities.py       # User, Offer, BloggerRating, etc.
├── enums.py          # UserRole, OfferStatus, MessengerType
└── value_objects.py  # Phone, Email, URL (if needed)
```

**Key Rule:** Entities can only depend on other entities and enums. No services, no I/O.

### Application Layer (`src/ugc_bot/application/`)
```
├── ports.py          # Abstract interfaces (20+)
├── services/         # Business logic services
│   ├── user_service.py
│   ├── offer_service.py
│   ├── creator_service.py
│   └── ...
├── messenger/        # Messenger-neutral DTOs & contexts
│   ├── dto.py
│   ├── ports.py
│   └── context.py
└── errors.py         # Custom exceptions
```

**Key Pattern:** All repositories, external clients, and event publishers are injected via constructor.

### Infrastructure Layer (`src/ugc_bot/infrastructure/`)
```
├── db/               # PostgreSQL via SQLAlchemy
│   ├── models.py     # ORM models
│   ├── repositories.py
│   └── migrations/   # Alembic
├── kafka/            # Kafka publisher & consumer
├── instagram/        # Instagram Graph API + web scraping
├── redis_cache.py    # Cache & FSM storage
└── messenger/        # Telegram, Instagram, Max adapters
    ├── telegram/
    ├── instagram/
    └── max/
```

### Interface Layer
```
├── bot/              # Telegram handlers & middleware
│   └── handlers/     # /start, registration, offers, etc.
├── miniapp/          # FastAPI Telegram Mini App
├── admin/            # SQLAdmin dashboard
└── *_webhook_app.py  # Entry points (Telegram, Instagram, Max)
```

## Data Flow Example: User sends message to bot

```
1. Telegram server → /webhook/telegram (FastAPI)
2. FastAPI parses aiogram.Update
3. TelegramEventAdapter converts to messenger.IncomingMessage (DTO)
4. Handler extracts chat_id, user_id, text from message
5. Handler calls UserService.get_or_create_user()
6. UserService queries UserRepository.get_by_external_id()
7. UserRepository executes SQLAlchemy query
8. Entity loaded from DB, returned to service
9. Service applies business logic, may save via repository
10. Handler builds response using UserMessengerContext
11. Context calls TelegramMessengerClient.send_text()
12. TelegramMessengerClient calls bot.send_message()
13. Response sent back to user
```

## Key Patterns

### Repository Pattern
- **Port:** `UserRepository` interface in `application/ports.py`
- **Implementation:** `UserSQLRepository` in `infrastructure/db/repositories.py`
- **Usage:** Services request repos, repos return entities
- **Session Management:** Repos use `_resolve_session(factory, session)` context manager

### Service Layer
- **Location:** `application/services/`
- **Responsibility:** Orchestrate business logic using repos and external clients
- **Dependency Injection:** Constructor injection from container
- **No Direct Repo Calls:** Endpoints should call services, not repos directly

### Outbox Pattern (Event Consistency)
- Every write operation creates an `Outbox` entry
- Background worker (`outbox_processor.py`) publishes to Kafka
- Guarantees "at least once" delivery without distributed transactions

### FSM (Finite State Machine)
- Telegram: `aiogram.fsm.context.FSMContext` stored in Redis
- Tracks user's conversation state (e.g., `waiting_for_bio`, `selecting_offer`)
- Used by handlers to determine which handler should process next message

## Multi-Messenger Architecture

Services are **messenger-agnostic**. Multiple adapters implement `MessengerClient` port:
- **Telegram:** `TelegramMessengerClient` in `infrastructure/messenger/telegram/`
- **Max:** `MaxMessengerClient` in `infrastructure/messenger/max/`
- **Instagram DM:** (future) `InstagramDMMessengerClient`

Each has an `EventAdapter` to convert native events to shared DTOs.

## Technology Stack

| Layer | Technology |
|-------|------------|
| **Web Framework** | FastAPI (async/await) |
| **Telegram Bot** | aiogram 3.x |
| **Database** | PostgreSQL 16 + PostGIS |
| **Connection Pooling** | PgBouncer (session mode) |
| **ORM** | SQLAlchemy 2.0 |
| **Migrations** | Alembic (64+ migrations) |
| **Caching/FSM** | Redis |
| **Event Bus** | Kafka (Confluent 7.6.1) |
| **Scheduling** | APScheduler |
| **Admin UI** | SQLAdmin |
| **Monitoring** | Prometheus + Grafana + Loki |

---

## Related Documents
- [[Ports & Adapters Pattern]]
- [[Repository Pattern]]
- [[Outbox Pattern]]
- [[Development Workflow]]
