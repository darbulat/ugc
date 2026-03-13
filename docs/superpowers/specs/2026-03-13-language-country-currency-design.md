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

| Column        | Type         | Notes        |
|---------------|--------------|--------------|
| `code`        | VARCHAR (PK) | e.g. `"ru"`  |
| `name_native` | VARCHAR      | e.g. `"Русский"` |
| `enabled`     | BOOLEAN      | default TRUE |

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

```
/start received
  │
  ├─ user.language is None?
  │    ├─ from_user.language_code matches an enabled language?
  │    │    └─ yes → set_language(code), continue
  │    └─ no match → show language keyboard → wait for callback
  │         └─ lang:<code> callback → set_language(code), continue
  │
  ├─ user.country is None?
  │    └─ show country keyboard → wait for callback
  │         └─ country:<code> callback → set_country(code), continue
  │
  └─ show role keyboard
```

Existing users with `language` already set skip step 1. Existing users with `country` already set skip step 2.

### Language selection keyboard

- Callback prefix: `"lang:"`  (e.g. `"lang:ru"`, `"lang:en"`)
- Button labels: `language.name_native`
- New handler: `@router.callback_query(lambda c: c.data.startswith("lang:"))`

### Changing language later

- Command `/language` → shows language keyboard (always, even if language already set)
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

Texts that mention prices use `{currency}` as a placeholder. At render time, handlers substitute it with `country.currency_symbol` via `resolve_currency_symbol()`.

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
| `bot/texts/defaults.py` | Replace hardcoded currency names with `{currency}` |
| `container/service_factory.py` | Wire `LanguageRepository` |
| `telegram_webhook_app.py` | Inject `language_repo` into dispatcher data |
| `tests/helpers/fakes.py` | Add fake `LanguageRepository` |
