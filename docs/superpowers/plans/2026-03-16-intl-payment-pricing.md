# International Payment Pricing Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Charge international advertisers using a country-specific formula: `(contact_pricing + order.price * bloggers_needed) * (1 + tax_rate)`, with per-country pricing and provider tokens.

**Architecture:** Add `tax_rate` to Country, make ContactPricing country-specific with composite PK, centralize all invoice calculation in `PaymentService.calculate_invoice_data()`, and use a pure `calculate_invoice_total()` function as single source of truth for both invoice-sending and payment validation.

**Tech Stack:** Python 3.13, SQLAlchemy + Alembic, aiogram, pydantic-settings, PostgreSQL

**Spec:** `docs/superpowers/specs/2026-03-16-intl-payment-pricing-design.md`

---

## Chunk 1: Data Model & Repository Layer

### Task 1: Add `locale` and `tax_rate` to Country entity + ORM model

Migration 0063 already added `locale` column to DB, but entity and ORM model are out of sync. Fix that and add `tax_rate`.

**Files:**
- Modify: `src/ugc_bot/domain/entities.py:35-42`
- Modify: `src/ugc_bot/infrastructure/db/models.py:388-399`
- Modify: `src/ugc_bot/infrastructure/db/repositories.py:2945-2953` (`_to_country_entity`)
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0070_country_tax_rate.py`

- [ ] **Step 1: Update Country entity**

In `src/ugc_bot/domain/entities.py`, add `locale` and `tax_rate` fields to `Country`:

```python
@dataclass(frozen=True)
class Country:
    """Country entity for multi-country support."""

    code: str
    name_native: str
    currency_code: str
    currency_symbol: str
    locale: str = "ru"
    tax_rate: Decimal = field(default_factory=lambda: Decimal("0"))
    enabled: bool = True
```

Add `from decimal import Decimal` to imports at top of file (line 1-5 area).

- [ ] **Step 2: Update CountryModel ORM**

In `src/ugc_bot/infrastructure/db/models.py`, add columns to `CountryModel` (after `currency_symbol`, before `enabled`):

```python
locale: Mapped[str] = mapped_column(
    String(8), nullable=False, server_default=text("'ru'")
)
tax_rate: Mapped[Decimal] = mapped_column(
    Numeric(5, 4), nullable=False, server_default=text("0")
)
```

Add `from decimal import Decimal` to imports.

- [ ] **Step 3: Update `_to_country_entity` mapping**

In `src/ugc_bot/infrastructure/db/repositories.py:2945-2953`, add `locale` and `tax_rate`:

```python
def _to_country_entity(model: CountryModel) -> Country:
    """Map country ORM model to domain entity."""
    return Country(
        code=model.code,
        name_native=model.name_native,
        currency_code=model.currency_code,
        currency_symbol=model.currency_symbol,
        locale=model.locale,
        tax_rate=model.tax_rate,
        enabled=model.enabled,
    )
```

- [ ] **Step 4: Create migration 0070 for `tax_rate`**

```bash
uv run alembic revision -m "add tax_rate to countries" --rev-id 0070_country_tax_rate
```

Edit the migration file:

```python
"""Add tax_rate column to countries table."""

import sqlalchemy as sa
from alembic import op

revision = "0070_country_tax_rate"
down_revision = "0069_add_index_offer_dispatches_manager_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "countries",
        sa.Column(
            "tax_rate",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("countries", "tax_rate")
```

- [ ] **Step 5: Update InMemoryCountryRepository and any test fakes**

Search for all `Country(` constructors in test code and `memory_repositories.py`. Add `locale=` and `tax_rate=` where missing. Most can use defaults.

```bash
grep -rn "Country(" src/ugc_bot/infrastructure/memory_repositories.py tests/ --include="*.py"
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_container.py tests/application/test_geography.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/domain/entities.py src/ugc_bot/infrastructure/db/models.py src/ugc_bot/infrastructure/db/repositories.py src/ugc_bot/infrastructure/db/migrations/versions/0070_country_tax_rate.py src/ugc_bot/infrastructure/memory_repositories.py tests/
git commit -m "feat: add locale and tax_rate to Country entity/model"
```

---

### Task 2: Make ContactPricing country-specific

**Files:**
- Modify: `src/ugc_bot/domain/entities.py:326-337`
- Modify: `src/ugc_bot/infrastructure/db/models.py:414-427`
- Modify: `src/ugc_bot/infrastructure/db/repositories.py:876-895` (SQLAlchemy repo)
- Modify: `src/ugc_bot/infrastructure/db/repositories.py:1802-1810` (`_to_contact_pricing_entity`)
- Modify: `src/ugc_bot/application/ports.py:647-655` (abstract repo)
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py:948-984`
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0071_contact_pricing_country.py`
- Test: `tests/application/services/test_contact_pricing_service.py`

- [ ] **Step 1: Update ContactPricing entity**

In `src/ugc_bot/domain/entities.py:326-337`:

```python
@dataclass(frozen=True)
class ContactPricing:
    """Contact pricing entity.

    When adding a new field: find usages with grep -r "ContactPricing(" src/;
    for updates use dataclasses.replace(pricing, ...). Update repo mapping.
    """

    country_code: str
    bloggers_count: int
    price: Decimal
    currency: str
    updated_at: datetime
    created_at: Optional[datetime] = None
```

Add `Decimal` to imports if not already present.

- [ ] **Step 2: Update ContactPricingModel ORM**

In `src/ugc_bot/infrastructure/db/models.py:414-427`:

```python
class ContactPricingModel(Base):
    """Contact pricing ORM model."""

    __tablename__ = "contact_pricing"

    country_code: Mapped[str] = mapped_column(
        String(2), primary_key=True, server_default=text("'ru'")
    )
    bloggers_count: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'RUB'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
```

- [ ] **Step 3: Update `ContactPricingRepository` port**

In `src/ugc_bot/application/ports.py:647-655`, add `country_code` parameter:

```python
class ContactPricingRepository(ABC):
    """Port for contact pricing persistence."""

    @abstractmethod
    async def get_by_bloggers_count(
        self,
        bloggers_count: int,
        country_code: str = "ru",
        session: object | None = None,
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count and country."""
```

- [ ] **Step 4: Update `_to_contact_pricing_entity` mapping**

In `src/ugc_bot/infrastructure/db/repositories.py:1802-1810`:

```python
def _to_contact_pricing_entity(model: ContactPricingModel) -> ContactPricing:
    """Map contact pricing ORM model to entity."""
    return ContactPricing(
        country_code=model.country_code,
        bloggers_count=model.bloggers_count,
        price=model.price,
        currency=model.currency,
        created_at=getattr(model, "created_at", model.updated_at),
        updated_at=model.updated_at,
    )
```

- [ ] **Step 5: Update SQLAlchemy repo implementation**

In `src/ugc_bot/infrastructure/db/repositories.py:876-895`, add `country_code` filter:

```python
async def get_by_bloggers_count(
    self,
    bloggers_count: int,
    country_code: str = "ru",
    session: object | None = None,
) -> Optional[ContactPricing]:
    """Fetch pricing by bloggers count and country."""
    async with _resolve_session(
        self.session_factory, session
    ) as db_session:
        exec_result = await db_session.execute(
            select(ContactPricingModel).where(
                ContactPricingModel.country_code == country_code,
                ContactPricingModel.bloggers_count == bloggers_count,
            )
        )
        result = exec_result.scalar_one_or_none()
        return _to_contact_pricing_entity(result) if result else None
```

- [ ] **Step 6: Update InMemoryContactPricingRepository**

In `src/ugc_bot/infrastructure/memory_repositories.py:948-984`, change key to `(country_code, bloggers_count)`:

```python
@dataclass
class InMemoryContactPricingRepository(ContactPricingRepository):
    """In-memory contact pricing repository."""

    prices: Dict[tuple[str, int], ContactPricing] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """Initialize with default prices."""
        if not self.prices:
            now = datetime.now(timezone.utc)
            for count in (3, 10, 20, 30, 50):
                self.prices[("ru", count)] = ContactPricing(
                    country_code="ru",
                    bloggers_count=count,
                    price=Decimal("0"),
                    currency="RUB",
                    updated_at=now,
                )

    async def get_by_bloggers_count(
        self,
        bloggers_count: int,
        country_code: str = "ru",
        session: object | None = None,
    ) -> Optional[ContactPricing]:
        """Fetch pricing by bloggers count and country."""
        return self.prices.get((country_code, bloggers_count))

    async def save(self, pricing: ContactPricing) -> None:
        """Persist pricing in memory."""
        self.prices[(pricing.country_code, pricing.bloggers_count)] = pricing
```

Add `from decimal import Decimal` to imports.

- [ ] **Step 7: Update all `ContactPricing(` constructors in tests**

Search and fix all files that construct `ContactPricing` directly. Files to update:

1. `tests/application/services/test_contact_pricing_service.py` (lines ~21, ~37)
2. `tests/application/services/test_payment_service.py` (line ~270)
3. `tests/helpers/services.py` (line ~156)
4. `tests/helpers/factories.py` (line ~300)
5. `tests/bot/handlers/test_payments.py` (line ~570)

For each `ContactPricing(...)` call, add `country_code="ru"`, change `price=` to `Decimal(...)`, add `currency="RUB"`. Example:

```python
# Before:
ContactPricing(bloggers_count=3, price=300.0, updated_at=now)
# After:
ContactPricing(country_code="ru", bloggers_count=3, price=Decimal("300"), currency="RUB", updated_at=now)
```

Add `from decimal import Decimal` to each file's imports where missing.

- [ ] **Step 8: Update ContactPricingService (keep `float` return for now)**

In `src/ugc_bot/application/services/contact_pricing_service.py`, add `country_code` parameter but **keep returning `float | None`** to avoid breaking handlers (they'll be refactored in Task 6):

```python
"""Service for contact pricing."""

from dataclasses import dataclass

from ugc_bot.application.ports import (
    ContactPricingRepository,
    TransactionManager,
)
from ugc_bot.infrastructure.db.session import with_optional_tx


@dataclass(slots=True)
class ContactPricingService:
    """Service for contact pricing lookup."""

    pricing_repo: ContactPricingRepository
    transaction_manager: TransactionManager | None = None

    async def get_price(
        self, bloggers_count: int, country_code: str = "ru"
    ) -> float | None:
        """Get price for bloggers count and country.

        Returns float for backward compat with handlers.
        PaymentService uses pricing_repo directly for full entity.
        """

        async def _run(session: object | None):
            pricing = await self.pricing_repo.get_by_bloggers_count(
                bloggers_count, country_code=country_code, session=session
            )
            return float(pricing.price) if pricing else None

        return await with_optional_tx(self.transaction_manager, _run)
```

**Note:** Return type stays `float | None` until Task 6 removes `contact_pricing_service` from handlers. `PaymentService.calculate_invoice_data` uses `pricing_repo` directly and gets the full `ContactPricing` entity.

- [ ] **Step 9: Create migration 0071**

```python
"""Add country_code and currency to contact_pricing, make composite PK."""

import sqlalchemy as sa
from alembic import op

revision = "0071_contact_pricing_country"
down_revision = "0070_country_tax_rate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contact_pricing",
        sa.Column(
            "country_code",
            sa.String(2),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )
    op.add_column(
        "contact_pricing",
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default=sa.text("'RUB'"),
        ),
    )
    op.drop_constraint(
        "contact_pricing_pkey", "contact_pricing", type_="primary"
    )
    op.create_primary_key(
        "contact_pricing_pkey",
        "contact_pricing",
        ["country_code", "bloggers_count"],
    )
    op.create_foreign_key(
        "fk_contact_pricing_country",
        "contact_pricing",
        "countries",
        ["country_code"],
        ["code"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_contact_pricing_country", "contact_pricing", type_="foreignkey"
    )
    op.drop_constraint(
        "contact_pricing_pkey", "contact_pricing", type_="primary"
    )
    op.create_primary_key(
        "contact_pricing_pkey", "contact_pricing", ["bloggers_count"]
    )
    op.drop_column("contact_pricing", "currency")
    op.drop_column("contact_pricing", "country_code")
```

- [ ] **Step 10: Run full test suite**

```bash
make fix
```

Expected: all tests pass, 98%+ coverage.

- [ ] **Step 11: Commit**

```bash
git add -u && git add src/ugc_bot/infrastructure/db/migrations/versions/0071_contact_pricing_country.py
git commit -m "feat: make ContactPricing country-specific with composite PK"
```

---

## Chunk 2: Service Layer — Invoice Calculation

### Task 3: Add `calculate_invoice_total` pure function + tests

**Files:**
- Modify: `src/ugc_bot/application/services/payment_service.py`
- Create: `tests/application/services/test_invoice_calculation.py`

- [ ] **Step 1: Write failing tests**

Create `tests/application/services/test_invoice_calculation.py`:

```python
"""Tests for calculate_invoice_total."""

from decimal import Decimal

import pytest

from ugc_bot.application.services.payment_service import (
    calculate_invoice_total,
)


class TestCalculateInvoiceTotal:
    def test_ru_returns_contact_pricing_only(self):
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("1000"),
            bloggers_needed=5,
            tax_rate=Decimal("0"),
            is_ru=True,
        )
        assert result == Decimal("300")

    def test_intl_basic_formula(self):
        # (300 + 1000 * 3) * (1 + 0.12) = 3300 * 1.12 = 3696
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("1000"),
            bloggers_needed=3,
            tax_rate=Decimal("0.12"),
            is_ru=False,
        )
        assert result == Decimal("3696.00")

    def test_intl_zero_tax(self):
        # (300 + 1000 * 3) * (1 + 0) = 3300
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("1000"),
            bloggers_needed=3,
            tax_rate=Decimal("0"),
            is_ru=False,
        )
        assert result == Decimal("3300.00")

    def test_intl_zero_order_price(self):
        # (300 + 0 * 3) * (1 + 0.1) = 300 * 1.1 = 330
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("0"),
            bloggers_needed=3,
            tax_rate=Decimal("0.1"),
            is_ru=False,
        )
        assert result == Decimal("330.00")

    def test_intl_rounding(self):
        # (100 + 33.33 * 3) * (1 + 0.07) = 199.99 * 1.07 = 213.9893
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("100"),
            order_price=Decimal("33.33"),
            bloggers_needed=3,
            tax_rate=Decimal("0.07"),
            is_ru=False,
        )
        assert result == Decimal("213.99")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/application/services/test_invoice_calculation.py -v
```

Expected: `ImportError: cannot import name 'calculate_invoice_total'`

- [ ] **Step 3: Implement `calculate_invoice_total`**

Add to `src/ugc_bot/application/services/payment_service.py` (before the `PaymentService` class):

```python
from decimal import ROUND_HALF_UP, Decimal

def calculate_invoice_total(
    contact_pricing_price: Decimal,
    order_price: Decimal,
    bloggers_needed: int,
    tax_rate: Decimal,
    is_ru: bool,
) -> Decimal:
    """Calculate invoice total. Single source of truth for pricing.

    RU: total = contact_pricing_price
    International: total = (contact_pricing + order_price * bloggers_needed) * (1 + tax_rate)
    """
    if is_ru:
        return contact_pricing_price
    base = contact_pricing_price + order_price * bloggers_needed
    return (base * (1 + tax_rate)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/application/services/test_invoice_calculation.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/payment_service.py tests/application/services/test_invoice_calculation.py
git commit -m "feat: add calculate_invoice_total pure function with tests"
```

---

### Task 4: Add `InvoiceData` DTO and `PaymentService.calculate_invoice_data`

**Files:**
- Modify: `src/ugc_bot/application/services/payment_service.py` (add InvoiceData, calculate_invoice_data, move build_receipt_provider_data here)
- Modify: `src/ugc_bot/bot/handlers/payments.py` (re-import build_receipt_provider_data from service)
- Modify: `src/ugc_bot/container/service_factory.py:374-382`
- Modify: `tests/helpers/services.py:106-134`
- Modify: `tests/helpers/repositories.py` (add `country_repo` fixture)
- Create: `tests/application/services/test_calculate_invoice_data.py`

- [ ] **Step 0: Add `country_repo` fixture**

In `tests/helpers/repositories.py`, add import and fixture at the end:

```python
from ugc_bot.infrastructure.memory_repositories import InMemoryCountryRepository

@pytest.fixture
def country_repo() -> InMemoryCountryRepository:
    """Fixture for country repository."""
    return InMemoryCountryRepository()
```

Then in `tests/conftest.py`, add `country_repo` to the import block (line ~31-43):

```python
from tests.helpers.repositories import (  # noqa: E402, F401
    advertiser_repo,
    blogger_repo,
    complaint_repo,
    country_repo,  # <-- add this
    ...
)
```

This makes `country_repo` available to all tests.

- [ ] **Step 1: Write failing tests**

Create `tests/application/services/test_calculate_invoice_data.py`:

```python
"""Tests for PaymentService.calculate_invoice_data."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ugc_bot.application.services.payment_service import InvoiceData
from ugc_bot.domain.entities import ContactPricing, Country
from ugc_bot.domain.enums import OrderStatus
from tests.helpers.factories import create_test_order, create_test_user
from tests.helpers.services import build_payment_service

NOW = datetime.now(timezone.utc)


@pytest.fixture
def patched_config(monkeypatch):
    """Config with provider tokens set."""
    monkeypatch.setenv("TELEGRAM_PROVIDER_TOKEN", "ru_provider")
    monkeypatch.setenv("TELEGRAM_PROVIDER_TOKEN_INTL", "intl_provider")
    from ugc_bot.config import load_config
    return load_config()


@pytest.mark.asyncio
async def test_calculate_invoice_data_ru(
    user_repo, advertiser_repo, order_repo, payment_repo,
    pricing_repo, country_repo, fake_tm, patched_config,
):
    """RU user gets contact_pricing only, with YooKassa receipt."""
    pricing_repo.prices[("ru", 3)] = ContactPricing(
        country_code="ru", bloggers_count=3,
        price=Decimal("300"), currency="RUB",
        updated_at=NOW,
    )
    user = await create_test_user(
        user_repo, external_id="1", country="ru",
    )
    order = await create_test_order(
        order_repo, user.user_id, price=1000.0,
        bloggers_needed=3, status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo, advertiser_repo, order_repo,
        payment_repo, pricing_repo, fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order, "ru", patched_config,
    )
    assert result is not None
    assert result.total == Decimal("300")
    assert result.currency == "RUB"
    assert result.provider_token == "ru_provider"
    assert result.provider_data is not None  # 54-FZ receipt
    assert result.is_ru is True
    assert result.need_email is True


@pytest.mark.asyncio
async def test_calculate_invoice_data_intl(
    user_repo, advertiser_repo, order_repo, payment_repo,
    pricing_repo, country_repo, fake_tm, patched_config,
):
    """International user gets full formula with tax."""
    country_repo.countries["ge"] = Country(
        code="ge", name_native="საქართველო",
        currency_code="GEL", currency_symbol="₾",
        locale="en", tax_rate=Decimal("0.18"),
    )
    pricing_repo.prices[("ge", 3)] = ContactPricing(
        country_code="ge", bloggers_count=3,
        price=Decimal("200"), currency="GEL",
        updated_at=NOW,
    )
    user = await create_test_user(
        user_repo, external_id="2", country="ge",
    )
    order = await create_test_order(
        order_repo, user.user_id, price=500.0,
        bloggers_needed=3, status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo, advertiser_repo, order_repo,
        payment_repo, pricing_repo, fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order, "ge", patched_config,
    )
    assert result is not None
    # (200 + 500 * 3) * (1 + 0.18) = 1700 * 1.18 = 2006.00
    assert result.total == Decimal("2006.00")
    assert result.currency == "GEL"
    assert result.currency_symbol == "₾"
    assert result.provider_token == "intl_provider"
    assert result.provider_data is None
    assert result.is_ru is False
    assert result.need_email is False


@pytest.mark.asyncio
async def test_calculate_invoice_data_no_pricing(
    user_repo, advertiser_repo, order_repo, payment_repo,
    pricing_repo, country_repo, fake_tm, patched_config,
):
    """Returns None when pricing not configured for country."""
    user = await create_test_user(user_repo, external_id="3", country="ge")
    order = await create_test_order(
        order_repo, user.user_id, price=500.0,
        bloggers_needed=3, status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo, advertiser_repo, order_repo,
        payment_repo, pricing_repo, fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order, "ge", patched_config,
    )
    assert result is None


@pytest.mark.asyncio
async def test_calculate_invoice_data_none_country_defaults_to_ru(
    user_repo, advertiser_repo, order_repo, payment_repo,
    pricing_repo, country_repo, fake_tm, patched_config,
):
    """user_country=None is treated as RU."""
    pricing_repo.prices[("ru", 3)] = ContactPricing(
        country_code="ru", bloggers_count=3,
        price=Decimal("300"), currency="RUB",
        updated_at=NOW,
    )
    user = await create_test_user(user_repo, external_id="4")
    order = await create_test_order(
        order_repo, user.user_id, price=1000.0,
        bloggers_needed=3, status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo, advertiser_repo, order_repo,
        payment_repo, pricing_repo, fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order, None, patched_config,
    )
    assert result is not None
    assert result.total == Decimal("300")
    assert result.is_ru is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/application/services/test_calculate_invoice_data.py -v
```

Expected: `ImportError: cannot import name 'InvoiceData'`

- [ ] **Step 3: Add `InvoiceData` to `payment_service.py`**

```python
@dataclass(frozen=True)
class InvoiceData:
    """All data needed to send a Telegram invoice."""

    total: Decimal
    currency: str
    currency_symbol: str
    provider_token: str
    provider_data: str | None
    need_email: bool
    is_ru: bool
```

- [ ] **Step 4: Add `country_repo` to `PaymentService`**

In `src/ugc_bot/application/services/payment_service.py`, add to `PaymentService` fields:

```python
from ugc_bot.application.ports import (
    ...,
    CountryRepository,
)

@dataclass(slots=True)
class PaymentService:
    ...
    country_repo: CountryRepository | None = None
    ...
```

- [ ] **Step 5a: Move `build_receipt_provider_data` to service layer**

Move the function from `src/ugc_bot/bot/handlers/payments.py` (line ~57) to `src/ugc_bot/application/services/payment_service.py`. This avoids a circular import (service layer must not import from handler layer).

In `payments.py`, replace the function body with a re-import for backward compatibility:

```python
from ugc_bot.application.services.payment_service import build_receipt_provider_data  # moved
```

The function itself (paste into `payment_service.py` before `PaymentService` class). **Copy the exact existing implementation** from `payments.py` (lines 57-83) — do not change parameter names, vat_code, or receipt fields:

```python
import json

DEFAULT_RECEIPT_SERVICE_DESCRIPTION = "Услуги платформы Use My Content"


def build_receipt_provider_data(
    total_amount: float,
    currency: str,
    receipt_description: str,
) -> str:
    """Build provider_data JSON for YooKassa receipt (54-FZ)."""
    amount_str = f"{total_amount:.2f}"
    receipt = {
        "receipt": {
            "items": [
                {
                    "description": receipt_description
                    or DEFAULT_RECEIPT_SERVICE_DESCRIPTION,
                    "quantity": 1,
                    "amount": {"value": amount_str, "currency": currency},
                    "vat_code": 2,
                    "payment_mode": "full_prepayment",
                    "payment_subject": "service",
                }
            ],
            "internet": "true",
        }
    }
    return json.dumps(receipt, ensure_ascii=False)
```

- [ ] **Step 5b: Implement `calculate_invoice_data`**

Add method to `PaymentService`:

```python
async def calculate_invoice_data(
    self,
    order: Order,
    user_country: str | None,
    config: "AppConfig",
) -> InvoiceData | None:
    """Build invoice data for an order. Returns None if pricing missing."""

    country_code = (user_country or "ru").lower()
    is_ru = country_code == "ru"

    async def _run(session: object | None):
        pricing = await self.pricing_repo.get_by_bloggers_count(
            order.bloggers_needed,
            country_code=country_code,
            session=session,
        )
        if pricing is None:
            return None

        tax_rate = Decimal("0")
        currency_symbol = config.market.currency_symbol
        if not is_ru and self.country_repo is not None:
            country = await self.country_repo.get_by_code(
                user_country, session=session
            )
            if country:
                tax_rate = country.tax_rate
                currency_symbol = country.currency_symbol

        total = calculate_invoice_total(
            contact_pricing_price=pricing.price,
            order_price=Decimal(str(order.price)),
            bloggers_needed=order.bloggers_needed,
            tax_rate=tax_rate,
            is_ru=is_ru,
        )

        if is_ru:
            provider_token = config.bot.telegram_provider_token
        else:
            provider_token = config.bot.telegram_provider_token_intl

        receipt_desc = (
            config.market.receipt_service_description
            or "Услуги платформы Use My Content"
        )
        provider_data = (
            build_receipt_provider_data(
                float(total), pricing.currency, receipt_desc
            )
            if is_ru
            else None
        )

        return InvoiceData(
            total=total,
            currency=pricing.currency,
            currency_symbol=currency_symbol,
            provider_token=provider_token,
            provider_data=provider_data,
            need_email=is_ru,
            is_ru=is_ru,
        )

    return await with_optional_tx(self.transaction_manager, _run)
```

- [ ] **Step 6: Update `build_payment_service` in test helpers**

In `tests/helpers/services.py:106-134`, add `country_repo` parameter:

```python
def build_payment_service(
    user_repo, advertiser_repo, order_repo, payment_repo,
    pricing_repo, transaction_manager, country_repo=None,
) -> PaymentService:
    ...
    return PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        pricing_repo=pricing_repo,
        country_repo=country_repo,
        transaction_manager=transaction_manager,
    )
```

- [ ] **Step 7: Update DI container**

In `src/ugc_bot/container/service_factory.py`, add `country_repo` to `PaymentService` construction:

```python
"payment_service": PaymentService(
    user_repo=repos["user_repo"],
    advertiser_repo=repos["advertiser_repo"],
    order_repo=repos["order_repo"],
    payment_repo=repos["payment_repo"],
    pricing_repo=repos["pricing_repo"],
    country_repo=repos.get("country_repo"),
    metrics_collector=metrics_collector,
    transaction_manager=transaction_manager,
),
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/application/services/test_calculate_invoice_data.py tests/application/services/test_invoice_calculation.py tests/application/services/test_payment_service.py -v
```

- [ ] **Step 9: Commit**

```bash
git add -u && git add tests/application/services/test_calculate_invoice_data.py
git commit -m "feat: add InvoiceData DTO and calculate_invoice_data method"
```

---

### Task 5: Update `confirm_telegram_payment` validation

**Files:**
- Modify: `src/ugc_bot/application/services/payment_service.py:107-118`
- Modify: `tests/application/services/test_payment_service.py`
- [ ] **Step 1: Write failing test for international validation**

Add to `tests/application/services/test_payment_service.py`:

```python
@pytest.mark.asyncio
async def test_confirm_payment_intl_formula(
    user_repo, advertiser_repo, order_repo, payment_repo,
    pricing_repo, country_repo, fake_tm,
):
    """International payment validates against full formula."""
    from decimal import Decimal

    country_repo.countries["ge"] = Country(
        code="ge", name_native="Georgia",
        currency_code="GEL", currency_symbol="₾",
        tax_rate=Decimal("0.18"),
    )
    pricing_repo.prices[("ge", 3)] = ContactPricing(
        country_code="ge", bloggers_count=3,
        price=Decimal("200"), currency="GEL",
        updated_at=datetime.now(timezone.utc),
    )
    user = await create_test_user(
        user_repo, external_id="1", country="ge",
    )
    await create_test_advertiser_profile(advertiser_repo, user.user_id)
    order = await create_test_order(
        order_repo, user.user_id, price=500.0,
        bloggers_needed=3, status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo, advertiser_repo, order_repo,
        payment_repo, pricing_repo, fake_tm,
        country_repo=country_repo,
    )
    # (200 + 500 * 3) * (1 + 0.18) = 2006.00 → 200600 minor
    payment = await service.confirm_telegram_payment(
        user_id=user.user_id,
        order_id=order.order_id,
        provider_payment_charge_id="ext_123",
        total_amount=200600,
        currency="GEL",
    )
    assert payment.amount == 2006.00
    assert payment.currency == "GEL"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/application/services/test_payment_service.py::test_confirm_payment_intl_formula -v
```

- [ ] **Step 3: Update validation in `_confirm_telegram_payment_impl`**

In `src/ugc_bot/application/services/payment_service.py:107-118`, replace:

```python
pricing = await self.pricing_repo.get_by_bloggers_count(
    order.bloggers_needed, session=session
)
if pricing is None:
    raise OrderCreationError(
        "Contact pricing not configured for this bloggers count."
    )
expected_amount_minor = round(pricing.price * 100)
if total_amount != expected_amount_minor:
    raise OrderCreationError(
        "Payment amount does not match order price."
    )
```

With:

```python
country_code = (user.country or "ru").lower()
is_ru = country_code == "ru"
pricing = await self.pricing_repo.get_by_bloggers_count(
    order.bloggers_needed,
    country_code=country_code,
    session=session,
)
if pricing is None:
    raise OrderCreationError(
        "Contact pricing not configured for this bloggers count."
    )
tax_rate = Decimal("0")
if not is_ru and self.country_repo is not None:
    country_obj = await self.country_repo.get_by_code(
        user.country, session=session
    )
    if country_obj:
        tax_rate = country_obj.tax_rate
expected = calculate_invoice_total(
    pricing.price,
    Decimal(str(order.price)),
    order.bloggers_needed,
    tax_rate,
    is_ru,
)
expected_amount_minor = int(expected * 100)
if total_amount != expected_amount_minor:
    raise OrderCreationError(
        "Payment amount does not match order price."
    )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/application/services/test_payment_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add -u
git commit -m "feat: update payment validation for international formula"
```

---

## Chunk 3: Handler Layer & Admin

### Task 6: Refactor `payments.py` handlers to use `InvoiceData`

**Files:**
- Modify: `src/ugc_bot/bot/handlers/payments.py`
- Modify: `tests/bot/handlers/test_payments.py`

- [ ] **Step 1: Update `send_order_invoice` to accept `InvoiceData`**

Replace the function signature and body. Remove `_get_provider_token` helper (logic moved to `PaymentService`). Remove `order_currency`, `user_country` parameters. The function now receives pre-calculated `InvoiceData`:

```python
async def send_order_invoice(
    incoming_message,
    messenger_client: MessengerClient,
    order_id: UUID,
    offer_text: str,
    invoice_data: InvoiceData,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
) -> None:
    """Send invoice using pre-calculated InvoiceData."""
    locale = user_locale

    if not incoming_message.chat_id:
        return

    price = int(invoice_data.total * 100)
    if price > 100_000_000:
        msg_too_large = await bot_texts_service.get(
            "msg_order_amount_too_large", locale
        )
        await messenger_client.send_text(
            chat_id=incoming_message.chat_id, text=msg_too_large,
        )
        return

    try:
        label_text = await bot_texts_service.get("msg_pay_label", locale)
        label = label_text.format(
            amount=int(invoice_data.total),
            symbol=invoice_data.currency_symbol,
        ) if label_text and "{amount}" in label_text else (
            f"💳 {int(invoice_data.total)} {invoice_data.currency_symbol}"
        )
        await messenger_client.send_invoice(
            chat_id=incoming_message.chat_id,
            invoice=Invoice(
                title=await bot_texts_service.get("msg_title_payment", locale),
                description=offer_text[:255],
                payload=str(order_id),
                provider_token=invoice_data.provider_token,
                currency=invoice_data.currency,
                items=[InvoiceItem(label=label, amount_minor=price)],
                provider_data=invoice_data.provider_data,
                need_email=invoice_data.need_email,
                send_email_to_provider=invoice_data.need_email,
            ),
        )
    except Exception:
        logger.exception(
            "Failed to send invoice",
            extra={"order_id": str(order_id), "price_minor": price},
        )
        msg_failed = await bot_texts_service.get("msg_invoice_failed", locale)
        await messenger_client.send_text(
            chat_id=incoming_message.chat_id, text=msg_failed,
        )
```

- [ ] **Step 2: Update three handlers**

In each of `start_pay_order_link`, `pay_order`, `pay_order_callback`:

1. Remove `contact_pricing_service` from parameters
2. Replace the block:
```python
contact_price = await contact_pricing_service.get_price(order.bloggers_needed)
if contact_price is None: ...
if not _get_provider_token(user.country, config): ...
receipt_desc = ...
await send_order_invoice(price_value=contact_price, ...)
```
With:
```python
invoice_data = await payment_service.calculate_invoice_data(
    order, user.country, config,
)
if invoice_data is None:
    msg_pricing = await bot_texts_service.get(
        "msg_pricing_not_configured", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=msg_pricing,
    )
    return
if not invoice_data.provider_token:
    msg_provider = await bot_texts_service.get(
        "msg_payment_provider_not_configured", locale
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id, text=msg_provider,
    )
    return
await send_order_invoice(
    incoming_message=incoming,
    messenger_client=messenger_client,
    order_id=order.order_id,
    offer_text=order.offer_text,
    invoice_data=invoice_data,
    bot_texts_service=bot_texts_service,
    user_locale=user_locale,
)
```

- [ ] **Step 3: Remove unused imports**

Remove `_get_provider_token`, `build_receipt_provider_data` usage from handlers (keep function itself — it's used by `PaymentService`). Remove `ContactPricingService` import from handler file if no longer used.

- [ ] **Step 4: Update tests**

Update `tests/bot/handlers/test_payments.py`:
- Remove `contact_pricing_service` from handler test calls
- Tests already have `country="ru"` from previous work
- Ensure `payment_service` has `country_repo` in test setup
- Update `send_order_invoice` test calls to pass `invoice_data` instead of `price_value`

- [ ] **Step 5: Run full test suite**

```bash
make fix
```

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "refactor: handlers use InvoiceData from PaymentService"
```

---

### Task 7: Update admin panel

**Files:**
- Modify: `src/ugc_bot/admin/app.py:1884-1905` (ContactPricingAdmin)

- [ ] **Step 1: Update ContactPricingAdmin**

```python
class ContactPricingAdmin(ModelView, model=ContactPricingModel):
    """Admin view for contact pricing."""

    can_delete = False
    name = "Цена контакта"
    name_plural = "Цены контактов"
    column_list = [
        ContactPricingModel.country_code,
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.currency,
        ContactPricingModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        ContactPricingModel.country_code: "Страна",
        ContactPricingModel.bloggers_count: "Кол-во креаторов",
        ContactPricingModel.price: "Цена",
        ContactPricingModel.currency: "Валюта",
        ContactPricingModel.updated_at: "Обновлено",
    }
    form_columns = [
        ContactPricingModel.country_code,
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.currency,
    ]
```

- [ ] **Step 2: Add `tax_rate` to CountryModel admin (if exists)**

If there's a Country admin view, add `tax_rate` to `column_list`, `form_columns`, `column_labels`. If no Country admin exists, skip (admin can manage via DB directly).

- [ ] **Step 3: Run admin tests**

```bash
uv run pytest tests/admin/ -v
```

- [ ] **Step 4: Commit**

```bash
git add -u
git commit -m "feat: update admin panel for country-specific pricing"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run full quality check**

```bash
make fix
```

Expected: format ok, lint ok, mypy ok, all tests pass, coverage >= 98%.

- [ ] **Step 2: Push and deploy**

```bash
git push origin feature/intl-payment-provider-routing
```

Then on dev server:
```bash
ssh root@45.130.145.27
cd ugc && git pull && make dev-up
DEV_NETWORK=ugc_default make test-all-docker-dev
```

- [ ] **Step 3: Manual verification**

On dev server via bot:
1. RU advertiser → pay order → invoice in RUB, amount = contact_pricing only, YooKassa receipt present
2. International advertiser (e.g., GE) → pay order → invoice in GEL, amount = full formula, no receipt
