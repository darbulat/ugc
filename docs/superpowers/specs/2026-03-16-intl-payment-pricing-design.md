# International Payment Pricing Design

## Context

Advertisers outside Russia must pay through a separate Telegram payment provider (`TELEGRAM_PROVIDER_TOKEN_INTL`) because YooKassa works only for RU. International invoices must include UGC video cost and country-specific tax on top of the contact pricing. Russian advertisers keep the current flow unchanged.

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
    tax_rate: float = 0.0    # 0.0 = 0%, 0.12 = 12%
    enabled: bool = True
```

Migration adds `tax_rate NUMERIC(5,4) NOT NULL DEFAULT 0` to `countries` table. RU stays at 0 (VAT handled via 54-FZ receipt, not added to price).

### ContactPricing entity — country-specific pricing

```python
@dataclass(frozen=True)
class ContactPricing:
    country_code: str        # part of composite PK
    bloggers_count: int      # part of composite PK
    price: float
    currency: str            # invoice currency (RUB, GEL, KZT...)
    updated_at: datetime
    created_at: datetime | None = None
```

Migration:
1. Add `country_code VARCHAR(2) NOT NULL DEFAULT 'ru'` to `contact_pricing`
2. Add `currency VARCHAR(3) NOT NULL DEFAULT 'RUB'` to `contact_pricing`
3. Drop old PK `(bloggers_count)`, create new PK `(country_code, bloggers_count)`
4. Add FK `country_code` -> `countries(code)`
5. Existing rows become `country_code='ru'`, `currency='RUB'`

## Service Layer Changes

### Pure calculation function

```python
def calculate_invoice_total(
    contact_pricing_price: float,
    order_price: float,
    bloggers_needed: int,
    tax_rate: float,
    is_ru: bool,
) -> float:
    if is_ru:
        return contact_pricing_price
    return (contact_pricing_price + order_price * bloggers_needed) * (1 + tax_rate)
```

No IO, easily testable.

### InvoiceData DTO

```python
@dataclass(frozen=True)
class InvoiceData:
    total: float              # final amount to charge
    currency: str             # invoice currency
    provider_token: str       # RU or intl Telegram provider token
    provider_data: str | None # 54-FZ YooKassa receipt (RU only) or None
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
3. Look up `Country` for `tax_rate` (if not RU)
4. Calculate total via `calculate_invoice_total()`
5. Select provider token via `_get_provider_token()`
6. Build `provider_data` (RU only)
7. Return `InvoiceData` or `None` if pricing not configured

### PaymentService — new dependency

`country_repo: CountryRepository` added via DI container.

### PaymentService.confirm_telegram_payment — updated validation

```python
is_ru = (user.country or "").lower() == "ru"
pricing = await self.pricing_repo.get_by_bloggers_count(
    order.bloggers_needed, country_code=user.country or "ru"
)
country = await self.country_repo.get_by_code(user.country) if not is_ru else None
tax_rate = country.tax_rate if country else 0.0

expected = calculate_invoice_total(
    pricing.price, order.price, order.bloggers_needed, tax_rate, is_ru
)
expected_minor = round(expected * 100)
if total_amount != expected_minor:
    raise OrderCreationError("amount mismatch")
```

Same `calculate_invoice_total` — single source of truth.

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

No longer calculates currency, provider token, or receipt internally. All comes from `InvoiceData`.

## Rollback from Current PR

The current `feature/intl-payment-provider-routing` branch contains `order_currency` logic that is superseded by this design. To roll back:

- Remove `order_currency` parameter from `send_order_invoice` and all call sites
- Keep `telegram_provider_token_intl` in config (needed)
- `_get_provider_token()` moves inside `PaymentService.calculate_invoice_data`
- Conditional `provider_data` (RU only) moves inside `PaymentService.calculate_invoice_data`

## Admin Panel

- `CountryModel`: add `tax_rate` to displayed columns
- `ContactPricingModel`: composite PK `(country_code, bloggers_count)` — verify SQLAdmin handles this correctly

## Testing

- `calculate_invoice_total`: unit tests for RU and international formulas, edge cases (tax_rate=0, price=0)
- `PaymentService.calculate_invoice_data`: test with RU user, international user, missing pricing
- `PaymentService.confirm_telegram_payment`: test validation with both formulas
- Existing payment handler tests: update to use `country="ru"` in test users (already done)
- New handler tests: international user scenarios
