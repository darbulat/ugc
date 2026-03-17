# Referral Rewards with Multi-Currency Support

**Date:** 2026-03-17
**Status:** Draft
**Branch:** feature/intl-payment-provider-routing

## Problem

Current `ReferralIncomeService` calculates referral income on the fly from `payment.amount` without considering currency. With international expansion (RUB, GEL, KZT, BYN, etc.), amounts in different currencies get mixed, producing incorrect totals.

## Requirements

1. **Separate accounting by currency** — income displayed as breakdown: "120 ₽ • 15 ₾ • 500 ₸"
2. **Approximate total** in referrer's currency using cached exchange rates
3. **Per-currency payout buttons** — referrer chooses which currency to withdraw
4. **One PayoutRequest = one currency**
5. **Commission calculated from platform revenue** (`contact_pricing.price`), not from payment amount
6. **Exchange rates** from open.er-api.com (free, no API key), lazy-cached in Redis with 24h TTL
7. **Graceful degradation** — if exchange API unavailable, show breakdown without approximate total
8. **Rate limit** — one payout request per day per currency (independent)

## Design

### 1. Data Model

#### New table: `referral_income_entries`

```
referral_income_entries
├── entry_id: UUID (PK)
├── referrer_user_id: UUID (FK users)
├── referred_user_id: UUID (FK users)
├── order_id: UUID (FK orders)
├── income_type: str — "creator" | "advertiser"
├── currency: str(3) — from contact_pricing.currency
├── platform_revenue: Decimal(10,2) — contact_pricing.price (or per-creator share)
├── commission_rate: Decimal(5,4) — rate at time of calculation
├── commission_amount: Decimal(10,2) — final commission
├── created_at: datetime
└── UNIQUE(order_id, referrer_user_id, income_type)
```

- One order can produce two entries: one for creator-referral, one for advertiser-referral
- `INSERT ... ON CONFLICT DO NOTHING` for idempotency

#### Modified table: `payout_requests`

Add column `currency: str(3)`, default `"RUB"` (existing rows are all RUB).

### 2. Commission Calculation

Triggered when order transitions to `CLOSED` status. Called from the order-close handler as a direct call to `ReferralIncomeService.record_referral_income(order)`. Idempotency guaranteed by the unique constraint + `ON CONFLICT DO NOTHING`.

#### ContactPricing lookup

Country is resolved from the order's advertiser: `order.user_id → user.country_code`. Then `ContactPricingRepository.get_by_bloggers_count(country_code, order.bloggers_needed)` returns the pricing row. `contact_pricing.price` is the total platform revenue for the entire order (for all N bloggers).

If no ContactPricing found for a given `(country_code, bloggers_count)` — skip the entry and log a warning. For future orders this should not happen (validation at order creation), but historical data may have gaps.

#### Creator-referral

- For each creator on the order, check if they have a referrer via `UserReferralBinding`
- `platform_revenue = contact_pricing.price / order.bloggers_needed` (per-creator share of total platform fee)
- `commission_rate = user.referral_payout_rate ?? (first_year ? 0.10 : 0.03)`
- `first_year` = order closed within 1 year of the referred user's registration date
- `commission_amount = platform_revenue * commission_rate`
- `income_type = "creator"`, `currency` from `contact_pricing.currency`

#### Advertiser-referral

- Check if order owner has a referrer via `UserReferralBinding`
- `platform_revenue = contact_pricing.price` (full platform fee)
- `commission_rate` — same logic (based on referred advertiser's registration date)
- `commission_amount = platform_revenue * commission_rate`
- `income_type = "advertiser"`, `currency` from `contact_pricing.currency`

### 3. Exchange Rate Service

#### Ports (application layer)

```python
class ExchangeRateProvider(ABC):
    """External API for exchange rates."""
    async def fetch_rates(self, base_currency: str) -> dict[str, Decimal]

class ExchangeRateCache(ABC):
    """Cache for exchange rates."""
    async def get_rates(self, base_currency: str) -> Optional[dict[str, Decimal]]
    async def set_rates(self, base_currency: str, rates: dict[str, Decimal]) -> None
```

#### ReferralIncomeEntryRepository port

```python
class ReferralIncomeEntryRepository(ABC):
    async def save(self, entry: ReferralIncomeEntry, session=None) -> None
    async def get_totals_by_currency(self, referrer_user_id: UUID, session=None) -> dict[str, Decimal]
    async def get_orders_count_by_currency(self, referrer_user_id: UUID, session=None) -> dict[str, int]
    async def get_current_month_totals_by_currency(self, referrer_user_id: UUID, session=None) -> dict[str, Decimal]
```

#### ExchangeRateService (application layer)

```python
class ExchangeRateService:
    async def get_rate(self, from_currency: str, to_currency: str) -> Optional[Decimal]
    async def convert(self, amount: Decimal, from_currency: str, to_currency: str) -> Optional[Decimal]
    async def convert_many(self, amounts: dict[str, Decimal], to_currency: str) -> Optional[Decimal]
```

#### Infrastructure

- `OpenERApiProvider` — implementation using open.er-api.com (free, no API key)
- `RedisExchangeRateCache` — Redis with key `exchange_rates:{base}`, TTL 24h
- Fallback: if API unavailable and cache empty, methods return `None`

### 4. Display (`/referral` command)

```
Ваш реферальный доход:
• 1 200 ₽ (3 заказа)
• 45 ₾ (1 заказ)

≈ 1 380 ₽ (примерный итог)

Выплачено: 500 ₽
В ожидании: 200 ₽

[Выплатить 500 ₽] [Выплатить 45 ₾]
```

- Available balance per currency: `SUM(commission_amount) - SUM(PAID payouts) - SUM(PENDING payouts)` per currency
- PENDING payout amounts are frozen (subtracted from available balance)
- Payout button shows available balance (excluding both PAID and PENDING)
- Approximate total via `ExchangeRateService.convert_many()` to referrer's country currency
- If referrer has no country — default to RUB
- If exchange rates unavailable — omit approximate total line
- All display strings added to `bot_texts` / `DEFAULT_TEXTS` with both `"ru"` and `"en"` locale variants; handler receives `user_locale` via middleware

### 5. Payout Flow

1. Referrer taps `[Выплатить 500 ₽]`
2. `PayoutRequest(user_id, currency="RUB", amount=500)` created with status `PENDING`
3. Notification to `REFERRAL_SUPPORT_CHAT_ID`: "Запрос на выплату 500 ₽ от @username"
4. Admin taps "Выплачено" → status `PAID`
5. Button hidden while pending request exists for that currency
6. Rate limit: one request per day per currency (independent per currency)

### 6. Data Migration

Alembic migration (two separate migrations for safety):

**Migration A — schema changes:**
1. Create `referral_income_entries` table
2. Add `currency` column to `payout_requests` (default `"RUB"`)

**Migration B — data migration:**
3. Iterate all `CLOSED` orders with referral bindings, compute and insert `referral_income_entries` from `contact_pricing`. Note: may be slow on large datasets; consider running as a separate script if > 10k orders.

### 7. New Components Summary

| Layer | Component | Description |
|-------|-----------|-------------|
| Domain | `ReferralIncomeEntry` entity | Frozen dataclass |
| Domain | `ReferralIncomeType` enum | `CREATOR`, `ADVERTISER` |
| Application | `ExchangeRateProvider` port | ABC for external API |
| Application | `ExchangeRateCache` port | ABC for rate cache |
| Application | `ReferralIncomeEntryRepository` port | CRUD + GROUP BY currency |
| Application | `ExchangeRateService` | Conversion with lazy cache |
| Infrastructure | `OpenERApiProvider` | open.er-api.com implementation |
| Infrastructure | `RedisExchangeRateCache` | Redis cache, TTL 24h |
| Infrastructure | `ReferralIncomeEntryModel` | SQLAlchemy model |
| Infrastructure | Migration A + B | Schema + data migration |
| Bot | Updated `referral.py` | Multi-currency display + per-currency buttons |
| Admin | `ReferralIncomeEntryAdmin` | Read-only admin view for income entries |

### 8. Changes to Existing Code

| Component | Change |
|-----------|--------|
| `ReferralIncomeService` | New `record_referral_income()` on order close; `get_stats()` reads from table |
| `PayoutRequestModel` | Add `currency: str(3)` |
| `PayoutRequest` entity | Add `currency` field |
| `PayoutRequestAdmin` | Display and filter by `currency` column |
| `referral.py` handlers | Per-currency buttons, approximate total, localized texts |
| `container/` | Register new services and ports |

### 9. Unchanged

- `PaymentService`, `calculate_invoice_total()` — no changes
- `ReferralService` (pending/binding logic) — no changes
- Referral code mechanism — no changes
