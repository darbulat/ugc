# Verify Instagram Before Account Linking

**Date:** 2026-03-27
**Status:** Approved

## Problem

When a Max user enters an Instagram URL that matches an existing Telegram user's profile, `link_max_account` runs immediately — without verifying that the Max user actually owns that Instagram account. Any user can hijack another blogger's account by entering their URL.

## Solution

Require Instagram verification (DM code) before linking. Extend `InstagramVerificationCode` with optional linking metadata so that `verify_code_by_instagram_sender` can perform the link after successful verification.

## Design

### 1. Domain Entity Changes

`InstagramVerificationCode` gets 3 optional fields:

```python
link_max_id: str | None = None
link_max_chat_id: str | None = None
link_username: str | None = None
```

When populated, the code represents a "linking verification" — after the code is confirmed, `link_max_account` is called with these values.

### 2. DB Migration (0086)

Add 3 nullable `String` columns to `instagram_verification_codes`:
- `link_max_id`
- `link_max_chat_id`
- `link_username`

### 3. ORM Model Changes

`InstagramVerificationCodeModel` — add 3 `Mapped[Optional[str]]` columns. Update `_to_verification_entity` and `_to_verification_model` mappers.

### 4. Handler Changes (`handle_instagram`)

When `existing_profile is not None` (duplicate Instagram URL detected):

1. Find existing Telegram user (owner of the profile) via `blogger_profile_repo.get_by_instagram_username` → `user_repo.get_by_id`
2. Call `instagram_verification_service.generate_code(existing_user.user_id, link_max_id=..., link_max_chat_id=..., link_username=...)`
3. Send verification instruction + code (same format as `/verify_instagram`)
4. Clear FSM state, return

Remove the direct `link_max_account` call from `handle_instagram`.

### 5. `generate_code` Changes

Accept optional linking params:

```python
async def generate_code(
    self,
    user_id: UUID,
    link_max_id: str | None = None,
    link_max_chat_id: str | None = None,
    link_username: str | None = None,
) -> InstagramVerificationCode:
```

Pass them through to `InstagramVerificationCode(...)`.

### 6. `InstagramVerificationService` Changes

Add `user_role_service: UserRoleService | None = None` field.

#### `verify_code_by_instagram_sender`

After successful verification (profile confirmed), check `valid_code.link_max_id`:
- If set → call `self.user_role_service.link_max_account(max_id=valid_code.link_max_id, instagram_url=profile.instagram_url, username=valid_code.link_username, max_chat_id=valid_code.link_max_chat_id)`
- Return `VerificationLinkSuccess(user_id, linked_user)` on success
- Return existing `VerificationSuccess(user_id)` if no linking params

#### `verify_code` (manual code entry)

Same logic — check `valid_code.link_max_id` after confirming profile.

### 7. New Result Type

```python
@dataclass(slots=True)
class VerificationLinkSuccess:
    """Verification succeeded and Max account was linked."""
    user_id: UUID
    linked_user_id: UUID
```

### 8. `instagram_webhook_app` Changes

In `_handle_messaging_event`:
- `VerificationLinkSuccess` → call `_notify_user_link_success(...)` — sends `msg_account_linked` to the Max user
- `VerificationMismatch` — existing behavior already sends mismatch message with expected/actual usernames

Add `_notify_user_link_success` function that sends `msg_account_linked` to the **linked user's Max chat** (using `linked_user.max_chat_id`).

### 9. Container Wiring

`build_instagram_verification_service` — pass `user_role_service` built with `user_repo` and `blogger_profile_repo`.

For webhook context: build a `UserRoleService` and inject it.

### 10. Bot Texts

Already have:
- `msg_account_linked` (ru/en) — for successful link
- `msg_instagram_mismatch` (ru/en) — for mismatch

No new texts needed. The verification instruction (`msg_instagram_verify_instruction`) is reused as-is.

### 11. Memory Repository

`InMemoryInstagramVerificationRepository` — update `save`/`get_*` to handle new fields (they're part of the entity, so mostly free).

## Flow Diagram

```
Max user enters Instagram URL
    ↓
URL matches existing profile?
    ├─ No → normal registration flow
    └─ Yes → generate verification code (with link_max_id/chat_id/username)
              ↓
         Send instruction + code to Max user
              ↓
         User sends code to Instagram DM
              ↓
         instagram_webhook receives code
              ↓
         verify_code_by_instagram_sender
              ├─ Match → confirm profile + link_max_account → send msg_account_linked
              ├─ Mismatch → send msg_instagram_mismatch (expected vs actual)
              └─ Not found → ignore
```

## Files to Modify

1. `domain/entities.py` — 3 fields on `InstagramVerificationCode`
2. `infrastructure/db/models.py` — 3 columns on `InstagramVerificationCodeModel`
3. `infrastructure/db/migrations/versions/0086_*.py` — new migration
4. `infrastructure/db/repositories/instagram.py` — update mappers
5. `infrastructure/memory_repositories.py` — update memory repo entity handling
6. `application/services/instagram_verification_service.py` — `generate_code` params, `verify_code*` linking logic, `VerificationLinkSuccess` type, `user_role_service` field
7. `bot/max/handlers/blogger_registration.py` — replace direct `link_max_account` with verification flow
8. `instagram_webhook_app.py` — handle `VerificationLinkSuccess`
9. `container/service_factory.py` — wire `user_role_service` into verification service
10. `container/__init__.py` — update `build_instagram_verification_service`
11. Tests — update existing, add new for linking verification flow
