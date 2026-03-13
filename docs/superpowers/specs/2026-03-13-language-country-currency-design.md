# Language, Country, and Currency Selection — Design Spec

**Date:** 2026-03-13
**Status:** Approved

## Summary

Users can independently choose their language (affects bot UI texts) and country (affects currency symbol). Language and country are decoupled. Currency is always shown as a symbol derived from the user's country at runtime.

## Goals

- Give users explicit language selection (arbitrary number of languages, stored in DB)
- Give users country selection (already exists, kept as-is minus `locale` field)
- Currency symbol shown from `country.currency_symbol`, substituted via `{currency}` placeholder in bot texts
- Language and country are fully independent (e.g., Kazakhstan + English)

## Non-Goals

- Currency number formatting (decimal separators, etc.)
- Currency conversion
- Language-specific country lists

---

## Domain Layer

### New Entity: `Language`

```python
@dataclass(frozen=True)
class Language:
    code: str         # IETF-style: "ru", "en", "kk"
    name_native: str  # "Русский", "English", "Қазақша"
    enabled: bool = True
```

### Changes to `User`

Add field:
```python
language: Optional[str] = None  # language code from languages.code
```

### Changes to `Country`

Remove field `locale: str` — country no longer determines UI language.

---

## Database

### New table: `languages`

| Column        | Type             | Notes        |
|---------------|------------------|--------------|
| `code`        | VARCHAR(10) (PK) | e.g. `"ru"`  |
| `name_native` | VARCHAR          | e.g. `"Русский"` |
| `enabled`     | BOOLEAN          | default TRUE |

### Modified table: `users`

Add column: `language VARCHAR NULL` — references `languages.code` (no FK constraint, soft reference).

### Modified table: `countries`

Remove column: `locale`.

### Modified table: `bot_texts`

Remove rows where `locale IN ('by', 'kz', 'kg', 'am', 'uz', 'ge')` — these were country-code hacks from migration 0064. Language-specific texts use language codes as `locale`.

---

## Migration (0065)

Steps in a single Alembic revision:

1. Create `languages` table
2. Insert initial languages from current `countries.locale` distinct values (at minimum: `ru`, `en`)
3. Add `users.language VARCHAR NULL`
4. Populate `users.language`:
   ```sql
   UPDATE users
   SET language = countries.locale
   FROM countries
   WHERE users.country = countries.code
   ```
5. Drop `countries.locale` column
6. Delete country-code bot_texts overrides:
   ```sql
   DELETE FROM bot_texts
   WHERE locale IN ('by', 'kz', 'kg', 'am', 'uz', 'ge')
   ```
   **Safety:** These rows are safe to delete because all affected keys (`prompt_edit_price`, `msg_step_ask_price`, `msg_order_budget`) have canonical `ru`/`en` rows in `DEFAULT_TEXTS` used as fallback. Verify in migration that `ru` rows exist for all three keys before deleting.

**Note on users with `country = NULL` at migration time:** Step 4 only populates `users.language` for users who already have a country. Users with `country = NULL` will retain `language = NULL`. This is intentional — `LocaleMiddleware` falls back to `default_locale` for them, and the `/start` flow will prompt them to choose a language on next interaction.

---

## Repository Layer

### `LanguageRepository` (abstract port)

```python
class LanguageRepository(ABC):
    async def list_enabled(self) -> list[Language]: ...
    async def get_by_code(self, code: str) -> Language | None: ...
```

Implementations:
- `SqlAlchemyLanguageRepository` in `infrastructure/db/repositories.py`
- `MemoryLanguageRepository` in `infrastructure/memory_repositories.py`
- Fake in `tests/helpers/fakes.py`

---

## Middleware

### `LocaleMiddleware` (changed)

New resolution order in `_resolve()`:
1. Load user by `external_id`
2. If `user.language` is set → return it
3. Return `data["default_locale"]` or `"ru"`

`country.locale` no longer participates in locale resolution.

---

## User Flow

### `/start` — First-time user (three steps)

No FSM state is used. Each step is re-evaluated on each callback by checking `user.language` and `user.country` from the DB. This is the same pattern as the existing `country_selected` handler.

```
/start received
  │
  ├─ user.language is None?
  │    ├─ from_user.language_code matches an enabled language?
  │    │    └─ yes → set_language(code), re-check country below
  │    └─ no match → show language keyboard → return
  │         └─ lang:<code> callback:
  │              set_language(code)
  │              if user.country is None → show country keyboard → return
  │              else → show role keyboard → return
  │
  ├─ user.country is None?
  │    └─ show country keyboard → return
  │         └─ country:<code> callback (existing handler, unchanged):
  │              set_country(code) → show role keyboard
  │
  └─ show role keyboard
```

Existing users with `language` already set skip step 1. Existing users with `country` already set skip step 2.

### Language selection keyboard

- Callback prefix: `"lang:"`  (e.g. `"lang:ru"`, `"lang:en"`)
- Button labels: `language.name_native`
- Handler in `bot/handlers/start.py`: `@router.callback_query(lambda c: c.data.startswith(CALLBACK_LANG_PREFIX))`

### Changing language later

- Command `/language` (registered in `bot/handlers/start.py` router) → shows language keyboard (always, even if language already set)
- Profile screen → button `btn_change_language` → same keyboard
- Handler saves new language and responds with confirmation in the new language

### `UserRoleService.set_language()`

New method analogous to `set_country()`:
```python
async def set_language(
    self,
    *,
    external_id: str,
    messenger_type: MessengerType,
    language_code: str,
) -> None: ...
```

---

## Bot Texts

### Locale = language code

`bot_texts.locale` stores language codes from `languages.code`. Examples:
- `(key="prompt_edit_price", locale="ru")` → `"Укажите цену за 1 UGC‑видео ({currency}):"`
- `(key="prompt_edit_price", locale="en")` → `"Price for 1 UGC video ({currency}):"`

### `{currency}` placeholder

Texts that mention prices use `{currency}` as a placeholder. At render time, handlers substitute it with `country.currency_symbol` via the existing `resolve_currency_symbol(user, country_repo, default)` helper in `bot/handlers/utils.py` (no changes needed to this function).

**Fallback when user has no country:** `resolve_currency_symbol()` already accepts a `default` argument (currently `"₽"`). The dispatcher also injects `currency_symbol` from `config.market.currency_symbol`. When a user has no country set (mid-onboarding), handlers use the config-provided default symbol. The `{currency}` placeholder will never appear literally — callers must always provide a fallback.

Before:
```
"в рублях" / "в тенге"  (hardcoded currency names)
```
After:
```
"({currency})"  →  "(₽)" / "(₸)" / "(€)" at runtime
```

Affected keys in `DEFAULT_TEXTS["ru"]`:
- `prompt_edit_price`: `"Укажите цену за 1 UGC‑видео ({currency}):"`
- `msg_step_ask_price`: `"...Цена ({currency}), например: 500, 1000, 2000\n\nШаг 10 из 12"`
- `msg_order_budget`: `"Бюджет за 1 UGC-видео? Укажите цену ({currency}): 500, 1000, 2000"`

### New text keys

Add to all supported locales:
- `language_prompt` — invitation to choose language (shown before user has a language)
- `btn_change_language` — button label in profile
- `language_changed` — confirmation after language change

### Language prompt (before language is known)

Since no language is set yet, the prompt is shown in the language matched from `from_user.language_code`. If no match, fall back to default locale.

---

## Service-Level Localization

Several places across the codebase send messages to users with hardcoded Russian strings, bypassing `bot_texts_service`. All user-facing hardcoded strings must become bot_text keys fetched via `bot_texts_service.get_many(keys, locale)` using the blogger's/user's `user.language`.

Admin-only messages ("Открыть в админке", "Активировать", complaint/moderation notifications) are excluded — admins always use Russian.

### `OfferDispatchService.format_offer()` + `kafka_consumer.py`

`format_offer()` builds a Russian-only offer message. Must accept `locale: str` and `bot_texts_service: BotTextsService`.

`kafka_consumer.py::_send_offer_to_blogger()` has hardcoded button texts and must also pass `blogger.language` and `bot_texts_service` to `format_offer()` and the button builder.

New bot_text keys:
- `offer_header` — "Новый заказ"
- `offer_details_header` — "📋 Детали заказа:"
- `offer_format` — "🎥 Формат: {format_label}"
- `offer_task` — "📝 Задача: {task}"
- `offer_budget` — "💰 Бюджет: {price} {currency} за 1 UGC-видео"
- `offer_barter` — "🎁 Бартер: {description}"
- `offer_content_usage` — "📢 Использование: {usage}"
- `offer_deadlines` — "⏱ Сроки: {deadlines}"
- `offer_geography` — "📍 География: {geography}"
- `offer_bloggers_needed` — "👥 Нужно креаторов: {count}"
- `offer_warning` — warning block text
- `offer_how_it_works` — how-it-works block text
- `offer_format_label_ugc_placement` — "UGC + размещение"
- `offer_format_label_ugc_only` — "UGC-видео для бренда"
- `btn_offer_accept` — "Готов снять UGC" (button in `kafka_consumer.py`)
- `btn_offer_skip` — "Пропустить" (button in `kafka_consumer.py`)

**Files:** `application/services/offer_dispatch_service.py`, `kafka_consumer.py`, `bot/texts/defaults.py`

### `feedback_scheduler.py`

Sends feedback request messages to users with hardcoded Russian strings. Must load `user.language` per user and fetch texts via `bot_texts_service`.

Affected keys (already exist in `DEFAULT_TEXTS` but not fetched from service):
- Feedback button texts (`btn_feedback_ok`, `btn_feedback_no_deal`, etc.) — already in `DEFAULT_TEXTS`, need to use user locale
- Feedback request message templates (`msg_feedback_request`, etc.) — need locale-aware fetch

**File:** `feedback_scheduler.py`

### `complaints.py`

Button "Пожаловаться на {blogger_name}" is hardcoded. Needs bot_text key:
- `btn_complaint` — "Пожаловаться на {name}"

**File:** `bot/handlers/complaints.py`

### `offer_responses.py`

Hardcoded order type labels ("UGC + размещение", "UGC-видео для бренда") and button fallbacks. These keys already exist in `DEFAULT_TEXTS` — handlers must use `user_locale` when building these strings instead of hardcoding.

**File:** `bot/handlers/offer_responses.py`

### `start.py`, `feedback.py`, `advertiser_registration.py`, `referral.py`

These files have hardcoded Russian fallbacks for cases when `bot_texts_service` returns empty. The strings already exist in `DEFAULT_TEXTS` — the fix is to always call `bot_texts_service.get(key, locale)` and rely on `DEFAULT_TEXTS` as the ultimate fallback (which `BotTextsService` already handles). No new bot_text keys needed for these.

---

## Admin Panel

Register `LanguageModel` in SQLAdmin — allows adding/editing/enabling languages without a deploy.

---

## Testing

### Unit tests

- `LocaleMiddleware` — user with language set, user without language, no user
- `_start_command` — three branches: auto-detect matches, auto-detect misses, country missing
- `lang:` callback handler — saves language, proceeds to next step
- `/language` command — shows keyboard regardless of current language

### Integration tests

- Migration 0065 — verify `users.language` populated correctly, `countries.locale` gone, bot_texts country-overrides removed

### In-memory fakes

`MemoryLanguageRepository` follows the same pattern as `MemoryCountryRepository`.

---

## File Changes Summary

| File | Change |
|------|--------|
| `domain/entities.py` | Add `Language`, add `User.language`, remove `Country.locale` |
| `application/ports.py` | Add `LanguageRepository` ABC |
| `application/services/user_role_service.py` | Add `set_language()` |
| `infrastructure/db/models.py` | Add `LanguageModel`, add `UserModel.language`, remove `CountryModel.locale` |
| `infrastructure/db/repositories.py` | Add `SqlAlchemyLanguageRepository`, update user/country mapping |
| `infrastructure/memory_repositories.py` | Add `MemoryLanguageRepository` |
| `infrastructure/db/migrations/versions/0065_*.py` | New migration |
| `bot/middleware/locale.py` | Use `user.language` only |
| `bot/handlers/start.py` | Add language step, language callback handler |
| `bot/handlers/keyboards.py` | Add `language_inline_keyboard()`, `CALLBACK_LANG_PREFIX` |
| `bot/handlers/profile.py` | Add language change button + handler |
| `bot/texts/defaults.py` | Replace hardcoded currency names with `{currency}`; add offer text keys |
| `application/services/offer_dispatch_service.py` | Accept `locale` + `bot_texts_service`; localize `format_offer()` |
| `kafka_consumer.py` | Pass blogger `user.language` + `bot_texts_service`; localize offer buttons |
| `feedback_scheduler.py` | Load `user.language` per user; fetch feedback texts via `bot_texts_service` |
| `bot/handlers/complaints.py` | Replace hardcoded "Пожаловаться на {name}" with bot_text key |
| `bot/handlers/offer_responses.py` | Replace hardcoded order type labels with bot_text keys |
| `container/service_factory.py` | Wire `LanguageRepository`; add `language_repo` to `build_dispatcher_data()` |
| `miniapp/api.py` | Update `_get_user_locale()` to use `user.language` instead of `country.locale` |
| `tests/helpers/fakes.py` | Add fake `LanguageRepository` |
