# International Payment Pricing Design

## Context

Advertisers outside Russia must pay through a separate Telegram payment provider (`TELEGRAM_PROVIDER_TOKEN_INTL`) because YooKassa works only for RU. International invoices must include UGC video cost and country-specific tax on top of the contact pricing. Russian advertisers keep the current flow unchanged.

## Design Decisions

- **`user.country = None` fallback:** Users without a country are treated as Russian (fallback to `"ru"`). This matches the current user base where most users are RU.
- **Rounding:** All monetary calculations use `Decimal` to avoid floating-point drift. Both invoice-sending and payment validation use the same `calculate_invoice_total` function with `Decimal` arithmetic, ensuring identical results.
- **`Order.price` stays `float`:** Existing field with many dependents. Converted to `Decimal` at calculation boundaries via `Decimal(str(order.price))`. Full migration to `Decimal` is a separate refactor.
- **`ContactPricing.price` and `Country.tax_rate` are `Decimal`:** New/changed fields — typed correctly from the start.

## Pricing Formula

**For RU advertisers:**
```
total = contact_pricing.price
```
No changes. Invoice currency = RUB. YooKassa receipt (54-FZ) included.

**For international advertisers:**
```
total = (contact_pricing.price + order.price * order.bloggers_needed) * (1 + country.tax_rate)
```

Where:
- `contact_pricing.price` — total price for matching a package of N bloggers (looked up by `country_code` + `bloggers_count`)
- `order.price` — UGC video price **per one blogger** (set by advertiser at order creation)
- `order.bloggers_needed` — number of bloggers in the order
- `country.tax_rate` — tax rate for the advertiser's country (e.g., 0.12 = 12%)

Invoice currency = `contact_pricing.currency` (per-country pricing currency). No YooKassa receipt.

## Data Model Changes

### Country entity — new field

```python
@dataclass(frozen=True)
class Country:
    code: str
    name_native: str
    currency_code: str
    currency_symbol: str
    locale: str = "ru"
    tax_rate: Decimal = Decimal("0")  # 0 = 0%, 0.12 = 12%
    enabled: bool = True
```

Migration adds `tax_rate NUMERIC(5,4) NOT NULL DEFAULT 0` to `countries` table. RU stays at 0 (VAT handled via 54-FZ receipt, not added to price).

### ContactPricing entity — country-specific pricing

```python
@dataclass(frozen=True)
class ContactPricing:
    country_code: str        # part of composite PK
    bloggers_count: int      # part of composite PK
    price: Decimal
    currency: str            # invoice currency (RUB, GEL, KZT...)
    updated_at: datetime
    created_at: datetime | None = None
```

Migration:
1. Add `country_code VARCHAR(2) NOT NULL DEFAULT 'ru'` to `contact_pricing`
2. Add `currency VARCHAR(3) NOT NULL DEFAULT 'RUB'` to `contact_pricing`
3. Drop old PK `(bloggers_count)`, create new PK `(country_code, bloggers_count)` — done in a single migration step; table is small and rarely written
4. Add FK `country_code` -> `countries(code)`
5. Existing rows become `country_code='ru'`, `currency='RUB'`

## Service Layer Changes

### Pure calculation function

```python
def calculate_invoice_total(
    contact_pricing_price: Decimal,
    order_price: Decimal,
    bloggers_needed: int,
    tax_rate: Decimal,
    is_ru: bool,
) -> Decimal:
    if is_ru:
        return contact_pricing_price
    base = contact_pricing_price + order_price * bloggers_needed
    return (base * (1 + tax_rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

No IO, easily testable. Uses `Decimal` to avoid floating-point drift between invoice-sending and payment validation.

### InvoiceData DTO

```python
@dataclass(frozen=True)
class InvoiceData:
    total: Decimal            # final amount to charge
    currency: str             # invoice currency code (RUB, GEL, KZT)
    currency_symbol: str      # display symbol (₽, ₾, ₸)
    provider_token: str       # RU or intl Telegram provider token
    provider_data: str | None # 54-FZ YooKassa receipt (RU only) or None
    need_email: bool          # True for RU (YooKassa), False for intl
    is_ru: bool
```

### PaymentService — new method

```python
async def calculate_invoice_data(
    self, order: Order, user_country: str | None, config: AppConfig,
) -> InvoiceData | None:
```

Steps:
1. Determine `is_ru` from `user_country`
2. Look up `ContactPricing` by `(country_code, bloggers_needed)`
3. Look up `Country` for `tax_rate` and `currency_symbol` (if not RU)
4. Calculate total via `calculate_invoice_total()`
5. Select provider token via `_get_provider_token()`
6. Build `provider_data` (RU only)
7. Set `need_email=True` for RU, `False` for international
8. Return `InvoiceData` or `None` if pricing not configured

### PaymentService — new dependency

`country_repo: CountryRepository` added via DI container.

### PaymentService.confirm_telegram_payment — updated validation

```python
is_ru = (user.country or "").lower() == "ru"
country_code = (user.country or "ru").lower()
pricing = await self.pricing_repo.get_by_bloggers_count(
    order.bloggers_needed, country_code=country_code, session=session
)
country = await self.country_repo.get_by_code(user.country, session=session) if not is_ru else None
tax_rate = country.tax_rate if country else Decimal("0")

expected = calculate_invoice_total(
    pricing.price,              # already Decimal
    Decimal(str(order.price)),  # Order.price is float, convert at boundary
    order.bloggers_needed,
    tax_rate,                   # already Decimal
    is_ru,
)
expected_minor = int(expected * 100)
if total_amount != expected_minor:
    raise OrderCreationError("amount mismatch")
```

Same `calculate_invoice_total` — single source of truth. All repo calls pass `session=session` to stay within the transaction.

### ContactPricingRepository

`get_by_bloggers_count` gains `country_code` parameter:

```python
async def get_by_bloggers_count(
    self, bloggers_count: int, country_code: str = "ru", session=None
) -> ContactPricing | None:
```

### ContactPricingService

```python
async def get_price(
    self, bloggers_count: int, country_code: str = "ru"
) -> ContactPricing | None:
```

Returns full `ContactPricing` object (not just `float`).

## Handler Changes

### Three payment handlers simplified

`start_pay_order_link`, `pay_order`, `pay_order_callback` each become:

```python
invoice_data = await payment_service.calculate_invoice_data(order, user.country, config)
if invoice_data is None:
    # pricing not configured message
    ...
await send_order_invoice(invoice_data=invoice_data, ...)
```

`contact_pricing_service` removed from handler parameters — no longer needed directly.

### `send_order_invoice` accepts `InvoiceData`

No longer calculates currency, provider token, or receipt internally. All comes from `InvoiceData`. Uses `invoice_data.currency_symbol` for the label. Uses `invoice_data.need_email` and `send_email_to_provider=invoice_data.need_email` (YooKassa-specific, only for RU).

Invoice label uses `bot_texts_service` for localized text instead of hardcoded Russian.

## Rollback from Current PR

The current `feature/intl-payment-provider-routing` branch contains `order_currency` logic that is superseded by this design. To roll back:

- Remove `order_currency` parameter from `send_order_invoice` and all call sites
- Keep `telegram_provider_token_intl` in config (needed)
- `_get_provider_token()` moves inside `PaymentService.calculate_invoice_data`
- Conditional `provider_data` (RU only) moves inside `PaymentService.calculate_invoice_data`

## Admin Panel

- `CountryModel`: add `tax_rate` to `column_list`, `form_columns`, `column_labels`
- `ContactPricingModel`: add `country_code` and `currency` to `column_list`, `form_columns`, `column_labels`. Composite PK `(country_code, bloggers_count)` — sqladmin supports composite PKs for list/detail/edit views. If issues arise, fallback: add surrogate `id` serial PK with unique constraint on `(country_code, bloggers_count)`.

## Testing

- `calculate_invoice_total`: unit tests for RU and international formulas, edge cases (tax_rate=0, price=0, large values)
- `PaymentService.calculate_invoice_data`: test with RU user, international user, missing pricing, user.country=None
- `PaymentService.confirm_telegram_payment`: test validation with both formulas, verify Decimal rounding matches
- Existing payment handler tests: update to use `country="ru"` in test users (already done)
- New handler tests: international user scenarios
- Update in-memory fakes: `InMemoryContactPricingRepository` in `memory_repositories.py` and `tests/helpers/fakes.py` to support `country_code` parameter
