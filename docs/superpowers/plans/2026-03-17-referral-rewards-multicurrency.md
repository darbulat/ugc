# Referral Rewards Multi-Currency Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement multi-currency referral rewards with denormalized income entries, per-currency payouts, and exchange rate service for approximate totals.

**Architecture:** New `referral_income_entries` table records commission at order close / interaction OK. Exchange rates cached in Redis (24h TTL) from open.er-api.com. Existing `ReferralIncomeService` refactored to read from new table. Per-currency payout buttons in bot.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, aiogram 3, Redis, aiohttp (for exchange API), pytest

**Spec:** `docs/superpowers/specs/2026-03-17-referral-rewards-multicurrency-design.md`

---

## Chunk 1: Domain & Data Layer

### Task 1: Add ReferralIncomeType enum and ReferralIncomeEntry entity

**Files:**
- Modify: `src/ugc_bot/domain/enums.py:100` (add enum before PayoutRequestStatus)
- Modify: `src/ugc_bot/domain/entities.py:407` (add entity after PayoutRequest)
- Test: `tests/unit/domain/test_entities.py` (if exists, or verify via import)

- [ ] **Step 1: Add ReferralIncomeType enum**

In `src/ugc_bot/domain/enums.py`, before `PayoutRequestStatus`:

```python
class ReferralIncomeType(StrEnum):
    """Type of referral income entry."""

    CREATOR = "creator"
    ADVERTISER = "advertiser"
```

- [ ] **Step 2: Add ReferralIncomeEntry entity**

In `src/ugc_bot/domain/entities.py`, after the `PayoutRequest` dataclass:

```python
@dataclass(frozen=True)
class ReferralIncomeEntry:
    """One referral income record for a completed order."""

    entry_id: UUID
    referrer_user_id: UUID
    referred_user_id: UUID
    order_id: UUID
    income_type: ReferralIncomeType
    currency: str
    platform_revenue: Decimal
    commission_rate: Decimal
    commission_amount: Decimal
    created_at: datetime
```

Add imports: `from ugc_bot.domain.enums import ReferralIncomeType` and `Decimal` (if not present).

- [ ] **Step 3: Add currency field to PayoutRequest entity**

In `src/ugc_bot/domain/entities.py`, add to `PayoutRequest` dataclass:

```python
currency: str = "RUB"
```

- [ ] **Step 4: Verify imports work**

Run: `python -c "from ugc_bot.domain.entities import ReferralIncomeEntry; from ugc_bot.domain.enums import ReferralIncomeType; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/domain/enums.py src/ugc_bot/domain/entities.py
git commit -m "feat: add ReferralIncomeEntry entity and ReferralIncomeType enum"
```

---

### Task 2: Add ReferralIncomeEntryModel and update PayoutRequestModel

**Files:**
- Modify: `src/ugc_bot/infrastructure/db/models.py` (add model near PayoutRequestModel ~line 795, add currency to PayoutRequestModel ~line 768)

- [ ] **Step 1: Add currency to PayoutRequestModel**

In `src/ugc_bot/infrastructure/db/models.py`, add to `PayoutRequestModel` class:

```python
currency: Mapped[str] = mapped_column(
    String(3), nullable=False, server_default=text("'RUB'")
)
```

- [ ] **Step 2: Add ReferralIncomeEntryModel**

After `PayoutRequestModel` in `models.py`:

```python
class ReferralIncomeEntryModel(Base):
    """Denormalized referral income record per order."""

    __tablename__ = "referral_income_entries"

    entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
        index=True,
    )
    referred_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id"),
        nullable=False,
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.order_id"),
        nullable=False,
    )
    income_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False
    )
    platform_revenue: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    commission_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    commission_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "order_id", "referrer_user_id", "income_type",
            name="uq_referral_income_order_referrer_type",
        ),
    )
```

Add necessary imports (`UniqueConstraint` from sqlalchemy if not present).

- [ ] **Step 3: Verify model imports**

Run: `python -c "from ugc_bot.infrastructure.db.models import ReferralIncomeEntryModel; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/infrastructure/db/models.py
git commit -m "feat: add ReferralIncomeEntryModel, add currency to PayoutRequestModel"
```

---

### Task 3: Alembic migration — schema changes

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0072_referral_income_entries.py`

- [ ] **Step 1: Create migration file**

```python
"""Add referral_income_entries table and currency to payout_requests."""

import sqlalchemy as sa
from alembic import op

revision = "0072_referral_income_entries"
down_revision = "0071_contact_pricing_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create referral_income_entries table, add currency to payout_requests."""
    op.create_table(
        "referral_income_entries",
        sa.Column("entry_id", sa.UUID(), nullable=False),
        sa.Column("referrer_user_id", sa.UUID(), nullable=False),
        sa.Column("referred_user_id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("income_type", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("platform_revenue", sa.Numeric(10, 2), nullable=False),
        sa.Column("commission_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("commission_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("entry_id"),
        sa.ForeignKeyConstraint(
            ["referrer_user_id"], ["users.user_id"],
            name="fk_referral_income_referrer",
        ),
        sa.ForeignKeyConstraint(
            ["referred_user_id"], ["users.user_id"],
            name="fk_referral_income_referred",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.order_id"],
            name="fk_referral_income_order",
        ),
        sa.UniqueConstraint(
            "order_id", "referrer_user_id", "income_type",
            name="uq_referral_income_order_referrer_type",
        ),
    )
    op.create_index(
        "ix_referral_income_entries_referrer",
        "referral_income_entries",
        ["referrer_user_id"],
    )

    op.add_column(
        "payout_requests",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
    )


def downgrade() -> None:
    """Revert changes."""
    op.drop_column("payout_requests", "currency")
    op.drop_table("referral_income_entries")
```

- [ ] **Step 2: Verify migration syntax**

Run: `cd /home/bulat/PycharmProjects/ugc && python -c "import importlib.util; spec = importlib.util.spec_from_file_location('m', 'src/ugc_bot/infrastructure/db/migrations/versions/0072_referral_income_entries.py'); mod = importlib.util.module_from_spec(spec); print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0072_referral_income_entries.py
git commit -m "feat: add migration 0072 — referral_income_entries table + payout currency"
```

---

### Task 4: Add ReferralIncomeEntryRepository port and implementations

**Files:**
- Modify: `src/ugc_bot/application/ports.py` (add ABC after PayoutRequestRepository)
- Modify: `src/ugc_bot/infrastructure/db/repositories.py` (add SQLAlchemy implementation)
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py` (add in-memory fake)
- Test: `tests/unit/test_memory_repositories.py` (or existing test file)

- [ ] **Step 1: Write failing test for InMemoryReferralIncomeEntryRepository**

Create or add to existing test file `tests/application/services/test_referral_income_entry_repo.py`:

```python
"""Tests for ReferralIncomeEntryRepository (in-memory)."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from ugc_bot.domain.entities import ReferralIncomeEntry
from ugc_bot.domain.enums import ReferralIncomeType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryReferralIncomeEntryRepository,
)


@pytest.mark.asyncio
async def test_save_and_get_totals_by_currency() -> None:
    repo = InMemoryReferralIncomeEntryRepository()
    referrer_id = uuid4()
    now = datetime.now(timezone.utc)

    entry_rub = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=uuid4(),
        order_id=uuid4(),
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("1000.00"),
        commission_rate=Decimal("0.1000"),
        commission_amount=Decimal("100.00"),
        created_at=now,
    )
    entry_gel = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=uuid4(),
        order_id=uuid4(),
        income_type=ReferralIncomeType.ADVERTISER,
        currency="GEL",
        platform_revenue=Decimal("50.00"),
        commission_rate=Decimal("0.1000"),
        commission_amount=Decimal("5.00"),
        created_at=now,
    )

    await repo.save(entry_rub)
    await repo.save(entry_gel)

    totals = await repo.get_totals_by_currency(referrer_id)
    assert totals == {"RUB": Decimal("100.00"), "GEL": Decimal("5.00")}


@pytest.mark.asyncio
async def test_save_idempotent_on_conflict() -> None:
    repo = InMemoryReferralIncomeEntryRepository()
    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)

    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=uuid4(),
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("1000.00"),
        commission_rate=Decimal("0.1000"),
        commission_amount=Decimal("100.00"),
        created_at=now,
    )
    await repo.save(entry)

    # Same order_id + referrer + type → should not duplicate
    entry2 = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=uuid4(),
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("2000.00"),
        commission_rate=Decimal("0.1000"),
        commission_amount=Decimal("200.00"),
        created_at=now,
    )
    await repo.save(entry2)

    totals = await repo.get_totals_by_currency(referrer_id)
    assert totals == {"RUB": Decimal("100.00")}  # Not 300


@pytest.mark.asyncio
async def test_get_orders_count_by_currency() -> None:
    repo = InMemoryReferralIncomeEntryRepository()
    referrer_id = uuid4()
    now = datetime.now(timezone.utc)

    for _ in range(3):
        await repo.save(
            ReferralIncomeEntry(
                entry_id=uuid4(),
                referrer_user_id=referrer_id,
                referred_user_id=uuid4(),
                order_id=uuid4(),
                income_type=ReferralIncomeType.CREATOR,
                currency="RUB",
                platform_revenue=Decimal("100.00"),
                commission_rate=Decimal("0.1000"),
                commission_amount=Decimal("10.00"),
                created_at=now,
            )
        )

    counts = await repo.get_orders_count_by_currency(referrer_id)
    assert counts == {"RUB": 3}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/application/services/test_referral_income_entry_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'InMemoryReferralIncomeEntryRepository'`

- [ ] **Step 3: Add ReferralIncomeEntryRepository port**

In `src/ugc_bot/application/ports.py`, after `PayoutRequestRepository`:

```python
class ReferralIncomeEntryRepository(ABC):
    """Repository for referral income entries."""

    @abstractmethod
    async def save(
        self, entry: "ReferralIncomeEntry", session: object | None = None
    ) -> None:
        """Save entry. Ignore if (order_id, referrer_user_id, income_type) exists."""

    @abstractmethod
    async def get_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: total_commission_amount} for referrer."""

    @abstractmethod
    async def get_orders_count_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, int]:
        """Return {currency: distinct_order_count} for referrer."""

    @abstractmethod
    async def get_current_month_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: total_commission_this_month} for referrer."""
```

Add `Decimal` import from `decimal` if not present.

Also update `PayoutRequestRepository` port — add method:

```python
    @abstractmethod
    async def get_paid_totals_by_currency(
        self, user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: sum_of_paid_amounts} for user."""

    @abstractmethod
    async def get_pending_totals_by_currency(
        self, user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        """Return {currency: sum_of_pending_amounts} for user."""

    @abstractmethod
    async def has_request_today_by_currency(
        self, user_id: UUID, session: object | None = None
    ) -> dict[str, bool]:
        """Return {currency: True} for currencies with a request today."""
```

Add implementations to both `InMemoryPayoutRequestRepository` and `SqlPayoutRequestRepository`.

- [ ] **Step 4: Add InMemoryReferralIncomeEntryRepository**

In `src/ugc_bot/infrastructure/memory_repositories.py`:

```python
@dataclass
class InMemoryReferralIncomeEntryRepository(ReferralIncomeEntryRepository):
    """In-memory implementation of ReferralIncomeEntryRepository."""

    entries: list[ReferralIncomeEntry] = field(default_factory=list)
    _seen: set[tuple[UUID, UUID, str]] = field(default_factory=set)

    async def save(
        self, entry: ReferralIncomeEntry, session: object | None = None
    ) -> None:
        key = (entry.order_id, entry.referrer_user_id, entry.income_type)
        if key in self._seen:
            return
        self._seen.add(key)
        self.entries.append(entry)

    async def get_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for e in self.entries:
            if e.referrer_user_id == referrer_user_id:
                totals[e.currency] = totals.get(e.currency, Decimal("0")) + e.commission_amount
        return totals

    async def get_orders_count_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, int]:
        seen_orders: dict[str, set[UUID]] = {}
        for e in self.entries:
            if e.referrer_user_id == referrer_user_id:
                seen_orders.setdefault(e.currency, set()).add(e.order_id)
        return {c: len(ids) for c, ids in seen_orders.items()}

    async def get_current_month_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        now = datetime.now(timezone.utc)
        totals: dict[str, Decimal] = {}
        for e in self.entries:
            if (
                e.referrer_user_id == referrer_user_id
                and e.created_at.year == now.year
                and e.created_at.month == now.month
            ):
                totals[e.currency] = totals.get(e.currency, Decimal("0")) + e.commission_amount
        return totals
```

Add imports: `ReferralIncomeEntryRepository` from ports, `ReferralIncomeEntry` from entities, `Decimal` from decimal.

- [ ] **Step 5: Add SQLAlchemy implementation**

In `src/ugc_bot/infrastructure/db/repositories.py`, add:

```python
class SqlReferralIncomeEntryRepository(ReferralIncomeEntryRepository):
    """SQLAlchemy implementation of ReferralIncomeEntryRepository."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def save(
        self, entry: ReferralIncomeEntry, session: object | None = None
    ) -> None:
        async with _resolve_session(self.session_factory, session) as s:
            stmt = pg_insert(ReferralIncomeEntryModel).values(
                entry_id=entry.entry_id,
                referrer_user_id=entry.referrer_user_id,
                referred_user_id=entry.referred_user_id,
                order_id=entry.order_id,
                income_type=entry.income_type,
                currency=entry.currency,
                platform_revenue=entry.platform_revenue,
                commission_rate=entry.commission_rate,
                commission_amount=entry.commission_amount,
                created_at=entry.created_at,
            ).on_conflict_do_nothing(
                constraint="uq_referral_income_order_referrer_type"
            )
            await s.execute(stmt)

    async def get_totals_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, Decimal]:
        async with _resolve_session(self.session_factory, session) as s:
            stmt = (
                select(
                    ReferralIncomeEntryModel.currency,
                    func.sum(ReferralIncomeEntryModel.commission_amount),
                )
                .where(
                    ReferralIncomeEntryModel.referrer_user_id == referrer_user_id
                )
                .group_by(ReferralIncomeEntryModel.currency)
            )
            rows = (await s.execute(stmt)).all()
            return {row[0]: row[1] for row in rows}

    async def get_orders_count_by_currency(
        self, referrer_user_id: UUID, session: object | None = None
    ) -> dict[str, int]:
        async with _resolve_session(self.session_factory, session) as s:
            stmt = (
                select(
                    ReferralIncomeEntryModel.currency,
                    func.count(
                        func.distinct(ReferralIncomeEntryModel.order_id)
                    ),
                )
                .where(
                    ReferralIncomeEntryModel.referrer_user_id == referrer_user_id
                )
                .group_by(ReferralIncomeEntryModel.currency)
            )
            rows = (await s.execute(stmt)).all()
            return {row[0]: row[1] for row in rows}
```

Add imports: `pg_insert` from `sqlalchemy.dialects.postgresql`, `ReferralIncomeEntryModel` from models, `ReferralIncomeEntryRepository` from ports.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/application/services/test_referral_income_entry_repo.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/memory_repositories.py src/ugc_bot/infrastructure/db/repositories.py tests/application/services/test_referral_income_entry_repo.py
git commit -m "feat: add ReferralIncomeEntryRepository port with SQL and in-memory implementations"
```

---

## Chunk 2: Exchange Rate Service

### Task 5: Add ExchangeRateProvider port and ExchangeRateCache port

**Files:**
- Modify: `src/ugc_bot/application/ports.py` (add two ABCs)

- [ ] **Step 1: Add ports**

In `src/ugc_bot/application/ports.py`:

```python
class ExchangeRateProvider(ABC):
    """External API for fetching exchange rates."""

    @abstractmethod
    async def fetch_rates(self, base_currency: str) -> dict[str, Decimal]:
        """Fetch current rates relative to base_currency. E.g. {"USD": 0.011, "GEL": 0.03}."""


class ExchangeRateCache(ABC):
    """Cache for exchange rates with TTL."""

    @abstractmethod
    async def get_rates(self, base_currency: str) -> dict[str, Decimal] | None:
        """Return cached rates or None if expired/missing."""

    @abstractmethod
    async def set_rates(self, base_currency: str, rates: dict[str, Decimal]) -> None:
        """Store rates with TTL."""
```

- [ ] **Step 2: Commit**

```bash
git add src/ugc_bot/application/ports.py
git commit -m "feat: add ExchangeRateProvider and ExchangeRateCache ports"
```

---

### Task 6: Implement ExchangeRateService

**Files:**
- Create: `src/ugc_bot/application/services/exchange_rate_service.py`
- Test: `tests/application/services/test_exchange_rate_service.py`

- [ ] **Step 1: Write failing tests**

```python
"""Tests for ExchangeRateService."""

import pytest
from decimal import Decimal
from unittest.mock import AsyncMock

from ugc_bot.application.services.exchange_rate_service import ExchangeRateService


@pytest.fixture
def mock_provider() -> AsyncMock:
    provider = AsyncMock()
    provider.fetch_rates.return_value = {
        "USD": Decimal("1.0"),
        "RUB": Decimal("90.0"),
        "GEL": Decimal("2.7"),
    }
    return provider


@pytest.fixture
def mock_cache() -> AsyncMock:
    cache = AsyncMock()
    cache.get_rates.return_value = None  # empty cache
    return cache


@pytest.fixture
def service(mock_provider, mock_cache) -> ExchangeRateService:
    return ExchangeRateService(provider=mock_provider, cache=mock_cache)


@pytest.mark.asyncio
async def test_convert_fetches_and_caches(service, mock_provider, mock_cache):
    result = await service.convert(Decimal("100"), "GEL", "RUB")
    # 100 GEL * (90/2.7) = 3333.33 RUB
    assert result is not None
    assert abs(result - Decimal("3333.33")) < Decimal("0.01")
    mock_cache.set_rates.assert_called_once()


@pytest.mark.asyncio
async def test_convert_uses_cache(service, mock_cache):
    mock_cache.get_rates.return_value = {
        "USD": Decimal("1.0"),
        "RUB": Decimal("90.0"),
        "GEL": Decimal("2.7"),
    }
    result = await service.convert(Decimal("100"), "GEL", "RUB")
    assert result is not None
    service.provider.fetch_rates.assert_not_called()


@pytest.mark.asyncio
async def test_convert_same_currency(service):
    result = await service.convert(Decimal("100"), "RUB", "RUB")
    assert result == Decimal("100")


@pytest.mark.asyncio
async def test_convert_many(service):
    amounts = {"RUB": Decimal("1000"), "GEL": Decimal("100")}
    result = await service.convert_many(amounts, "RUB")
    # 1000 RUB + 100 GEL * (90/2.7) = 1000 + 3333.33 = 4333.33
    assert result is not None
    assert abs(result - Decimal("4333.33")) < Decimal("0.01")


@pytest.mark.asyncio
async def test_convert_returns_none_when_api_fails(mock_cache):
    provider = AsyncMock()
    provider.fetch_rates.side_effect = Exception("API down")
    service = ExchangeRateService(provider=provider, cache=mock_cache)
    result = await service.convert(Decimal("100"), "GEL", "RUB")
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/application/services/test_exchange_rate_service.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement ExchangeRateService**

Create `src/ugc_bot/application/services/exchange_rate_service.py`:

```python
"""Service for currency conversion with lazy-cached exchange rates."""

import logging
from decimal import Decimal, ROUND_HALF_UP

from ugc_bot.application.ports import ExchangeRateCache, ExchangeRateProvider

logger = logging.getLogger(__name__)

# Use USD as intermediate base for all conversions
_BASE = "USD"


class ExchangeRateService:
    """Convert amounts between currencies using cached exchange rates."""

    def __init__(
        self,
        provider: ExchangeRateProvider,
        cache: ExchangeRateCache,
    ) -> None:
        self.provider = provider
        self.cache = cache

    async def _get_rates(self) -> dict[str, Decimal] | None:
        """Get rates (from cache or API). Returns {currency: rate_vs_USD}."""
        rates = await self.cache.get_rates(_BASE)
        if rates is not None:
            return rates
        try:
            rates = await self.provider.fetch_rates(_BASE)
        except Exception:
            logger.warning("Exchange rate API unavailable", exc_info=True)
            return None
        await self.cache.set_rates(_BASE, rates)
        return rates

    async def get_rate(
        self, from_currency: str, to_currency: str
    ) -> Decimal | None:
        """Return conversion rate from_currency -> to_currency."""
        if from_currency == to_currency:
            return Decimal("1")
        rates = await self._get_rates()
        if rates is None:
            return None
        from_rate = rates.get(from_currency)
        to_rate = rates.get(to_currency)
        if from_rate is None or to_rate is None or from_rate == 0:
            return None
        return (to_rate / from_rate).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

    async def convert(
        self, amount: Decimal, from_currency: str, to_currency: str
    ) -> Decimal | None:
        """Convert amount from one currency to another."""
        rate = await self.get_rate(from_currency, to_currency)
        if rate is None:
            return None
        return (amount * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    async def convert_many(
        self, amounts: dict[str, Decimal], to_currency: str
    ) -> Decimal | None:
        """Convert multiple currency amounts to one currency and sum."""
        total = Decimal("0")
        for currency, amount in amounts.items():
            converted = await self.convert(amount, currency, to_currency)
            if converted is None:
                return None
            total += converted
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/services/test_exchange_rate_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/exchange_rate_service.py tests/application/services/test_exchange_rate_service.py
git commit -m "feat: add ExchangeRateService with lazy-cached currency conversion"
```

---

### Task 7: Implement OpenERApiProvider and RedisExchangeRateCache

**Files:**
- Create: `src/ugc_bot/infrastructure/exchange_rate.py`
- Test: `tests/unit/infrastructure/test_exchange_rate.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for exchange rate infrastructure."""

import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from ugc_bot.infrastructure.exchange_rate import (
    OpenERApiProvider,
    RedisExchangeRateCache,
)


@pytest.mark.asyncio
async def test_open_er_api_provider_parses_response():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={
        "result": "success",
        "rates": {"RUB": 90.5, "GEL": 2.7, "USD": 1.0},
    })
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    provider = OpenERApiProvider(session=mock_session)
    rates = await provider.fetch_rates("USD")

    assert rates["RUB"] == Decimal("90.5")
    assert rates["GEL"] == Decimal("2.7")


@pytest.mark.asyncio
async def test_redis_cache_get_returns_none_when_empty():
    redis = AsyncMock()
    redis.get.return_value = None
    cache = RedisExchangeRateCache(redis=redis, ttl_seconds=86400)
    result = await cache.get_rates("USD")
    assert result is None


@pytest.mark.asyncio
async def test_redis_cache_roundtrip():
    storage = {}

    async def mock_set(key, value, ex=None):
        storage[key] = value

    async def mock_get(key):
        return storage.get(key)

    redis = AsyncMock()
    redis.set = mock_set
    redis.get = mock_get

    cache = RedisExchangeRateCache(redis=redis, ttl_seconds=86400)
    rates = {"RUB": Decimal("90.5"), "GEL": Decimal("2.7")}
    await cache.set_rates("USD", rates)

    result = await cache.get_rates("USD")
    assert result == rates
```

- [ ] **Step 2: Run tests — expect failure**

Run: `uv run pytest tests/unit/infrastructure/test_exchange_rate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

Create `src/ugc_bot/infrastructure/exchange_rate.py`:

```python
"""Exchange rate infrastructure: API provider and Redis cache."""

import json
import logging
from decimal import Decimal

from ugc_bot.application.ports import ExchangeRateCache, ExchangeRateProvider

logger = logging.getLogger(__name__)

_API_URL = "https://open.er-api.com/v6/latest/{base}"


class OpenERApiProvider(ExchangeRateProvider):
    """Fetch rates from open.er-api.com (free, no API key)."""

    def __init__(self, session) -> None:
        self._session = session

    async def fetch_rates(self, base_currency: str) -> dict[str, Decimal]:
        url = _API_URL.format(base=base_currency)
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if data.get("result") != "success":
            raise RuntimeError(f"Exchange rate API error: {data}")
        return {
            code: Decimal(str(rate))
            for code, rate in data["rates"].items()
        }


class RedisExchangeRateCache(ExchangeRateCache):
    """Redis-backed cache for exchange rates."""

    def __init__(self, redis, ttl_seconds: int = 86400) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get_rates(
        self, base_currency: str
    ) -> dict[str, Decimal] | None:
        raw = await self._redis.get(f"exchange_rates:{base_currency}")
        if raw is None:
            return None
        data = json.loads(raw)
        return {code: Decimal(val) for code, val in data.items()}

    async def set_rates(
        self, base_currency: str, rates: dict[str, Decimal]
    ) -> None:
        data = {code: str(val) for code, val in rates.items()}
        await self._redis.set(
            f"exchange_rates:{base_currency}",
            json.dumps(data),
            ex=self._ttl,
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `uv run pytest tests/unit/infrastructure/test_exchange_rate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/infrastructure/exchange_rate.py tests/unit/infrastructure/test_exchange_rate.py
git commit -m "feat: add OpenERApiProvider and RedisExchangeRateCache"
```

---

## Chunk 3: Recording Referral Income

### Task 8: Add record_referral_income methods to ReferralIncomeService

**Files:**
- Modify: `src/ugc_bot/application/services/referral_income_service.py`
- Test: `tests/application/services/test_referral_income_service.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/application/services/test_referral_income_service.py`:

```python
@pytest.mark.asyncio
async def test_record_creator_referral_income_creates_entry() -> None:
    """When interaction is OK, creator referral income is recorded."""
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)

    # Setup: referrer -> creator binding
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer_id,
            referred_user_id=creator_id,
            created_at=now - timedelta(days=30),
        )
    )

    # User (creator) registered 30 days ago → first year rate (10%)
    user_repo = InMemoryUserRepository()
    creator = User(
        user_id=creator_id,
        external_id="123",
        messenger=MessengerType.TELEGRAM,
        created_at=now - timedelta(days=30),
        country_code="ru",
    )
    await user_repo.save(creator)

    # Order with 2 bloggers, country_code from advertiser
    order = Order(
        order_id=order_id,
        user_id=uuid4(),  # advertiser
        status=OrderStatus.CLOSED,
        bloggers_needed=2,
        completed_at=now,
        # ... other required fields
    )

    # ContactPricing: ru, 2 bloggers → 500 RUB
    pricing_repo = InMemoryContactPricingRepository()
    await pricing_repo.save(
        ContactPricing(
            country_code="ru",
            bloggers_count=2,
            price=Decimal("500.00"),
            currency="RUB",
            updated_at=now,
        )
    )

    income_entry_repo = InMemoryReferralIncomeEntryRepository()

    service = ReferralIncomeService(
        # ... existing deps
        referral_income_entry_repo=income_entry_repo,
        contact_pricing_repo=pricing_repo,
    )

    await service.record_creator_referral_income(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
    )

    totals = await income_entry_repo.get_totals_by_currency(referrer_id)
    # platform_revenue = 500 / 2 = 250, commission = 250 * 0.10 = 25.00
    assert totals == {"RUB": Decimal("25.00")}
```

**IMPORTANT for agentic worker:** This test is a sketch. Before implementing:
1. Read `tests/application/services/test_referral_income_service.py` for existing fixture patterns
2. Read `src/ugc_bot/domain/entities.py` for exact `Order` and `User` dataclass field signatures
3. Fill in all required constructor fields to match the project's dataclasses
4. Wire all `ReferralIncomeService` constructor dependencies (see existing tests for the full list, plus new `referral_income_entry_repo` and `contact_pricing_repo`)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/services/test_referral_income_service.py::test_record_creator_referral_income_creates_entry -v`
Expected: FAIL

- [ ] **Step 3: Add record methods to ReferralIncomeService**

Add to `src/ugc_bot/application/services/referral_income_service.py`:

```python
async def record_creator_referral_income(
    self,
    order: Order,
    creator_id: UUID,
    advertiser_country_code: str,
    session: object | None = None,
) -> None:
    """Record referral income for a creator whose interaction is OK."""
    binding = await self.user_referral_binding_repo.get_by_referred_user(
        creator_id, session=session
    )
    if binding is None:
        return

    pricing = await self.contact_pricing_repo.get_by_bloggers_count(
        order.bloggers_needed,
        country_code=advertiser_country_code,
        session=session,
    )
    if pricing is None:
        logger.warning(
            "No ContactPricing for country=%s bloggers=%d, skipping referral income",
            advertiser_country_code,
            order.bloggers_needed,
        )
        return

    creator = await self.user_repo.get_by_id(creator_id, session=session)
    if creator is None:
        return

    platform_revenue = pricing.price / order.bloggers_needed
    rate = self._resolve_rate(creator, order)
    commission = (platform_revenue * rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=binding.referrer_user_id,
        referred_user_id=creator_id,
        order_id=order.order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency=pricing.currency,
        platform_revenue=platform_revenue,
        commission_rate=rate,
        commission_amount=commission,
        created_at=datetime.now(timezone.utc),
    )
    await self.referral_income_entry_repo.save(entry, session=session)


async def record_advertiser_referral_income(
    self,
    order: Order,
    advertiser_id: UUID,
    advertiser_country_code: str,
    session: object | None = None,
) -> None:
    """Record referral income for an advertiser when order closes."""
    binding = await self.user_referral_binding_repo.get_by_referred_user(
        advertiser_id, session=session
    )
    if binding is None:
        return

    pricing = await self.contact_pricing_repo.get_by_bloggers_count(
        order.bloggers_needed,
        country_code=advertiser_country_code,
        session=session,
    )
    if pricing is None:
        logger.warning(
            "No ContactPricing for country=%s bloggers=%d, skipping referral income",
            advertiser_country_code,
            order.bloggers_needed,
        )
        return

    advertiser = await self.user_repo.get_by_id(
        advertiser_id, session=session
    )
    if advertiser is None:
        return

    platform_revenue = pricing.price
    rate = self._resolve_rate(advertiser, order)
    commission = (platform_revenue * rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=binding.referrer_user_id,
        referred_user_id=advertiser_id,
        order_id=order.order_id,
        income_type=ReferralIncomeType.ADVERTISER,
        currency=pricing.currency,
        platform_revenue=platform_revenue,
        commission_rate=rate,
        commission_amount=commission,
        created_at=datetime.now(timezone.utc),
    )
    await self.referral_income_entry_repo.save(entry, session=session)


def _resolve_rate(self, referred_user: User, order: Order) -> Decimal:
    """Get commission rate: custom rate or default by year."""
    if referred_user.referral_payout_rate is not None:
        return referred_user.referral_payout_rate
    years = _years_since(referred_user.created_at, order.completed_at or datetime.now(timezone.utc))
    return Decimal(str(FIRST_YEAR_RATE if years < 1.0 else AFTER_FIRST_YEAR_RATE))
```

Add new constructor params: `referral_income_entry_repo: ReferralIncomeEntryRepository` and `contact_pricing_repo: ContactPricingRepository`.

Add imports: `ReferralIncomeEntry`, `ReferralIncomeType`, `Decimal`, `ROUND_HALF_UP`, `uuid4`, `ContactPricingRepository`, `ReferralIncomeEntryRepository`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/application/services/test_referral_income_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/referral_income_service.py tests/application/services/test_referral_income_service.py
git commit -m "feat: add record_creator/advertiser_referral_income methods"
```

---

### Task 9: Wire triggers — order close and interaction OK

**Files:**
- Modify: `src/ugc_bot/application/services/offer_response_service.py:170` (advertiser trigger on CLOSED)
- Modify: `src/ugc_bot/application/services/interaction_service.py:199,256` (creator trigger on OK)
- Modify: `src/ugc_bot/container/service_factory.py` (inject new deps)

- [ ] **Step 1: Add advertiser referral income trigger on order CLOSED**

In `offer_response_service.py`, after `await self.order_repo.save(updated, session=session)` (line 170), add:

```python
if updated.status == OrderStatus.CLOSED and self.referral_income_service:
    advertiser = await self.user_repo.get_by_id(
        order.user_id, session=session
    )
    if advertiser and advertiser.country_code:
        await self.referral_income_service.record_advertiser_referral_income(
            order=updated,
            advertiser_id=order.user_id,
            advertiser_country_code=advertiser.country_code,
            session=session,
        )
```

Add `referral_income_service` as optional constructor param (default `None`).

- [ ] **Step 2: Add creator referral income trigger on interaction OK**

In `interaction_service.py`, in both `record_advertiser_feedback()` (after line 199) and `record_blogger_feedback()` (after line 256), add:

```python
if updated.status == InteractionStatus.OK and self.referral_income_service:
    order = await self.order_repo.get_by_id(updated.order_id)
    if order and order.status == OrderStatus.CLOSED:
        advertiser = await self.user_repo.get_by_id(order.user_id)
        if advertiser and advertiser.country_code:
            await self.referral_income_service.record_creator_referral_income(
                order=order,
                creator_id=updated.blogger_id,
                advertiser_country_code=advertiser.country_code,
            )
```

Add `referral_income_service`, `order_repo`, `user_repo` as optional constructor params.

- [ ] **Step 3: Update container/service_factory.py (partial — service constructor changes only)**

Update `ReferralIncomeService` constructor call in `build_bot_services()` to pass new `referral_income_entry_repo` and `contact_pricing_repo`. Add `referral_income_service` as optional param to `OfferResponseService` and `InteractionService` constructors. Full wiring of `ExchangeRateService` and new infra components is done in Task 13.

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -x -v --timeout=5`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/offer_response_service.py src/ugc_bot/application/services/interaction_service.py src/ugc_bot/container/service_factory.py
git commit -m "feat: wire referral income recording on order CLOSED and interaction OK"
```

---

## Chunk 4: Updated Stats Display and Per-Currency Payouts

### Task 10: Update ReferralIncomeService.get_stats() to use entries table

**Files:**
- Modify: `src/ugc_bot/application/services/referral_income_service.py`
- Test: `tests/application/services/test_referral_income_service.py`

- [ ] **Step 1: Write test for multi-currency stats**

```python
@pytest.mark.asyncio
async def test_get_multicurrency_stats() -> None:
    """Stats should return per-currency breakdown."""
    referrer_id = uuid4()
    now = datetime.now(timezone.utc)

    income_repo = InMemoryReferralIncomeEntryRepository()
    # Add 2 RUB entries and 1 GEL entry
    await income_repo.save(ReferralIncomeEntry(
        entry_id=uuid4(), referrer_user_id=referrer_id,
        referred_user_id=uuid4(), order_id=uuid4(),
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB", platform_revenue=Decimal("500"),
        commission_rate=Decimal("0.1"), commission_amount=Decimal("50"),
        created_at=now,
    ))
    await income_repo.save(ReferralIncomeEntry(
        entry_id=uuid4(), referrer_user_id=referrer_id,
        referred_user_id=uuid4(), order_id=uuid4(),
        income_type=ReferralIncomeType.ADVERTISER,
        currency="GEL", platform_revenue=Decimal("100"),
        commission_rate=Decimal("0.1"), commission_amount=Decimal("10"),
        created_at=now,
    ))

    payout_repo = InMemoryPayoutRequestRepository()

    # IMPORTANT: Read existing test file for full constructor signature.
    # Wire all deps from existing tests, plus new referral_income_entry_repo.
    service = ReferralIncomeService(
        referral_income_entry_repo=income_repo,
        payout_request_repo=payout_repo,
        # ... fill in remaining deps from existing test fixtures
    )

    stats = await service.get_multicurrency_stats(referrer_id)
    assert stats.income_by_currency == {"RUB": Decimal("50"), "GEL": Decimal("10")}
    assert stats.orders_by_currency == {"RUB": 1, "GEL": 1}
    assert stats.paid_by_currency == {}
    assert stats.available_by_currency == {"RUB": Decimal("50"), "GEL": Decimal("10")}
```

- [ ] **Step 2: Run test — expect fail**

Run: `uv run pytest tests/application/services/test_referral_income_service.py::test_get_multicurrency_stats -v`

- [ ] **Step 3: Add MultiCurrencyReferralStats dataclass and get_multicurrency_stats()**

In `referral_income_service.py`:

```python
@dataclass(slots=True)
class MultiCurrencyReferralStats:
    """Referral stats broken down by currency."""
    creators_count: int
    income_by_currency: dict[str, Decimal]      # {currency: total_income}
    orders_by_currency: dict[str, int]           # {currency: order_count}
    paid_by_currency: dict[str, Decimal]         # {currency: paid_amount}
    pending_by_currency: dict[str, Decimal]      # {currency: pending_amount}
    available_by_currency: dict[str, Decimal]    # {currency: income - paid - pending}
    has_request_today_by_currency: dict[str, bool]
```

Implement `get_multicurrency_stats()` that reads from `referral_income_entry_repo` and aggregates payouts by currency.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/application/services/test_referral_income_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/referral_income_service.py tests/application/services/test_referral_income_service.py
git commit -m "feat: add get_multicurrency_stats() reading from income entries table"
```

---

### Task 11: Update bot handler for multi-currency display

**Files:**
- Modify: `src/ugc_bot/bot/handlers/referral.py`
- Modify: `src/ugc_bot/bot/texts/defaults.py` (add new text keys)

- [ ] **Step 1: Add new text keys to defaults.py**

Add to each locale in `DEFAULT_TEXTS`:

```python
# ru:
"lbl_referral_income_line": "• {amount} {symbol} ({count} заказов)",
"lbl_referral_approx_total": "≈ {amount} {symbol} (примерный итог)",
"lbl_referral_paid_currency": "Выплачено: {amount} {symbol}",
"lbl_referral_pending_currency": "В ожидании: {amount} {symbol}",
"btn_referral_payout_currency": "Выплатить {amount} {symbol}",
"msg_referral_payout_today_currency": "Вы уже подавали заявку на вывод {currency} сегодня.",

# en:
"lbl_referral_income_line": "• {amount} {symbol} ({count} orders)",
"lbl_referral_approx_total": "≈ {amount} {symbol} (approximate total)",
"lbl_referral_paid_currency": "Paid: {amount} {symbol}",
"lbl_referral_pending_currency": "Pending: {amount} {symbol}",
"btn_referral_payout_currency": "Withdraw {amount} {symbol}",
"msg_referral_payout_today_currency": "You already requested {currency} payout today.",
```

Add equivalent keys for kk, be, uz locales. Read the existing referral text keys in `defaults.py` for each locale to follow the translation style. Copy the patterns from nearby keys (e.g., `lbl_referral_income_month`) and adapt for the new keys.

- [ ] **Step 2: Update `/referral` handler to show multi-currency stats**

In `referral.py`, modify the referral stats handler to:
1. Call `service.get_multicurrency_stats()` instead of `get_user_referral_stats()`
2. Build multi-line income breakdown from `income_by_currency`
3. Get currency symbols from `CountryRepository` (map currency_code → symbol via `list_enabled()`)
4. Call `exchange_rate_service.convert_many()` for approximate total in referrer's currency
5. Build per-currency payout buttons (only for currencies with `available > 0` and no pending request)
6. Hide payout button for a currency if `pending_by_currency[currency] > 0`

**Referrer's currency resolution:** Get referrer's `country_code` from `user.country_code`, then `CountryRepository.get_by_code(country_code)` → `country.currency_code`. If no country set, default to `"RUB"`.

**Handler injection:** `exchange_rate_service` is injected from dispatcher data dict (aiogram DI), same pattern as other services. Task 13 registers it in the services dict.

- [ ] **Step 3: Update payout callback to include currency**

Change callback data from `referral:payout` to `referral:payout:{currency}`. Parse currency from callback, create `PayoutRequest` with `currency` field.

Update admin notification text to include currency: "Запрос на выплату {amount} {symbol} от @{username}". Add text key `msg_referral_payout_notify` to all locales with `{amount}`, `{symbol}`, `{username}` placeholders.

- [ ] **Step 4: Update payout rate limit check to be per-currency**

Check `has_request_today_by_currency.get(currency, False)` instead of global `has_request_today`. This uses the new `PayoutRequestRepository.has_request_today_by_currency()` method added in Task 4.

- [ ] **Step 5: Run make fix**

Run: `make fix`
Expected: All checks pass

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/bot/handlers/referral.py src/ugc_bot/bot/texts/defaults.py
git commit -m "feat: multi-currency referral stats display and per-currency payout buttons"
```

---

### Task 12: Update admin panel

**Files:**
- Modify: `src/ugc_bot/admin/app.py`

- [ ] **Step 1: Add currency to PayoutRequestAdmin**

In `PayoutRequestAdmin`, add `PayoutRequestModel.currency` to `column_list` and `column_labels`:

```python
column_list = [
    PayoutRequestModel.request_id,
    PayoutRequestModel.user_id,
    PayoutRequestModel.requested_at,
    PayoutRequestModel.status,
    PayoutRequestModel.amount,
    PayoutRequestModel.currency,  # NEW
]
column_labels = {
    ...
    PayoutRequestModel.currency: "Валюта",
}
```

- [ ] **Step 2: Add ReferralIncomeEntryAdmin**

```python
class ReferralIncomeEntryAdmin(ModelView, model=ReferralIncomeEntryModel):
    """Read-only admin view for referral income entries."""

    name = "Реферальное начисление"
    name_plural = "Реферальные начисления"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        ReferralIncomeEntryModel.entry_id,
        ReferralIncomeEntryModel.referrer_user_id,
        ReferralIncomeEntryModel.referred_user_id,
        ReferralIncomeEntryModel.order_id,
        ReferralIncomeEntryModel.income_type,
        ReferralIncomeEntryModel.currency,
        ReferralIncomeEntryModel.platform_revenue,
        ReferralIncomeEntryModel.commission_rate,
        ReferralIncomeEntryModel.commission_amount,
        ReferralIncomeEntryModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (ReferralIncomeEntryModel.created_at, True)
    column_labels = {
        ReferralIncomeEntryModel.entry_id: "ID",
        ReferralIncomeEntryModel.referrer_user_id: "Реферальщик",
        ReferralIncomeEntryModel.referred_user_id: "Реферал",
        ReferralIncomeEntryModel.order_id: "Заказ",
        ReferralIncomeEntryModel.income_type: "Тип",
        ReferralIncomeEntryModel.currency: "Валюта",
        ReferralIncomeEntryModel.platform_revenue: "Доход платформы",
        ReferralIncomeEntryModel.commission_rate: "Ставка",
        ReferralIncomeEntryModel.commission_amount: "Комиссия",
        ReferralIncomeEntryModel.created_at: "Дата",
    }
```

Register in `_add_admin_views()`:

```python
admin.add_view(ReferralIncomeEntryAdmin)
```

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/admin/app.py
git commit -m "feat: add ReferralIncomeEntryAdmin and currency column to PayoutRequestAdmin"
```

---

## Chunk 5: DI Wiring, Data Migration, and Final Verification

### Task 13: Wire everything in container

**Files:**
- Modify: `src/ugc_bot/container/service_factory.py`

- [ ] **Step 1: Add new repos and services to container**

1. Add `SqlReferralIncomeEntryRepository` to repos dict
2. Add `OpenERApiProvider` and `RedisExchangeRateCache` construction
3. Add `ExchangeRateService` construction
4. Pass new deps to `ReferralIncomeService`, `OfferResponseService`, `InteractionService`
5. Expose `exchange_rate_service` in bot services dict

- [ ] **Step 2: Run make fix**

Run: `make fix`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/container/service_factory.py
git commit -m "feat: wire ReferralIncomeEntryRepository, ExchangeRateService into DI container"
```

---

### Task 14: Data migration for historical orders

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0073_backfill_referral_income.py`

- [ ] **Step 1: Create data migration**

This migration iterates CLOSED orders with referral bindings and inserts entries. Uses raw SQL for performance:

```python
"""Backfill referral_income_entries from historical closed orders."""

from alembic import op
import sqlalchemy as sa

revision = "0073_backfill_referral_income"
down_revision = "0072_referral_income_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Backfill income entries for existing closed orders."""
    conn = op.get_bind()

    # Advertiser referrals: one entry per closed order where advertiser has a referrer
    conn.execute(sa.text("""
        INSERT INTO referral_income_entries
            (entry_id, referrer_user_id, referred_user_id, order_id,
             income_type, currency, platform_revenue, commission_rate,
             commission_amount, created_at)
        SELECT
            gen_random_uuid(),
            urb.referrer_user_id,
            o.user_id,
            o.order_id,
            'advertiser',
            cp.currency,
            cp.price,
            CASE
                WHEN u.referral_payout_rate IS NOT NULL THEN u.referral_payout_rate
                WHEN EXTRACT(EPOCH FROM (o.completed_at - u.created_at)) / 86400.0 / 365.25 < 1.0 THEN 0.10
                ELSE 0.03
            END,
            ROUND(cp.price * CASE
                WHEN u.referral_payout_rate IS NOT NULL THEN u.referral_payout_rate
                WHEN EXTRACT(EPOCH FROM (o.completed_at - u.created_at)) / 86400.0 / 365.25 < 1.0 THEN 0.10
                ELSE 0.03
            END, 2),
            COALESCE(o.completed_at, o.updated_at)
        FROM orders o
        JOIN users u ON u.user_id = o.user_id
        JOIN user_referral_bindings urb ON urb.referred_user_id = o.user_id
        JOIN contact_pricing cp ON cp.country_code = COALESCE(u.country_code, 'ru')
            AND cp.bloggers_count = o.bloggers_needed
        WHERE o.status = 'closed'
        ON CONFLICT (order_id, referrer_user_id, income_type) DO NOTHING
    """))

    # Creator referrals: one entry per creator with OK interaction on closed order
    conn.execute(sa.text("""
        INSERT INTO referral_income_entries
            (entry_id, referrer_user_id, referred_user_id, order_id,
             income_type, currency, platform_revenue, commission_rate,
             commission_amount, created_at)
        SELECT
            gen_random_uuid(),
            urb.referrer_user_id,
            i.blogger_id,
            o.order_id,
            'creator',
            cp.currency,
            ROUND(cp.price / o.bloggers_needed, 2),
            CASE
                WHEN creator.referral_payout_rate IS NOT NULL THEN creator.referral_payout_rate
                WHEN EXTRACT(EPOCH FROM (o.completed_at - creator.created_at)) / 86400.0 / 365.25 < 1.0 THEN 0.10
                ELSE 0.03
            END,
            ROUND(
                ROUND(cp.price / o.bloggers_needed, 2) * CASE
                    WHEN creator.referral_payout_rate IS NOT NULL THEN creator.referral_payout_rate
                    WHEN EXTRACT(EPOCH FROM (o.completed_at - creator.created_at)) / 86400.0 / 365.25 < 1.0 THEN 0.10
                    ELSE 0.03
                END,
            2),
            COALESCE(o.completed_at, o.updated_at)
        FROM interactions i
        JOIN orders o ON o.order_id = i.order_id
        JOIN users advertiser ON advertiser.user_id = o.user_id
        JOIN users creator ON creator.user_id = i.blogger_id
        JOIN user_referral_bindings urb ON urb.referred_user_id = i.blogger_id
        JOIN contact_pricing cp ON cp.country_code = COALESCE(advertiser.country_code, 'ru')
            AND cp.bloggers_count = o.bloggers_needed
        WHERE o.status = 'closed'
          AND i.status = 'ok'
          AND o.bloggers_needed > 0
        ON CONFLICT (order_id, referrer_user_id, income_type) DO NOTHING
    """))


def downgrade() -> None:
    """Remove backfilled entries."""
    op.execute("DELETE FROM referral_income_entries")
```

- [ ] **Step 2: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0073_backfill_referral_income.py
git commit -m "feat: add migration 0073 — backfill referral_income_entries from historical data"
```

---

### Task 15: Final verification

- [ ] **Step 1: Run make fix**

Run: `make fix`
Expected: All format, lint, typecheck, coverage checks pass

- [ ] **Step 2: Run full test suite**

Run: `make test`
Expected: All tests pass

- [ ] **Step 3: Run make all (CI replica)**

Run: `make all`
Expected: PASS — matches what GitHub Actions will run

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address lint/type issues from final verification"
```
