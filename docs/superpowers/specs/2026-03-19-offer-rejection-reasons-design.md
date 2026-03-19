# Offer Rejection Reasons — Design Spec

**Date:** 2026-03-19
**Status:** Approved

## Problem

When a creator clicks "Пропустить" on an offer, no reason is captured. This prevents understanding market pricing, ad format preferences, and product interest — data needed for dynamic pricing and re-targeting.

## Solution

After pressing "Пропустить", the creator must select a rejection reason. If "Низкая цена" is selected, the creator enters a desired price. A notification is sent to the order's manager for low-price rejections.

## Domain

### New enum `RejectionReason`

Located in `domain/enums.py` (following existing enum pattern):

```python
class RejectionReason(StrEnum):
    LOW_PRICE = "low_price"
    WRONG_FORMAT = "wrong_format"
    UNINTERESTING_PRODUCT = "uninteresting_product"
    NO_TIME = "no_time"
```

### Extended `OfferDispatch` entity

Two new fields:
- `rejection_reason: Optional[RejectionReason] = None`
- `desired_price: Optional[Decimal] = None` — only when `rejection_reason == LOW_PRICE`

## Database

### Migration

Add to `offer_dispatches`:
- `rejection_reason VARCHAR` — nullable
- `desired_price NUMERIC` — nullable

No indexes initially.

### Model

`OfferDispatchModel` gains corresponding mapped columns.

## Bot Flow

### Current

```
[Пропустить] → record_skip() → "Ок, пропущено."
```

### New

```
[Пропустить]
  → Inline keyboard with 4 reasons
    → [Низкая цена]
        → FSM state: waiting_desired_price
        → Creator enters price
        → Validation: offer_price ≤ value ≤ offer_price × 10
        → record_skip(reason=LOW_PRICE, desired_price=value)
        → Notify manager via Telegram
        → Confirmation with summary
    → [Не подходит формат / Неинтересный продукт / Нет времени]
        → record_skip(reason=<selected>)
        → Confirmation with summary
```

### Callback data

- `offer_skip:{order_id}` — existing, now shows reason menu instead of recording skip. Original offer keyboard is removed immediately on click (prevents double-clicks).
- `orr:{order_id_hex}:{reason}` — new, selects a specific reason. Uses short prefix `orr:` and UUID without dashes (32 chars) to fit Telegram's 64-byte callback data limit. Example: `orr:550e8400e29b41d4a716446655440000:low_price` (52 bytes).

### FSM state

New `OfferSkipStates(StatesGroup)` defined in `offer_responses.py` (following existing pattern of colocating FSM states with handlers):
- `waiting_desired_price = State()` — waiting for price input
- State data stores `order_id` and `reason`

### Price validation

- Parse text as `Decimal` (use `Decimal(str)` to avoid float precision issues)
- Min: offer price (from order, converted to `Decimal`)
- Max: offer price × 10
- On error: re-prompt with hint showing valid range
- Non-text messages (stickers, photos, etc.) are ignored with a re-prompt
- Cancel button available: sends `orr_cancel:{order_id_hex}` — records skip without reason (graceful exit)

## Service Layer

### `OfferDispatchService.record_skip()`

Extended signature:

```python
async def record_skip(
    self,
    order_id: UUID,
    blogger_id: UUID,
    rejection_reason: RejectionReason,
    desired_price: Decimal | None = None,
) -> None:
```

### `OfferDispatchRepository.record_response()`

Add `rejection_reason` and `desired_price` parameters, pass through to UPDATE.

### Manager notification

On `LOW_PRICE`: `record_skip()` returns a result dataclass indicating notification is needed (with manager_id, blogger info, prices). The handler then sends the Telegram message to the manager. This keeps the service layer free of messaging infrastructure dependencies (consistent with current `OfferDispatchService` which only has repository dependencies).

```python
@dataclass(slots=True)
class SkipResult:
    rejection_reason: RejectionReason
    desired_price: Decimal | None = None
    manager_id: UUID | None = None  # set when notification needed
    order_price: Decimal | None = None
```

## Localization

New text keys across 5 locales (RU, EN, BE, KK, UZ):

| Key | Purpose |
|-----|---------|
| `msg_offer_skip_reason_prompt` | Prompt to select reason |
| `btn_reject_low_price` | Button: low price |
| `btn_reject_wrong_format` | Button: wrong format |
| `btn_reject_uninteresting` | Button: uninteresting product |
| `btn_reject_no_time` | Button: no time |
| `msg_enter_desired_price` | Prompt for price input |
| `msg_invalid_price` | Validation error with {min}, {max}, {currency} |
| `msg_offer_skipped_with_reason` | Confirmation with {reason} |
| `msg_offer_skipped_low_price` | Confirmation with {price}, {currency}, re-offer hint |
| `msg_manager_low_price_notification` | Manager notification with {blogger}, {order}, {desired_price}, {offer_price}, {currency} |

### Translations

**RU:**
- `msg_offer_skip_reason_prompt`: Укажите причину отказа:
- `btn_reject_low_price`: Низкая цена
- `btn_reject_wrong_format`: Не подходит формат рекламы
- `btn_reject_uninteresting`: Неинтересный продукт / предложение
- `btn_reject_no_time`: Нет времени
- `msg_enter_desired_price`: Укажите, за какую стоимость вы готовы разместить рекламу:
- `msg_invalid_price`: Введите число от {min} до {max} {currency}
- `msg_offer_skipped_with_reason`: Спасибо за обратную связь. Вы отказались: {reason}. Пропущено.
- `msg_offer_skipped_low_price`: Спасибо за обратную связь. Вы отказались: Низкая цена. Желаемая сумма: {price} {currency}. Мы можем вернуться с новым предложением.
- `msg_manager_low_price_notification`: Блогер {blogger} отказался от заказа «{order}»: низкая цена. Готов за {desired_price} {currency} (в оффере: {offer_price} {currency}).

**EN:**
- `msg_offer_skip_reason_prompt`: Please select a reason:
- `btn_reject_low_price`: Low price
- `btn_reject_wrong_format`: Wrong ad format
- `btn_reject_uninteresting`: Uninteresting product
- `btn_reject_no_time`: No time
- `msg_enter_desired_price`: Enter your desired price:
- `msg_invalid_price`: Enter a number from {min} to {max} {currency}
- `msg_offer_skipped_with_reason`: Thanks for feedback. Declined: {reason}. Skipped.
- `msg_offer_skipped_low_price`: Thanks. Declined: Low price. Desired: {price} {currency}. We may return with a new offer.
- `msg_manager_low_price_notification`: Blogger {blogger} declined "{order}": low price. Wants {desired_price} {currency} (offered: {offer_price} {currency}).

**BE:**
- `msg_offer_skip_reason_prompt`: Пазначце прычыну адмовы:
- `btn_reject_low_price`: Нізкая цана
- `btn_reject_wrong_format`: Не падыходзіць фармат рэкламы
- `btn_reject_uninteresting`: Нецікавы прадукт / прапанова
- `btn_reject_no_time`: Няма часу
- `msg_enter_desired_price`: Пазначце, за якую кошт вы гатовы размясціць рэкламу:
- `msg_invalid_price`: Увядзіце лік ад {min} да {max} {currency}
- `msg_offer_skipped_with_reason`: Дзякуй за зваротную сувязь. Вы адмовіліся: {reason}. Прапушчана.
- `msg_offer_skipped_low_price`: Дзякуй. Адмовіліся: Нізкая цана. Жаданая сума: {price} {currency}. Мы можам вярнуцца з новай прапановай.
- `msg_manager_low_price_notification`: Блогер {blogger} адмовіўся ад замовы «{order}»: нізкая цана. Гатовы за {desired_price} {currency} (у оферы: {offer_price} {currency}).

**KK:**
- `msg_offer_skip_reason_prompt`: Бас тарту себебін көрсетіңіз:
- `btn_reject_low_price`: Баға төмен
- `btn_reject_wrong_format`: Жарнама форматы сәйкес келмейді
- `btn_reject_uninteresting`: Қызықсыз өнім / ұсыныс
- `btn_reject_no_time`: Уақыт жоқ
- `msg_enter_desired_price`: Жарнаманы қанша бағаға орналастыруға дайынсыз:
- `msg_invalid_price`: {min} мен {max} {currency} арасында сан енгізіңіз
- `msg_offer_skipped_with_reason`: Кері байланыс үшін рахмет. Бас тарттыңыз: {reason}. Өткізілді.
- `msg_offer_skipped_low_price`: Рахмет. Бас тарту: Баға төмен. Қалаған сома: {price} {currency}. Жаңа ұсыныспен қайта ораламыз.
- `msg_manager_low_price_notification`: Блогер {blogger} «{order}» тапсырысынан бас тартты: баға төмен. {desired_price} {currency} дайын (офферде: {offer_price} {currency}).

**UZ:**
- `msg_offer_skip_reason_prompt`: Rad etish sababini ko'rsating:
- `btn_reject_low_price`: Narx past
- `btn_reject_wrong_format`: Reklama formati mos emas
- `btn_reject_uninteresting`: Qiziq bo'lmagan mahsulot / taklif
- `btn_reject_no_time`: Vaqt yo'q
- `msg_enter_desired_price`: Qancha narxga reklama joylashga tayyorsiz:
- `msg_invalid_price`: {min} dan {max} {currency} gacha son kiriting
- `msg_offer_skipped_with_reason`: Fikr-mulohaza uchun rahmat. Rad ettingiz: {reason}. O'tkazib yuborildi.
- `msg_offer_skipped_low_price`: Rahmat. Rad: Narx past. Xohlagan summa: {price} {currency}. Yangi taklif bilan qaytishimiz mumkin.
- `msg_manager_low_price_notification`: Bloger {blogger} «{order}» buyurtmasidan voz kechdi: narx past. {desired_price} {currency} tayyor (offerda: {offer_price} {currency}).

## Admin Panel

- Two new columns in `OfferDispatch` list: **Причина отказа**, **Желаемая цена**
- Filter by `rejection_reason`

## Testing

- **Unit:** FSM flow for reason selection, price validation (boundary: exact offer_price, ×10, below, above, non-numeric), manager notification formatting
- **Integration:** `record_skip` with reason and price persists correctly
- **In-memory fakes:** update `MemoryOfferDispatchRepository` for new fields

## Key Files to Modify

| Component | File |
|-----------|------|
| Domain enum | `src/ugc_bot/domain/enums.py` |
| Domain entity | `src/ugc_bot/domain/entities.py` |
| DB model | `src/ugc_bot/infrastructure/db/models.py` |
| Migration | `src/ugc_bot/infrastructure/db/migrations/versions/` (new) |
| Repository port | `src/ugc_bot/application/ports.py` |
| Repository impl | `src/ugc_bot/infrastructure/db/repositories/interactions.py` |
| Memory repo | `src/ugc_bot/infrastructure/memory_repositories.py` |
| Offer dispatch service | `src/ugc_bot/application/services/offer_dispatch_service.py` |
| Bot handler + FSM states | `src/ugc_bot/bot/handlers/offer_responses.py` |
| Text defaults (ru) | `src/ugc_bot/bot/texts/defaults/ru.py` |
| Text defaults (en) | `src/ugc_bot/bot/texts/defaults/en.py` |
| Text defaults (be) | `src/ugc_bot/bot/texts/defaults/be.py` |
| Text defaults (kk) | `src/ugc_bot/bot/texts/defaults/kk.py` |
| Text defaults (uz) | `src/ugc_bot/bot/texts/defaults/uz.py` |
| Admin | `src/ugc_bot/admin/app.py` |
| Unit tests | `tests/unit/` |
| Integration tests | `tests/integration/` |
