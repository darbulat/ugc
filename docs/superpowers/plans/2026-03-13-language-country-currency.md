# Language, Country & Currency Selection — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple user language (UI texts) from country (currency), add explicit language selection to the /start flow, and replace all hardcoded Russian strings in user-facing messages with localized bot_texts keys.

**Architecture:** New `languages` DB table + `Language` entity mirrors the existing `Country` pattern. `User.language` (new field) drives `LocaleMiddleware`. Country drives currency symbol only. `format_offer()` and other user-facing services accept `locale` + `bot_texts_service`.

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2, Alembic, PostgreSQL 16, pytest, pydantic-settings.

**Spec:** `docs/superpowers/specs/2026-03-13-language-country-currency-design.md`

---

## Chunk 1: Foundation — Entity, DB, Repos, Middleware, Wiring

### Task 1: Language entity + User.language + remove Country.locale

**Files:**
- Modify: `src/ugc_bot/domain/entities.py`

- [ ] **Step 1: Add `Language` entity and `User.language`; remove `Country.locale`**

In `src/ugc_bot/domain/entities.py`:

```python
# Add after existing imports, before Country:
@dataclass(frozen=True)
class Language:
    """Language entity for multi-language support."""

    code: str
    name_native: str
    enabled: bool = True
```

In `Country` dataclass: remove the `locale: str = "ru"` field entirely.

In `User` dataclass: add `language: Optional[str] = None` after `country: Optional[str] = None`.

- [ ] **Step 2: Fix all Country(...) call sites that pass `locale=`**

Run:
```bash
grep -rn "locale=" src/ugc_bot/infrastructure/db/repositories.py
```

In `src/ugc_bot/infrastructure/db/repositories.py`, find `_to_country_entity` and remove `locale=model.locale` from the `Country(...)` call.

Also remove `locale=model.locale` from any `Country(...)` calls in `src/ugc_bot/infrastructure/memory_repositories.py`.

- [ ] **Step 3: Run typecheck to find all broken callsites**

```bash
make typecheck
```

Fix any remaining `Country(locale=...)` references reported by mypy.

- [ ] **Step 4: Run make fix + tests**

```bash
make fix
```

Expected: all tests pass (some Country-locale tests may fail — fix them to not pass `locale`).

---

### Task 2: DB ORM model for Language + update User and Country models

**Files:**
- Modify: `src/ugc_bot/infrastructure/db/models.py`

- [ ] **Step 1: Add `LanguageModel` ORM class**

In `src/ugc_bot/infrastructure/db/models.py`, add after `CountryModel`:

```python
class LanguageModel(Base):
    """Language ORM model."""

    __tablename__ = "languages"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name_native: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
```

- [ ] **Step 2: Add `language` column to `UserModel`**

In `UserModel`, add after the `country` field:

```python
language: Mapped[Optional[str]] = mapped_column(
    String(10), nullable=True, default=None
)
```

- [ ] **Step 3: Remove `locale` column from `CountryModel`**

Remove this from `CountryModel`:
```python
locale: Mapped[str] = mapped_column(
    String(8), nullable=False, server_default=text("'ru'")
)
```

- [ ] **Step 4: Run typecheck**

```bash
make typecheck
```

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/infrastructure/db/models.py
git commit -m "feat: add LanguageModel ORM, add users.language, remove countries.locale"
```

---

### Task 3: Alembic migration 0065

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0066_languages.py`

- [ ] **Step 1: Write the migration**

The current last migration is `0065_agreement_confirmed_at_profiles`. New migration chains from it.

```python
"""Add languages table, users.language; remove countries.locale; clean bot_texts."""

import sqlalchemy as sa
from alembic import op

revision = "0066_languages"
down_revision = "0065_agreement_confirmed_at_profiles"
branch_labels = None
depends_on = None

_COUNTRY_LOCALE_KEYS = ("by", "kz", "kg", "am", "uz", "ge")
_PRICE_TEXT_KEYS = ("prompt_edit_price", "msg_step_ask_price", "msg_order_budget")


def upgrade() -> None:
    """Create languages table, add users.language, drop countries.locale."""
    # 1. Create languages table
    op.create_table(
        "languages",
        sa.Column("code", sa.String(10), primary_key=True),
        sa.Column("name_native", sa.String(64), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    # 2. Seed initial languages from distinct countries.locale values
    conn = op.get_bind()
    seed = [
        ("ru", "Русский"),
        ("en", "English"),
    ]
    seen: set[str] = {code for code, _ in seed}
    for code, name in seed:
        conn.execute(
            sa.text(
                "INSERT INTO languages (code, name_native, enabled) "
                "VALUES (:code, :name, true) ON CONFLICT DO NOTHING"
            ),
            {"code": code, "name": name},
        )
    # Insert any extra locales found in countries that weren't in seed
    rows = conn.execute(
        sa.text("SELECT DISTINCT locale FROM countries")
    ).fetchall()
    for (locale,) in rows:
        if locale and locale not in seen:
            conn.execute(
                sa.text(
                    "INSERT INTO languages (code, name_native, enabled) "
                    "VALUES (:code, :name, true) ON CONFLICT DO NOTHING"
                ),
                {"code": locale, "name": locale},
            )
            seen.add(locale)

    # 3. Add users.language column
    op.add_column(
        "users",
        sa.Column("language", sa.String(10), nullable=True),
    )

    # 4. Populate users.language from countries.locale
    conn.execute(
        sa.text(
            "UPDATE users "
            "SET language = countries.locale "
            "FROM countries "
            "WHERE users.country = countries.code"
        )
    )

    # 5. Drop countries.locale column
    op.drop_column("countries", "locale")

    # 6. Delete country-code bot_texts overrides (hacks from migration 0064)
    for locale in _COUNTRY_LOCALE_KEYS:
        for key in _PRICE_TEXT_KEYS:
            conn.execute(
                sa.text(
                    "DELETE FROM bot_texts WHERE key = :key AND locale = :locale"
                ),
                {"key": key, "locale": locale},
            )


def downgrade() -> None:
    """Reverse migration."""
    conn = op.get_bind()

    # Re-add countries.locale (default 'ru')
    op.add_column(
        "countries",
        sa.Column(
            "locale",
            sa.String(8),
            nullable=False,
            server_default=sa.text("'ru'"),
        ),
    )

    # Drop users.language
    op.drop_column("users", "language")

    # Drop languages table
    op.drop_table("languages")
```

- [ ] **Step 2: Verify migration runs**

```bash
make migrate
```

Expected: migration applies without errors.

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0066_languages.py
git commit -m "feat: migration 0066 — languages table, users.language, drop countries.locale"
```

---

### Task 4: `LanguageRepository` — port + SQLAlchemy + memory implementations

**Files:**
- Modify: `src/ugc_bot/application/ports.py`
- Modify: `src/ugc_bot/infrastructure/db/repositories.py`
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py`

- [ ] **Step 1: Write failing test for `MemoryLanguageRepository`**

Create `tests/unit/test_language_repository.py`:

```python
"""Tests for LanguageRepository implementations."""

import pytest
from ugc_bot.domain.entities import Language
from ugc_bot.infrastructure.memory_repositories import MemoryLanguageRepository


@pytest.fixture()
def repo() -> MemoryLanguageRepository:
    ru = Language(code="ru", name_native="Русский", enabled=True)
    en = Language(code="en", name_native="English", enabled=True)
    disabled = Language(code="xx", name_native="Disabled", enabled=False)
    return MemoryLanguageRepository(
        languages={"ru": ru, "en": en, "xx": disabled}
    )


@pytest.mark.asyncio()
async def test_list_enabled_returns_only_enabled(repo):
    result = await repo.list_enabled()
    codes = {l.code for l in result}
    assert codes == {"ru", "en"}


@pytest.mark.asyncio()
async def test_get_by_code_found(repo):
    result = await repo.get_by_code("ru")
    assert result is not None
    assert result.name_native == "Русский"


@pytest.mark.asyncio()
async def test_get_by_code_not_found(repo):
    result = await repo.get_by_code("zz")
    assert result is None


@pytest.mark.asyncio()
async def test_get_by_code_disabled_returns_entity(repo):
    # get_by_code returns regardless of enabled status
    result = await repo.get_by_code("xx")
    assert result is not None
    assert result.enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_language_repository.py -v
```

Expected: `ImportError` — `MemoryLanguageRepository` not defined yet.

- [ ] **Step 3: Add `LanguageRepository` ABC to `ports.py`**

In `src/ugc_bot/application/ports.py`, add after `CountryRepository`:

```python
class LanguageRepository(ABC):
    """Port for language persistence."""

    @abstractmethod
    async def list_enabled(
        self, session: object | None = None
    ) -> list[Language]:
        """List enabled languages."""
        ...

    @abstractmethod
    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Language]:
        """Fetch language by code."""
        ...
```

Add `Language` to the import from `ugc_bot.domain.entities` at the top of `ports.py`.

- [ ] **Step 4: Add `MemoryLanguageRepository` to `memory_repositories.py`**

In `src/ugc_bot/infrastructure/memory_repositories.py`, add after `MemoryCountryRepository`:

```python
@dataclass
class MemoryLanguageRepository(LanguageRepository):
    """In-memory LanguageRepository for testing."""

    languages: Dict[str, Language] = field(default_factory=dict)

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Language]:
        """List enabled languages."""
        return [l for l in self.languages.values() if l.enabled]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Language]:
        """Fetch language by code."""
        return self.languages.get(code)
```

Add `Language` to the import from `ugc_bot.domain.entities` in `memory_repositories.py`.

- [ ] **Step 5: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_language_repository.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Add `SqlAlchemyLanguageRepository` to `repositories.py`**

In `src/ugc_bot/infrastructure/db/repositories.py`, add after `SqlAlchemyCountryRepository`:

```python
def _to_language_entity(model: "LanguageModel") -> Language:
    """Map language ORM model to domain entity."""
    return Language(
        code=model.code,
        name_native=model.name_native,
        enabled=model.enabled,
    )


@dataclass(slots=True)
class SqlAlchemyLanguageRepository(LanguageRepository):
    """SQLAlchemy implementation of LanguageRepository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def list_enabled(
        self, session: object | None = None
    ) -> list[Language]:
        """List enabled languages."""
        stmt = select(LanguageModel).where(LanguageModel.enabled.is_(True))
        exec_result = await _execute_stmt(stmt, session, self.session_factory)
        return [_to_language_entity(row) for row in exec_result.scalars().all()]

    async def get_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[Language]:
        """Fetch language by code."""
        stmt = select(LanguageModel).where(LanguageModel.code == code)
        exec_result = await _execute_stmt(stmt, session, self.session_factory)
        result = exec_result.scalar_one_or_none()
        return _to_language_entity(result) if result else None
```

Add `LanguageModel` and `Language` to the imports in `repositories.py`.

- [ ] **Step 7: Add fake to `tests/helpers/fakes.py`**

At the bottom of `tests/helpers/fakes.py`, add:

```python
from ugc_bot.domain.entities import Language
from ugc_bot.infrastructure.memory_repositories import MemoryLanguageRepository


def make_language_repo(*languages: Language) -> MemoryLanguageRepository:
    """Build a MemoryLanguageRepository from given Language instances."""
    return MemoryLanguageRepository(
        languages={lang.code: lang for lang in languages}
    )
```

- [ ] **Step 8: Run tests + typecheck**

```bash
make fix
```

Expected: all tests pass, no type errors.

- [ ] **Step 9: Commit**

```bash
git add src/ugc_bot/application/ports.py \
        src/ugc_bot/infrastructure/db/repositories.py \
        src/ugc_bot/infrastructure/memory_repositories.py \
        tests/unit/test_language_repository.py \
        tests/helpers/fakes.py
git commit -m "feat: add LanguageRepository port, SQLAlchemy and memory implementations"
```

---

### Task 5: `UserRoleService.set_language()`

**Files:**
- Modify: `src/ugc_bot/application/services/user_role_service.py`
- Modify: `tests/application/services/test_user_role_service.py`

- [ ] **Step 1: Write failing test**

Follow the same inline pattern as `test_set_country_updates_user` in `tests/application/services/test_user_role_service.py`. Add:

```python
@pytest.mark.asyncio()
async def test_set_language_updates_user():
    """set_language() persists user.language."""
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryUserRepository,
    )
    user_repo = InMemoryUserRepository()
    service = UserRoleService(user_repo=user_repo)
    await service.set_user(
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        username="tester",
        role_chosen=False,
    )
    await service.set_language(
        external_id="111",
        messenger_type=MessengerType.TELEGRAM,
        language_code="en",
    )
    result = await service.get_user("111", MessengerType.TELEGRAM)
    assert result is not None
    assert result.language == "en"
```

Run:
```bash
uv run pytest tests/application/services/test_user_role_service.py::test_set_language_updates_user -v
```

Expected: FAIL — `set_language` not defined.

- [ ] **Step 2: Implement `set_language()`**

In `src/ugc_bot/application/services/user_role_service.py`, add after `set_country()`:

```python
async def set_language(
    self,
    external_id: str,
    messenger_type: MessengerType,
    language_code: str,
) -> User:
    """Set language for a user identified by external_id."""

    async def _run(session: object | None) -> User:
        user = await self.user_repo.get_by_external(
            external_id, messenger_type, session=session
        )
        if user is None:
            raise UserNotFoundError("User not found.")
        updated = replace(user, language=language_code)
        await self.user_repo.save(updated, session=session)
        return updated

    return await with_optional_tx(self.transaction_manager, _run)
```

- [ ] **Step 3: Run test to verify it passes**

```bash
uv run pytest tests/application/services/test_user_role_service.py::test_set_language_updates_user -v
```

Expected: PASS.

- [ ] **Step 4: Run make fix**

```bash
make fix
```

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/user_role_service.py \
        tests/application/services/test_user_role_service.py
git commit -m "feat: add UserRoleService.set_language()"
```

---

### Task 6: Update `LocaleMiddleware` + `miniapp/api.py::_get_user_locale`

**Files:**
- Modify: `src/ugc_bot/bot/middleware/locale.py`
- Modify: `src/ugc_bot/miniapp/api.py`
- Modify: `tests/unit/bot/middleware/test_locale.py`

- [ ] **Step 1: Remove old locale tests that test `country.locale` resolution**

Two test files contain tests for the old `country.locale` path that must be cleaned up:

**`tests/unit/bot/middleware/test_locale.py`** — contains tests like `test_user_and_country_found_returns_country_locale`, `test_no_country_repo_returns_default`. Run:
```bash
grep -n "def test_" tests/unit/bot/middleware/test_locale.py
```
Remove any test that passes `country_repo` or asserts on `country.locale`.

**`tests/unit/miniapp/test_get_user_locale.py`** — contains `_make_country()` helper that calls `Country(..., locale=...)` (broken after Task 1), and `test_user_and_country_found_returns_country_locale` (tests removed behavior). Run:
```bash
grep -n "def test_\|_make_country\|locale" tests/unit/miniapp/test_get_user_locale.py
```
Remove `_make_country()`, remove any test that passes `country_repo` to dispatcher or asserts on `country.locale` resolution. Write replacement tests for the `user.language`-based behavior in both files.

- [ ] **Step 2: Write failing tests for updated middleware**

First read `tests/unit/bot/middleware/test_locale.py` to understand the existing stub pattern, then add tests that use the same approach:

```python
# Use the same stub/helper already in test_locale.py.
# Key assertions needed:
# 1. user with language="en" → locale == "en"
# 2. user with language=None → locale == default_locale
# 3. no user found → locale == default_locale
```

Run:
```bash
uv run pytest tests/unit/bot/middleware/test_locale.py -v
```

Expected: new tests FAIL (middleware still reads country.locale).

- [ ] **Step 4: Update `LocaleMiddleware._resolve()`**

Replace the body of `_resolve` in `src/ugc_bot/bot/middleware/locale.py`:

```python
@staticmethod
async def _resolve(data: dict[str, Any]) -> str:
    """Resolve locale from user.language, falling back to default."""
    default: str = data.get("default_locale") or "ru"
    user_role_service = data.get("user_role_service")
    if not user_role_service:
        return default
    tg_user = data.get("event_from_user")
    if tg_user is None:
        return default
    external_id = str(tg_user.id)
    user = await user_role_service.get_user(
        external_id, MessengerType.TELEGRAM
    )
    if not user or not user.language:
        return default
    return user.language
```

Remove the import of `CountryRepository` from this file (no longer needed).

- [ ] **Step 5: Update `miniapp/api.py::_get_user_locale`**

Replace the body of `_get_user_locale` in `src/ugc_bot/miniapp/api.py`:

```python
async def _get_user_locale(request: Request, external_id: str) -> str:
    """Resolve locale for user by external_id via user.language."""
    config = request.app.state.config
    default: str = config.market.default_locale
    dispatcher = request.app.state.dispatcher
    user_role_service = dispatcher.get("user_role_service")
    if not user_role_service:
        return default
    try:
        user = await user_role_service.get_user(
            external_id, MessengerType.TELEGRAM
        )
    except Exception:
        logger.warning("Failed to resolve locale for user %s", external_id)
        return default
    if not user or not user.language:
        return default
    return user.language
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/bot/middleware/test_locale.py -v
make fix
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/bot/middleware/locale.py \
        src/ugc_bot/miniapp/api.py \
        tests/unit/bot/middleware/test_locale.py
git commit -m "feat: LocaleMiddleware uses user.language; update miniapp _get_user_locale"
```

---

### Task 7: Wire `LanguageRepository` in service factory

**Files:**
- Modify: `src/ugc_bot/container/service_factory.py`

- [ ] **Step 1: Add `LanguageRepository` to repos dict**

In `src/ugc_bot/container/service_factory.py`, find where `country_repo` is built (look for `SqlAlchemyCountryRepository`) and add alongside it:

```python
"language_repo": SqlAlchemyLanguageRepository(
    session_factory=session_factory
),
```

Add `SqlAlchemyLanguageRepository` and `LanguageRepository` to the imports.

- [ ] **Step 2: Add `language_repo` to dispatcher data**

In `build_dispatcher_data()`, add:

```python
"language_repo": repos["language_repo"],
```

- [ ] **Step 3: Run typecheck + tests**

```bash
make fix
```

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/container/service_factory.py
git commit -m "feat: wire LanguageRepository into dispatcher data"
```

---

## Chunk 2: Bot Flow — Language Selection

### Task 8: Language keyboard + CALLBACK_LANG_PREFIX

**Files:**
- Modify: `src/ugc_bot/bot/handlers/keyboards.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/bot/test_language_keyboard.py`:

```python
"""Tests for language_inline_keyboard."""

import pytest
from ugc_bot.domain.entities import Language
from ugc_bot.bot.handlers.keyboards import (
    language_inline_keyboard,
    CALLBACK_LANG_PREFIX,
)
from ugc_bot.application.messenger.dto import KeyboardKind


def test_language_keyboard_builds_buttons():
    languages = [
        Language(code="ru", name_native="Русский"),
        Language(code="en", name_native="English"),
    ]
    kb = language_inline_keyboard(languages)
    assert kb.kind == KeyboardKind.INLINE
    assert len(kb.rows) == 1  # 2 per row, 2 languages = 1 row
    assert kb.rows[0][0].callback_data == f"{CALLBACK_LANG_PREFIX}ru"
    assert kb.rows[0][1].callback_data == f"{CALLBACK_LANG_PREFIX}en"
    assert kb.rows[0][0].text == "Русский"


def test_language_keyboard_empty_returns_empty():
    kb = language_inline_keyboard([])
    assert kb.rows == []
```

Run:
```bash
uv run pytest tests/unit/bot/test_language_keyboard.py -v
```

Expected: FAIL — `language_inline_keyboard` not defined.

- [ ] **Step 2: Add `CALLBACK_LANG_PREFIX` and `language_inline_keyboard`**

In `src/ugc_bot/bot/handlers/keyboards.py`, add:

```python
CALLBACK_LANG_PREFIX = "lang:"
```

And the function (mirror of `country_inline_keyboard`):

```python
def language_inline_keyboard(languages: "list[Language]") -> Keyboard:
    """Inline keyboard with language buttons (2 per row).

    Button text: name_native. Callback: lang:<code>
    """
    if TYPE_CHECKING:
        from ugc_bot.domain.entities import Language  # noqa: F401

    buttons = [
        Button(
            text=lang.name_native,
            callback_data=f"{CALLBACK_LANG_PREFIX}{lang.code}",
        )
        for lang in languages
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)
```

Add `Language` to the `TYPE_CHECKING` block at the top of the file.

- [ ] **Step 3: Run test to verify it passes**

```bash
uv run pytest tests/unit/bot/test_language_keyboard.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/bot/handlers/keyboards.py \
        tests/unit/bot/test_language_keyboard.py
git commit -m "feat: add language_inline_keyboard and CALLBACK_LANG_PREFIX"
```

---

### Task 9: `/start` language step + `lang:` callback + `/language` command

**Files:**
- Modify: `src/ugc_bot/bot/handlers/start.py`

- [ ] **Step 1: Write failing tests for the updated `_start_command`**

First, look at the existing start handler tests in the codebase:
```bash
find tests/ -name "test_start*" -o -name "*start*test*" 2>/dev/null
```

Create `tests/unit/bot/test_start_handler_language.py` following the same testing patterns used in the existing start handler tests. The key behaviors to test:

```python
"""Tests for language selection step in /start flow."""
# Test 1: user with language=None and tg_language_code not in available_language_codes
#   → should send language_prompt text with language_kb keyboard
#
# Test 2: user with language=None and tg_language_code="ru" in {"ru", "en"}
#   → should call user_role_service.set_language(language_code="ru")
#   → should NOT show language keyboard (auto-detected)
#
# Test 3: user with language="en" but country=None
#   → should skip language step, show country_prompt
#
# Pattern: use FakeMessengerClient from tests/helpers/fakes.py
# Create a minimal inline UserRoleService stub (SimpleNamespace or dataclass)
# that implements get_user(), set_user(), set_language()
# Use MemoryUserRepository + UserRoleService directly when practical
```

**Important:** The `_start_command` internal function must be updated in step 2 before the tests can pass. Write the tests first to define the expected behavior, then implement.

Run:
```bash
uv run pytest tests/unit/bot/test_start_handler_language.py -v
```

Expected: FAIL — `_start_command` doesn't accept new params yet.

- [ ] **Step 2: Update `start_command` handler (the aiogram router handler)**

In `src/ugc_bot/bot/handlers/start.py`, add imports:

```python
from ugc_bot.application.ports import LanguageRepository
from ugc_bot.bot.handlers.keyboards import (
    CALLBACK_LANG_PREFIX,
    language_inline_keyboard,
    ...  # existing imports
)
```

Update `start_command` handler signature to also accept `language_repo`:

```python
@router.message(CommandStart())
async def start_command(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    country_repo: CountryRepository | None = None,
    language_repo: LanguageRepository | None = None,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
```

Inside `start_command`, add language prompt fetching:

```python
language_prompt = (
    await bot_texts_service.get("language_prompt", user_locale)
).strip() or "Выберите язык / Choose language:"
languages = await language_repo.list_enabled() if language_repo else []
available_language_codes = {lang.code for lang in languages}
```

Pass to `_start_command`:

```python
await _start_command(
    ...
    language_prompt=language_prompt,
    language_kb=language_inline_keyboard(languages),
    available_language_codes=available_language_codes,
)
```

- [ ] **Step 3: Update `_start_command` internal function**

Replace `_start_command` signature and body:

```python
async def _start_command(
    *,
    incoming: IncomingMessage,
    state_store: StateStore,
    messenger_client: MessengerClient,
    user_role_service: UserRoleService,
    referral_service: ReferralService,
    start_text: str,
    role_kb: Keyboard,
    language_prompt: str = "Выберите язык / Choose language:",
    language_kb: Keyboard | None = None,
    available_language_codes: set[str] | None = None,
    country_prompt: str = "Выберите вашу страну:",
    country_kb: Keyboard | None = None,
) -> None:
    """Handle /start: language → country → role."""
    if not incoming.user.external_id:
        return
    await state_store.clear()
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    username = user.username if user else ""
    user = await user_role_service.set_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        username=username,
        role_chosen=False,
        telegram_username=incoming.user.username,
    )
    referral_code = referral_service.parse_referral_code(incoming.text)
    if referral_code:
        await referral_service.save_pending_referral(
            user.user_id, referral_code
        )
    # Step 1: Language
    if user.language is None:
        tg_lang = getattr(incoming, "language_code", None) or ""
        if tg_lang and available_language_codes and tg_lang in available_language_codes:
            await user_role_service.set_language(
                external_id=incoming.user.external_id,
                messenger_type=incoming.user.messenger_type,
                language_code=tg_lang,
            )
            # re-fetch to get updated user
            user = await user_role_service.get_user(
                incoming.user.external_id, incoming.user.messenger_type
            )
        elif language_kb is not None and language_kb.rows:
            await messenger_client.send_text(
                chat_id=incoming.chat_id,
                text=language_prompt,
                keyboard=language_kb,
            )
            return
    # Step 2: Country
    if user.country is None and country_kb is not None and country_kb.rows:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=country_prompt,
            keyboard=country_kb,
        )
        return
    # Step 3: Role
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_kb,
    )
```

**Note:** `IncomingMessage` needs a `language_code` field. Check `application/messenger/dto.py` — if it doesn't exist, add `language_code: str = ""` to `IncomingMessage` and populate it in `TelegramEventAdapter.from_message()` from `message.from_user.language_code`.

- [ ] **Step 4: Add `lang:` callback handler**

In `start.py`, add after `country_selected`:

```python
@router.callback_query(lambda c: c.data.startswith(CALLBACK_LANG_PREFIX))
async def language_selected(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    country_repo: CountryRepository | None = None,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle language selection — save language, proceed to country or role."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    await messenger_client.answer_callback(callback_id=incoming.callback_id)
    language_code = (callback.data or "").removeprefix(CALLBACK_LANG_PREFIX)
    if not language_code:
        return
    await user_role_service.set_language(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
        language_code=language_code,
    )
    # Reload user to check country
    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    # Use the newly selected language for the next prompt
    new_locale = language_code
    if incoming.message_id:
        await messenger_client.edit_reply_markup(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            keyboard=None,
        )
    if user and user.country is None and country_repo:
        countries = await country_repo.list_enabled()
        country_prompt = (
            await bot_texts_service.get("country_prompt", new_locale)
        ).strip() or "Выберите вашу страну:"
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=country_prompt,
            keyboard=country_inline_keyboard(countries),
        )
        return
    start_text = (
        await bot_texts_service.get("start_message", new_locale)
    ).strip() or "UMC — сервис для UGC."
    texts = await bot_texts_service.get_many(
        ["btn_creator", "btn_advertiser", "btn_support"], new_locale
    )
    await AiogramStateStore(state).clear()
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=start_text,
        keyboard=role_inline_keyboard(texts),
    )
```

- [ ] **Step 5: Add `/language` command handler**

```python
@router.message(Command("language"))
async def language_command(
    message: Message,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    language_repo: LanguageRepository | None = None,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /language — show language selection keyboard."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    languages = await language_repo.list_enabled() if language_repo else []
    language_prompt = (
        await bot_texts_service.get("language_prompt", user_locale)
    ).strip() or "Выберите язык / Choose language:"
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=language_prompt,
        keyboard=language_inline_keyboard(languages),
    )
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/bot/test_start_handler_language.py -v
make test
```

- [ ] **Step 7: Run make fix**

```bash
make fix
```

- [ ] **Step 8: Commit**

```bash
git add src/ugc_bot/bot/handlers/start.py \
        src/ugc_bot/application/messenger/dto.py \
        src/ugc_bot/infrastructure/messenger/telegram/adapter.py \
        tests/unit/bot/test_start_handler_language.py
git commit -m "feat: add language selection step to /start, lang: callback, /language command"
```

---

### Task 10: Bot texts — add new keys, replace hardcoded currency names

**Files:**
- Modify: `src/ugc_bot/bot/texts/defaults.py`

- [ ] **Step 1: Replace hardcoded currency names in `DEFAULT_TEXTS["ru"]`**

Find and replace in `src/ugc_bot/bot/texts/defaults.py`:

| Old | New |
|-----|-----|
| `"Укажите цену за 1 UGC‑видео в рублях:"` | `"Укажите цену за 1 UGC‑видео ({currency}):"` |
| `"...Цена в рублях, например: 500, 1000, 2000..."` | `"...Цена ({currency}), например: 500, 1000, 2000..."` |
| `"Бюджет за 1 UGC-видео? Укажите цену в рублях: 500, 1000, 2000"` | `"Бюджет за 1 UGC-видео? Укажите цену ({currency}): 500, 1000, 2000"` |

- [ ] **Step 2: Add new localization keys to `DEFAULT_TEXTS["ru"]` and `DEFAULT_TEXTS["en"]`**

Add to `"ru"` section:

```python
# Language selection
"language_prompt": "Выберите язык / Choose language:",
"btn_change_language": "🌐 Изменить язык",
"language_changed": "Язык изменён.",
# Offer texts (from offer_dispatch_service)
"offer_header": "Новый заказ",
"offer_details_header": "📋 Детали заказа:",
"offer_format": "🎥 Формат: {format_label}",
"offer_task": "📝 Задача: {task}",
"offer_budget": "💰 Бюджет: {price} {currency} за 1 UGC-видео",
"offer_barter": "🎁 Бартер: {description}",
"offer_content_usage": "📢 Использование: {usage}",
"offer_deadlines": "⏱ Сроки: {deadlines}",
"offer_geography": "📍 География: {geography}",
"offer_bloggers_needed": "👥 Нужно креаторов: {count}",
"offer_warning": (
    "⚠️ Важно\n"
    "🧷 Откликайтесь только если готовы работать на указанных условиях\n"
    "❗ Отказ после отклика без изменения условий со стороны заказчика"
    "   может привести к жалобе и ограничению аккаунта"
),
"offer_how_it_works": (
    "⏳ Как это работает\n"
    "● Вы откликаетесь на оффер\n"
    "● Получаете ссылку на продукт\n"
    "● Заказчик получает ваш профиль и пишет вам первым\n"
    "● Платформа не участвует в переговорах и оплате"
),
"offer_format_label_ugc_placement": "UGC + размещение",
"offer_format_label_ugc_only": "UGC-видео для бренда",
"btn_offer_accept": "Готов снять UGC",
"btn_offer_skip": "Пропустить",
# Complaint button
"btn_complaint": "Пожаловаться на {name}",
```

Add equivalent English translations to `"en"` section.

- [ ] **Step 3: Run tests**

```bash
make test
```

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/bot/texts/defaults.py
git commit -m "feat: add language/offer/complaint bot_text keys; replace hardcoded currency names"
```

---

## Chunk 3: Service Localization

### Task 11: Localize `OfferDispatchService.format_offer()` + `kafka_consumer.py`

**Files:**
- Modify: `src/ugc_bot/application/services/offer_dispatch_service.py`
- Modify: `src/ugc_bot/kafka_consumer.py`
- Modify: `tests/application/services/test_offer_dispatch_service.py`

- [ ] **Step 1: Write failing test for localized `format_offer()`**

In `tests/application/services/test_offer_dispatch_service.py`, add:

```python
@pytest.mark.asyncio()
async def test_format_offer_uses_locale(offer_dispatch_service, sample_order):
    """format_offer uses provided locale to fetch texts."""
    bot_texts_service = FakeBotTextsService(locale="en")
    result = await offer_dispatch_service.format_offer(
        order=sample_order,
        advertiser_status="ACTIVE",
        locale="en",
        bot_texts_service=bot_texts_service,
    )
    assert "New order" in result or "Новый заказ" in result  # depends on fake
```

Run:
```bash
uv run pytest tests/application/services/test_offer_dispatch_service.py::test_format_offer_uses_locale -v
```

Expected: FAIL — `format_offer` doesn't accept `locale` yet.

- [ ] **Step 2: Update `format_offer()` signature and body**

In `src/ugc_bot/application/services/offer_dispatch_service.py`, update `format_offer`:

```python
async def format_offer(
    self,
    order: Order,
    advertiser_status: str,
    locale: str = "ru",
    bot_texts_service: object | None = None,
    session: object | None = None,
) -> str:
    """Format offer text for a blogger using localized texts."""
    currency_symbol = self.currency_symbol
    if self.country_repo is not None:
        country = await self.country_repo.get_by_currency_code(
            order.currency, session=session
        )
        if country is not None:
            currency_symbol = country.currency_symbol

    # Fetch localized texts
    texts: dict[str, str] = {}
    if bot_texts_service is not None:
        keys = [
            "offer_header", "offer_details_header", "offer_format",
            "offer_task", "offer_budget", "offer_barter",
            "offer_content_usage", "offer_deadlines", "offer_geography",
            "offer_bloggers_needed", "offer_warning", "offer_how_it_works",
            "offer_format_label_ugc_placement", "offer_format_label_ugc_only",
        ]
        texts = await bot_texts_service.get_many(keys, locale)

    def t(key: str, default: str) -> str:
        return texts.get(key) or default

    format_label = (
        t("offer_format_label_ugc_placement", "UGC + размещение")
        if order.order_type.value == "ugc_plus_placement"
        else t("offer_format_label_ugc_only", "UGC-видео для бренда")
    )

    parts = [
        t("offer_header", "Новый заказ"),
        "",
        t("offer_details_header", "📋 Детали заказа:"),
        t("offer_format", "🎥 Формат: {format_label}").format(
            format_label=format_label
        ),
        t("offer_task", "📝 Задача: {task}").format(task=order.offer_text),
    ]
    if order.price > 0:
        parts.append(
            t("offer_budget", "💰 Бюджет: {price} {currency} за 1 UGC-видео").format(
                price=order.price, currency=currency_symbol
            )
        )
    if order.barter_description:
        parts.append(
            t("offer_barter", "🎁 Бартер: {description}").format(
                description=order.barter_description
            )
        )
    if order.content_usage:
        parts.append(
            t("offer_content_usage", "📢 Использование: {usage}").format(
                usage=order.content_usage
            )
        )
    if order.deadlines:
        parts.append(
            t("offer_deadlines", "⏱ Сроки: {deadlines}").format(
                deadlines=order.deadlines
            )
        )
    if order.geography:
        parts.append(
            t("offer_geography", "📍 География: {geography}").format(
                geography=order.geography
            )
        )
    parts.append(
        t("offer_bloggers_needed", "👥 Нужно креаторов: {count}").format(
            count=order.bloggers_needed
        )
    )
    parts.append("")
    parts.append(
        t(
            "offer_warning",
            "⚠️ Важно\n🧷 Откликайтесь только если готовы работать на указанных условиях",
        )
    )
    parts.append("")
    parts.append(
        t(
            "offer_how_it_works",
            "⏳ Как это работает\n● Вы откликаетесь на оффер",
        )
    )
    return "\n".join(parts)
```

- [ ] **Step 3: Update `kafka_consumer.py::_send_offer_to_blogger`**

Update the function to accept and pass locale + bot_texts_service:

```python
async def _send_offer_to_blogger(
    blogger: User,
    order: Order,
    advertisers_status: str,
    messenger_client: MessengerClient,
    offer_dispatch_service: OfferDispatchService,
    retries: int,
    retry_delay_seconds: float,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    locale: str = "ru",
    bot_texts_service: object | None = None,
) -> None:
```

Inside the retry loop, add locale-aware button texts and pass locale to `format_offer`:

```python
offer_text = await offer_dispatch_service.format_offer(
    order, advertisers_status, locale=locale, bot_texts_service=bot_texts_service
)
btn_accept = "Готов снять UGC"
btn_skip = "Пропустить"
if bot_texts_service is not None:
    txts = await bot_texts_service.get_many(
        ["btn_offer_accept", "btn_offer_skip"], locale
    )
    btn_accept = txts.get("btn_offer_accept") or btn_accept
    btn_skip = txts.get("btn_offer_skip") or btn_skip
reply_markup = Keyboard(
    kind=KeyboardKind.INLINE,
    rows=[
        [Button(text=btn_accept, callback_data=f"offer:{order.order_id}")],
        [Button(text=btn_skip, callback_data=f"offer_skip:{order.order_id}")],
    ],
)
```

Update `_send_offers` to load blogger locale from `user_role_service` and pass it:

```python
async def _send_offers(
    order_id: UUID,
    messenger_client: MessengerClient,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
    user_role_service: object | None = None,
    bot_texts_service: object | None = None,
    default_locale: str = "ru",
) -> None:
    ...
    for blogger in bloggers:
        locale = default_locale
        if user_role_service is not None and blogger.language:
            locale = blogger.language
        await _send_offer_to_blogger(
            ...,
            locale=locale,
            bot_texts_service=bot_texts_service,
        )
```

Pass `user_role_service` and `bot_texts_service` from `_consume_forever` via `run_consumer`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/application/services/test_offer_dispatch_service.py -v
uv run pytest tests/unit/test_kafka_consumer.py -v
make fix
```

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/offer_dispatch_service.py \
        src/ugc_bot/kafka_consumer.py \
        tests/application/services/test_offer_dispatch_service.py
git commit -m "feat: localize format_offer() and kafka_consumer offer buttons"
```

---

### Task 12: Localize `feedback_scheduler.py`

**Files:**
- Modify: `src/ugc_bot/feedback_scheduler.py`
- Modify: `tests/scheduler/test_feedback_scheduler.py`

- [ ] **Step 1: Write failing test**

In `tests/scheduler/test_feedback_scheduler.py`, add:

```python
@pytest.mark.asyncio()
async def test_feedback_message_uses_user_locale():
    """Feedback scheduler sends message in user's language."""
    # Create user with language="en"
    # Verify feedback message uses English texts
    ...
```

Run:
```bash
uv run pytest tests/scheduler/test_feedback_scheduler.py::test_feedback_message_uses_user_locale -v
```

Expected: FAIL.

- [ ] **Step 2: Update `feedback_scheduler.py` to use `bot_texts_service` with user locale**

Find where `_feedback_keyboard` and the feedback message are built. Replace:

```python
# Before: uses DEFAULT_TEXTS["ru"] hardcoded
texts = DEFAULT_TEXTS.get("ru", {})
```

After: accept `bot_texts_service` and load with `user.language`:

```python
locale = getattr(user, "language", None) or default_locale
texts = await bot_texts_service.get_many(feedback_text_keys, locale)
```

Propagate `bot_texts_service` from the container through the scheduler setup in `run_feedback_scheduler()`.

- [ ] **Step 3: Run tests**

```bash
uv run pytest tests/scheduler/test_feedback_scheduler.py -v
make fix
```

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/feedback_scheduler.py \
        tests/scheduler/test_feedback_scheduler.py
git commit -m "feat: localize feedback_scheduler — use user.language for feedback messages"
```

---

### Task 13: Localize `complaints.py` and `offer_responses.py`

**Files:**
- Modify: `src/ugc_bot/bot/handlers/complaints.py`
- Modify: `src/ugc_bot/bot/handlers/offer_responses.py`

- [ ] **Step 1: Fix `complaints.py` — replace hardcoded button text**

In `src/ugc_bot/bot/handlers/complaints.py`, find:

```python
text="Пожаловаться на {blogger_name}",
```

Replace with a lookup via `bot_texts_service`:

```python
btn_complaint_tpl = (
    await bot_texts_service.get("btn_complaint", user_locale)
).strip() or "Пожаловаться на {name}"
text=btn_complaint_tpl.format(name=blogger_name),
```

The handler must already receive `bot_texts_service` and `user_locale` — check if it does; add them to the signature if not.

- [ ] **Step 2: Fix `offer_responses.py` — replace hardcoded order type labels**

In `src/ugc_bot/bot/handlers/offer_responses.py`, find the two occurrences:

```python
"UGC + размещение"
"UGC-видео для бренда"
```

Replace with:

```python
texts = await bot_texts_service.get_many(
    ["offer_format_label_ugc_placement", "offer_format_label_ugc_only"],
    user_locale,
)
format_label = (
    texts.get("offer_format_label_ugc_placement", "UGC + размещение")
    if order.order_type.value == "ugc_plus_placement"
    else texts.get("offer_format_label_ugc_only", "UGC-видео для бренда")
)
```

- [ ] **Step 3: Run full suite**

```bash
make fix
```

Expected: all tests pass, coverage ≥ 98%, no type errors.

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/bot/handlers/complaints.py \
        src/ugc_bot/bot/handlers/offer_responses.py
git commit -m "feat: localize complaint button and offer response type labels"
```

---

### Task 14: Admin panel — register `LanguageModel`

**Files:**
- Modify: `src/ugc_bot/admin/app.py` (or wherever `CountryAdmin` is registered)

- [ ] **Step 1: Find where `CountryAdmin` is registered**

```bash
grep -rn "CountryAdmin\|CountryModel" src/ugc_bot/admin/
```

- [ ] **Step 2: Add `LanguageAdmin` view**

Add alongside `CountryAdmin`:

```python
class LanguageAdmin(ModelView, model=LanguageModel):
    column_list = [LanguageModel.code, LanguageModel.name_native, LanguageModel.enabled]
    name = "Language"
    name_plural = "Languages"
    icon = "fa-solid fa-language"
```

Register it in the admin app.

- [ ] **Step 3: Run admin tests**

```bash
uv run pytest tests/admin/ -v
make fix
```

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/admin/
git commit -m "feat: add LanguageAdmin view to admin panel"
```

---

### Task 15: Final verification

- [ ] **Step 1: Run full test suite with coverage**

```bash
make all
```

Expected: format-check PASS, lint PASS, typecheck PASS, coverage ≥ 98%.

- [ ] **Step 2: Run migration on clean DB**

```bash
make migrate
```

Verify with:
```bash
psql $DATABASE_URL -c "\\d languages; SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='language';"
```

- [ ] **Step 3: Manual smoke test (local polling bot)**

```bash
python -m ugc_bot.app
```

Send `/start` to the bot — verify:
1. Language keyboard appears for new user
2. Selecting language proceeds to country keyboard
3. Selecting country proceeds to role keyboard
4. `/language` command shows keyboard to existing user

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "feat: complete language/country/currency selection feature"
```
