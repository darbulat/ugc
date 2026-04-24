---
title: Glossary
tags: [glossary, reference, terms]
aliases: [Glossary, Terms, Terminology]
---

# Glossary

## A

### ADR (Architectural Decision Record)
A document capturing an important architectural decision, its context, rationale, and consequences.

**Location:** `docs/adr/`
**Format:** `ADR-###: Title`

### Adapter
A concrete implementation of a [[#Port]]. Implements a port interface to interact with external systems (database, APIs, frameworks).

**Example:** `TelegramMessengerClient` is an adapter implementing `MessengerClient` port.

### Alembic
Database migration tool for SQLAlchemy. Generates SQL scripts to evolve schema.

**Usage:** `make migrate`

### Aggregate Root
An entity that acts as the entry point to a cluster of related entities. Only access related entities through the aggregate root.

**Example:** `User` is an aggregate root; `OfferResponse` is accessed through `Offer`.

---

## B

### Backlink
In Obsidian, a link from document B to document A creates a "backlink" in A showing that A is referenced by B. Useful for discovering relationships.

### Blog/Blogger
See [[#Creator]].

---

## C

### Cache
In-memory data store for frequently accessed information. Implemented via Redis.

**Usage:** `await cache.get(key)`, `await cache.set(key, value, ttl=300)`

### Context Manager
Python pattern (`async with`) for resource management (open/close connections, transactions).

**Example:** `async with self._resolve_session(...) as session:`

### Creator
A user who creates content for brands. Role = `UserRole.CREATOR`

**Permissions:** View offers, submit responses, manage portfolio.

---

## D

### Database Model
SQLAlchemy ORM class representing a database table.

**Location:** `infrastructure/db/models.py`
**Naming:** PascalCase, e.g., `UserModel`, `OfferModel`

### DTO (Data Transfer Object)
An object for transferring data between layers (usually with validation).

**Location:** `application/dto.py`, `application/messenger/dto.py`
**Purpose:** Decouple layers from entity structure

### Domain
The core business logic of the application, independent of frameworks.

**Location:** `domain/` folder
**Contains:** Entities, enums, value objects (no framework imports)

### Domain-Driven Design (DDD)
Software development approach focusing on complex business logic.

**Principles:** Entities, value objects, aggregates, repositories, services, bounded contexts.

---

## E

### Entity
An object with a unique identity that persists over time. Mutable.

**Example:** `User(id=UUID(...), name="John", ...)`

**Location:** `domain/entities.py`

### Enum
A set of named constants. Used to represent fixed sets of values.

**Examples:** `UserRole`, `OfferStatus`, `MessengerType`

**Location:** `domain/enums.py`

### Event
Something that happened in the system, published to Kafka for consistency.

**Example:** "OfferAccepted", "UserRegistered"

**Pattern:** [[#Outbox Pattern]]

---

## F

### FSM (Finite State Machine)
A state machine with defined states and transitions. Used for conversation flow in chatbots.

**Locations:** 
- Telegram: aiogram FSM stored in Redis
- Max: maxapi FSM

**Example:** States: `waiting_for_bio`, `selecting_offer`, `confirming_offer`

### Foreign Key (FK)
Database constraint linking a column to a primary key in another table.

**Purpose:** Referential integrity

---

## G

### Graph View
Obsidian feature showing document relationships as a network graph.

**Usage:** Ctrl+G (Cmd+G on Mac)

---

## H

### Handler
A function processing a user interaction (message, button press, command).

**Location:** `bot/handlers/`
**Pattern:** Receives message → calls service → sends response

**Example:** 
```python
@router.message(Command("start"))
async def handle_start(message: Message):
    await message.answer("Welcome!")
```

### Hexagonal Architecture
See [[#Ports & Adapters]].

---

## I

### Idempotent
An operation producing the same result regardless of how many times it's called.

**Importance:** Critical for distributed systems (Kafka consumers, webhooks).

**Example:** Marking an outbox entry as "published" twice has same effect as once.

### Inbox Pattern
(Opposite of [[#Outbox Pattern]]) Receiving events into a table before processing.

**Usage:** Handling webhook payloads safely.

---

## J

### Kafka
A distributed message broker. Provides event streaming for the system.

**Topics:**
- `offer-events` — Offer lifecycle
- `user-events` — User registration, updates
- `payment-events` — Payments processed

**Pattern:** [[#Outbox Pattern]]

---

## L

### Loki
Log aggregation system. Collects logs from all services.

**Access:** Grafana dashboard

---

## M

### Messenger Type
Enum identifying which messaging platform (Telegram, Max, Instagram, etc.).

**Values:** `TELEGRAM`, `MAX`, `INSTAGRAM`

**Purpose:** Support multi-messenger accounts for same user

### Migration
A versioned SQL script modifying database schema (Alembic).

**Naming:** `{timestamp}_{description}.py`

**Example:** `2024_01_15_1234_add_user_rating_column.py`

### Mini App
Telegram Mini App (web-based UI inside Telegram).

**Entry point:** `miniapp/app.py`
**Port:** 8000

---

## O

### Offer
A task from a brand asking a creator to make content.

**Attributes:** `title`, `description`, `budget`, `status`, `expires_at`

**Statuses:** ACTIVE → ACCEPTED → COMPLETED → PAID

### Outbox Pattern
A pattern guaranteeing "at least once" event delivery:
1. Write to DB + Outbox table atomically
2. Background worker publishes Outbox to Kafka
3. Consumer processes events

**Purpose:** Consistency without distributed transactions

---

## P

### Pagination
Dividing large result sets into pages for efficiency.

**Parameters:** `limit`, `offset` (or `page`, `page_size`)

### Port
An abstract interface defining a contract with external systems.

**Location:** `application/ports.py`

**Examples:** `UserRepository`, `MessengerClient`, `CachePort`

**Principle:** Services depend on ports, not adapters.

### PostgreSQL
Relational database. The system's primary data store.

**Version:** 16
**Extensions:** PostGIS (geographic queries)

### Prometheus
Metrics collection system. Scrapes `/metrics` endpoints periodically.

**Retention:** 15 days default
**Scrape interval:** 15 seconds

---

## R

### Rate Limiting
Restricting request frequency per user/IP to prevent abuse.

**Storage:** Redis keys like `rate_limit:{user_id}:{endpoint}`

### Referential Integrity
Database constraint ensuring foreign keys reference valid primary keys.

**Mechanism:** Foreign Key constraints

### Repository
An object abstracting data access. Implements a port.

**Naming:** `{Entity}Repository` interface, `{Entity}SQLRepository` implementation

**Purpose:** Isolate services from database logic

**Location:**
- Interface: `application/ports.py`
- Implementation: `infrastructure/db/repositories.py`

---

## S

### Service
A class orchestrating business logic using repositories and external clients.

**Location:** `application/services/`

**Principle:** Services call repos, handlers call services. Never call repos from handlers directly.

**Dependency Injection:** Constructor injection of repos and clients.

### Session (Database)
A connection to the database managing a transaction.

**Lifecycle:** Created → operations → commit/rollback → closed

**Pattern:** Context manager (`async with`) for safety.

### Singleton
An object instantiated once and reused everywhere.

**Example:** Kafka publisher, database session factory

---

## T

### Transaction
A group of database operations that succeed or fail together.

**Property:** ACID (Atomicity, Consistency, Isolation, Durability)

**Pattern:** Usually via context manager

---

## U

### UUID
Universally Unique Identifier. A 128-bit value identifying entities.

**Format:** `550e8400-e29b-41d4-a716-446655440000`

**Advantage:** Can be generated client-side without database

---

## V

### Value Object
An immutable object defined by its attributes, not identity.

**Example:** `Phone(number="+1234567890", country_code="US")`

**Example:** `Money(amount=Decimal("99.99"), currency="USD")`

---

## W

### Webhook
An HTTP endpoint receiving events from external systems.

**Examples:**
- `/webhook/telegram` — Telegram sends updates here
- `/webhook/instagram` — Instagram sends webhook events
- `/webhook/max` — Max sends events

**Pattern:** Receives → validates → publishes to Outbox/Kafka

---

## Z

### Zookeeper
Coordination service for Kafka. Manages broker leadership.

**Port:** 2181

**Note:** Can be replaced with Kraft (built-in consensus) in newer Kafka versions.

---

## Related Documents
- [[Architecture Overview]]
- [[Domain Model]]
- [[Patterns & Principles]]
