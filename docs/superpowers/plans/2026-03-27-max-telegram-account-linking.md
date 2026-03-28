# Max-Telegram Account Linking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow creators migrating from Telegram to Max to keep their existing profile by linking accounts via verified Instagram URL.

**Architecture:** New `link_max_account` method in `UserRoleService` that finds an existing user by Instagram URL (via `BloggerProfileRepository`) and attaches `max_id` to that user. Max registration handler calls this after Instagram verification; if linked, skips remaining registration.

**Tech Stack:** Python, aiogram patterns, SQLAlchemy, Redis FSM, pytest with in-memory fakes

---

### Task 1: Add `link_max_account` to `UserRoleService`

**Files:**
- Modify: `src/ugc_bot/application/services/user_role_service.py`
- Test: `tests/application/services/test_user_role_service.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/application/services/test_user_role_service.py`:

```python
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerProfileRepository,
    InMemoryUserRepository,
)
from ugc_bot.domain.entities import BloggerProfile, User


@pytest.mark.asyncio
async def test_link_max_account_success() -> None:
    """Link max_id to existing Telegram user found by instagram_url."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    existing_user = User(
        user_id=uuid4(),
        telegram_id="tg_111",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(existing_user)
    await blogger_repo.save(
        BloggerProfile(
            user_id=existing_user.user_id,
            instagram_url="https://instagram.com/alice",
            confirmed=True,
            city="Moscow",
        )
    )

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    linked = await service.link_max_account(
        max_id="max_222",
        instagram_url="https://instagram.com/alice",
        username="alice_max",
    )

    assert linked is not None
    assert linked.user_id == existing_user.user_id
    assert linked.max_id == "max_222"
    assert linked.telegram_id == "tg_111"
    assert linked.messenger_type == MessengerType.MAX
    assert linked.username == "alice_max"


@pytest.mark.asyncio
async def test_link_max_account_not_found() -> None:
    """Return None when instagram_url not in DB."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    result = await service.link_max_account(
        max_id="max_333",
        instagram_url="https://instagram.com/unknown",
        username="nobody",
    )

    assert result is None


@pytest.mark.asyncio
async def test_link_max_account_already_has_max_id() -> None:
    """Return None when user already has a different max_id."""
    user_repo = InMemoryUserRepository()
    blogger_repo = InMemoryBloggerProfileRepository()

    existing_user = User(
        user_id=uuid4(),
        telegram_id="tg_111",
        max_id="max_existing",
        messenger_type=MessengerType.MAX,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(existing_user)
    await blogger_repo.save(
        BloggerProfile(
            user_id=existing_user.user_id,
            instagram_url="https://instagram.com/alice",
            confirmed=True,
            city="Moscow",
        )
    )

    service = UserRoleService(
        user_repo=user_repo,
        blogger_profile_repo=blogger_repo,
    )
    result = await service.link_max_account(
        max_id="max_new",
        instagram_url="https://instagram.com/alice",
        username="alice_max",
    )

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/application/services/test_user_role_service.py::test_link_max_account_success tests/application/services/test_user_role_service.py::test_link_max_account_not_found tests/application/services/test_user_role_service.py::test_link_max_account_already_has_max_id -v`
Expected: FAIL — `UserRoleService.__init__` does not accept `blogger_profile_repo`

- [ ] **Step 3: Add `blogger_profile_repo` dependency and `link_max_account` method**

Edit `src/ugc_bot/application/services/user_role_service.py`:

1. Add import:
```python
from ugc_bot.application.ports import BloggerProfileRepository, TransactionManager, UserRepository
```

2. Add field to `UserRoleService` dataclass (after `transaction_manager`):
```python
blogger_profile_repo: BloggerProfileRepository | None = None
```

3. Add method at the end of the class:
```python
async def link_max_account(
    self,
    max_id: str,
    instagram_url: str,
    username: str,
) -> User | None:
    """Link a Max messenger account to an existing user found by Instagram URL.

    Returns the updated User if linked, None if no matching user found
    or user already has a different max_id.
    """

    async def _run(session: object | None) -> User | None:
        if self.blogger_profile_repo is None:
            return None
        profile = await self.blogger_profile_repo.get_by_instagram_url(
            instagram_url, session=session
        )
        if profile is None:
            return None

        existing = await self.user_repo.get_by_id(
            profile.user_id, session=session
        )
        if existing is None:
            return None

        if existing.max_id is not None and existing.max_id != max_id:
            return None

        updated = replace(
            existing,
            max_id=max_id,
            messenger_type=MessengerType.MAX,
            username=username,
        )
        await self.user_repo.save(updated, session=session)
        return updated

    return await with_optional_tx(self.transaction_manager, _run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/services/test_user_role_service.py::test_link_max_account_success tests/application/services/test_user_role_service.py::test_link_max_account_not_found tests/application/services/test_user_role_service.py::test_link_max_account_already_has_max_id -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest tests/application/services/test_user_role_service.py -v`
Expected: All existing tests still pass (existing `UserRoleService` tests don't pass `blogger_profile_repo`, which is `None` by default)

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/application/services/user_role_service.py tests/application/services/test_user_role_service.py
git commit -m "feat: add link_max_account method to UserRoleService"
```

---

### Task 2: Wire `blogger_profile_repo` into `UserRoleService` in container

**Files:**
- Modify: `src/ugc_bot/container/service_factory.py`

- [ ] **Step 1: Add `blogger_profile_repo` to `UserRoleService` construction in `build_bot_services`**

In `src/ugc_bot/container/service_factory.py`, find the `UserRoleService` construction inside `build_bot_services` (around line 380):

```python
"user_role_service": UserRoleService(
    user_repo=repos["user_repo"],
    metrics_collector=metrics_collector,
    transaction_manager=transaction_manager,
),
```

Change to:

```python
"user_role_service": UserRoleService(
    user_repo=repos["user_repo"],
    metrics_collector=metrics_collector,
    transaction_manager=transaction_manager,
    blogger_profile_repo=repos["blogger_repo"],
),
```

Note: `repos["blogger_repo"]` is the `BloggerProfileRepository` — already available in the repos dict (used by `BloggerRegistrationService` on the next line).

- [ ] **Step 2: Run typecheck**

Run: `uv run mypy src/ugc_bot/container/service_factory.py src/ugc_bot/application/services/user_role_service.py`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/container/service_factory.py
git commit -m "feat: wire blogger_profile_repo into UserRoleService"
```

---

### Task 3: Modify Max creator registration handler to link accounts

**Files:**
- Modify: `src/ugc_bot/bot/max/handlers/blogger_registration.py`

- [ ] **Step 1: Change `handle_instagram` to attempt account linking**

In `src/ugc_bot/bot/max/handlers/blogger_registration.py`, the `handle_instagram` function (line 369) currently rejects duplicate Instagram URLs (lines 406-416):

```python
existing_profile = (
    await blogger_registration_service.get_profile_by_instagram_url(
        instagram_url
    )
)
if existing_profile is not None:
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_already,
    )
    return
```

Replace that block with account linking logic:

```python
existing_profile = (
    await blogger_registration_service.get_profile_by_instagram_url(
        instagram_url
    )
)
if existing_profile is not None:
    user_role_service: UserRoleService = deps["user_role_service"]
    linked_user = await user_role_service.link_max_account(
        max_id=incoming.user.external_id,
        instagram_url=instagram_url,
        username=incoming.user.username or "",
    )
    if linked_user:
        msg_linked = await bot_texts_service.get(
            "msg_account_linked", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg_linked,
        )
        await state_store.clear()
        return
    # link failed (user already has different max_id) — reject as duplicate
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=msg_already,
    )
    return
```

- [ ] **Step 2: Run lint and typecheck**

Run: `uv run ruff check src/ugc_bot/bot/max/handlers/blogger_registration.py && uv run mypy src/ugc_bot/bot/max/handlers/blogger_registration.py`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/bot/max/handlers/blogger_registration.py
git commit -m "feat: link Max account to existing Telegram user during creator registration"
```

---

### Task 4: Add bot text for account linked message

**Files:**
- Modify: `src/ugc_bot/bot/texts/defaults/ru.py`
- Modify: `src/ugc_bot/bot/texts/defaults/en.py`

- [ ] **Step 1: Add `msg_account_linked` to Russian texts**

In `src/ugc_bot/bot/texts/defaults/ru.py`, add:

```python
"msg_account_linked": "Мы нашли ваш аккаунт! Все данные сохранены. Теперь вы можете продолжить работу в Max.",
```

- [ ] **Step 2: Add `msg_account_linked` to English texts**

In `src/ugc_bot/bot/texts/defaults/en.py`, add:

```python
"msg_account_linked": "We found your account! All data is preserved. You can now continue working in Max.",
```

- [ ] **Step 3: Run lint**

Run: `uv run ruff check src/ugc_bot/bot/texts/defaults/ru.py src/ugc_bot/bot/texts/defaults/en.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/bot/texts/defaults/ru.py src/ugc_bot/bot/texts/defaults/en.py
git commit -m "feat: add msg_account_linked bot text for account linking notification"
```

---

### Task 5: Run full quality checks

- [ ] **Step 1: Run `make fix`**

Run: `make fix`
Expected: format + format-check + lint + typecheck + coverage all pass

- [ ] **Step 2: Fix any issues found**

If any step fails, fix the issue and re-run.

- [ ] **Step 3: Final commit if fixes were needed**

```bash
git add -u
git commit -m "fix: address lint/type/test issues from account linking"
```
