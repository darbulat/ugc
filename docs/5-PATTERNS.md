---
title: Design Patterns & Principles
tags: [patterns, architecture, design]
aliases: [Ports & Adapters Pattern, Repository Pattern, Outbox Pattern]
---

# Design Patterns & Principles

## 1. Ports & Adapters (Hexagonal Architecture)

**Goal:** Isolate business logic from frameworks and external systems.

### Structure
```
Business Logic (Services)
    ↓
Ports (Abstract Interfaces)
    ↓
Adapters (Concrete Implementations)
    ↓
External Systems (DB, APIs, Frameworks)
```

### Example: User Repository

**Port (Interface)** — `application/ports.py`:
```python
class UserRepository(Protocol):
    async def get_by_id(self, user_id: UUID) -> User | None: ...
    async def get_by_external_id(self, external_id: str, messenger_type: MessengerType) -> User | None: ...
    async def save(self, user: User, session: AsyncSession | None = None) -> User: ...
```

**Adapter (SQLAlchemy)** — `infrastructure/db/repositories.py`:
```python
class UserSQLRepository(UserRepository):
    def __init__(self, session_factory):
        self.session_factory = session_factory
    
    async def get_by_id(self, user_id: UUID) -> User | None:
        async with self.session_factory() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.id == user_id)
            )
            model = result.scalar_one_or_none()
            return model.to_entity() if model else None
```

**Usage in Service** — `application/services/user_service.py`:
```python
class UserService:
    def __init__(self, user_repo: UserRepository):
        self.user_repo = user_repo  # Depends on port, not adapter!
    
    async def get_user(self, user_id: UUID) -> User:
        return await self.user_repo.get_by_id(user_id)
```

### Benefits
- ✅ Services testable without database
- ✅ Easy to swap implementations (SQL → NoSQL)
- ✅ Clear contracts between layers
- ✅ No framework pollution in domain

---

## 2. Repository Pattern

**Goal:** Abstract data access logic away from services.

### Key Principle
Repositories represent aggregate roots (entities), not database tables.

### Session Management Pattern

Repositories use **context manager** for flexible session handling:

```python
class UserSQLRepository:
    async def save(self, user: User, session: AsyncSession | None = None) -> User:
        async with self._resolve_session(self.session_factory, session) as resolved_session:
            model = UserModel.from_entity(user)
            resolved_session.add(model)
            await resolved_session.flush()
            return model.to_entity()
    
    @staticmethod
    def _resolve_session(factory, provided_session):
        if provided_session:
            return provided_session  # Use provided session
        else:
            return factory()  # Create new session
```

### Usage
```python
# Standalone operation (creates own transaction)
user = await user_repo.save(user)

# Part of larger transaction (reuse session)
async with session_factory() as session:
    user = await user_repo.save(user, session=session)
    offer = await offer_repo.save(offer, session=session)
    # Both saved in one transaction
```

### Naming Conventions
- `get_by_X()` — Single entity or None
- `find_all_by_X()` — Multiple entities (with pagination)
- `exists(condition)` — Boolean check
- `count_by_X()` — Count matching records
- `save()` — Create or update
- `delete()` — Remove by ID

---

## 3. Outbox Pattern (Event Consistency)

**Goal:** Guarantee "at least once" event delivery without distributed transactions.

### Problem
If event publishing fails, DB commit succeeds → event lost

### Solution: Outbox Table
```
1. Write to application table + Outbox table in same transaction
2. Background worker reads Outbox periodically
3. Worker publishes to Kafka (idempotent)
4. Worker marks entry as published
```

### Implementation

**Step 1: Save entity + publish event atomically**
```python
class OfferService:
    async def accept_offer(self, offer_id: UUID, creator_id: UUID) -> Offer:
        async with self.session_factory() as session:
            # Update offer status
            offer = await self.offer_repo.update_status(
                offer_id, OfferStatus.ACCEPTED, session=session
            )
            
            # Create outbox entry in same transaction
            event = OutboxEntry(
                event_type="OfferAccepted",
                aggregate_id=offer.id,
                payload={"offer_id": str(offer.id), "creator_id": str(creator_id)},
                created_at=datetime.utcnow()
            )
            await self.outbox_repo.save(event, session=session)
            
            # Transaction commits atomically
            return offer
```

**Step 2: Background worker processes Outbox**
```python
# outbox_processor.py
async def process_outbox():
    while True:
        entries = await outbox_repo.find_unpublished(limit=100)
        
        for entry in entries:
            try:
                # Publish to Kafka
                await kafka_publisher.publish(
                    topic=f"{entry.event_type.lower()}-events",
                    message=entry.payload,
                    key=str(entry.aggregate_id)
                )
                # Mark as published
                await outbox_repo.mark_published(entry.id)
            except Exception:
                # Retry next iteration
                pass
        
        await asyncio.sleep(5)  # Check every 5 seconds
```

**Step 3: Kafka consumer processes events**
```python
# kafka_consumer.py
@router.message.handler()
async def handle_offer_accepted(message: dict):
    offer_id = UUID(message["offer_id"])
    creator_id = UUID(message["creator_id"])
    
    # Re-fetch offer and apply side effects
    offer = await offer_repo.get_by_id(offer_id)
    creator = await user_repo.get_by_id(creator_id)
    
    # Send notification to creator
    await messaging_service.send_to_user(
        creator,
        f"Your offer '{offer.title}' was accepted!"
    )
```

### Guarantees
- ✅ Event published ≥1 time (at least once)
- ✅ No distributed transactions
- ✅ Automatic retry on failure
- ✅ Consumer must be idempotent

---

## 4. Dependency Injection

**Goal:** Make dependencies explicit and testable.

### Constructor Injection (Preferred)
```python
class UserService:
    def __init__(
        self,
        user_repo: UserRepository,
        offer_repo: OfferRepository,
        cache: CachePort,
        event_bus: EventBusPort
    ):
        self.user_repo = user_repo
        self.offer_repo = offer_repo
        self.cache = cache
        self.event_bus = event_bus
```

### DI Container
```python
# container/__init__.py
class Container:
    def __init__(self, config: Config):
        self.config = config
        self._session_factory = create_async_sessionmaker(config.database_url)
    
    @property
    def user_repo(self) -> UserRepository:
        return UserSQLRepository(self._session_factory)
    
    @property
    def user_service(self) -> UserService:
        return UserService(
            user_repo=self.user_repo,
            offer_repo=self.offer_repo,
            cache=self.cache,
            event_bus=self.event_bus
        )
```

### Testing with Mocks
```python
@pytest.fixture
def user_service():
    user_repo = FakeUserRepository()  # In-memory
    offer_repo = FakeOfferRepository()
    cache = FakeCachePort()
    
    return UserService(
        user_repo=user_repo,
        offer_repo=offer_repo,
        cache=cache,
        event_bus=FakeEventBus()
    )

async def test_create_user(user_service):
    user = await user_service.create_user(
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        role=UserRole.CREATOR
    )
    assert user.role == UserRole.CREATOR
```

---

## 5. Value Objects

**Goal:** Encapsulate complex types with validation and behavior.

### Example: Phone Number
```python
@dataclass(frozen=True)
class Phone:
    number: str  # "+1234567890"
    country_code: str  # "US"
    
    @classmethod
    def parse(cls, raw: str) -> Phone:
        # Parse and validate E.164 format
        if not raw.startswith("+"):
            raise ValueError("Phone must start with +")
        # ... more validation
        
        # Extract country code
        cc = phonenumbers.parse(raw)
        return cls(
            number=phonenumbers.format_number(cc, PhoneNumberFormat.E164),
            country_code=phonenumbers.region_code_for_number(cc)
        )
    
    def __str__(self) -> str:
        return self.number
```

**Usage:**
```python
phone = Phone.parse("+1 (555) 123-4567")  # Normalized to "+15551234567"
user.phone = phone  # Stored in DB as string
```

---

## Related Documents
- [[Architecture Overview]]
- [[Domain Model]]
- [[Development Workflow]]
