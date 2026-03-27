# Max-Telegram Account Linking Design

## Problem

Telegram is being throttled in some regions. Users who previously used the Telegram bot are migrating to the Max bot. They need to keep their existing profile, orders, and statistics when switching messengers.

## Solution

Link Max and Telegram accounts via verified Instagram URL. Instagram is already unique per user and verified during blogger registration, making it a reliable identity proof.

## Scope

- **Direction:** Max -> Telegram only (Max user links to existing Telegram account)
- **Roles:** Creators (bloggers) only. Advertisers in Max are always new users.
- **Telegram bot:** No changes

## User Flow (Creator in Max)

```
Max bot: /start or bot_started
  -> Choose role: Creator / Advertiser

  [Advertiser] -> standard registration, new User with max_id

  [Creator] -> "Enter your Instagram URL"
    -> Instagram verification (standard flow, re-verification required)
    -> Verification passed:
        -> Search DB for user with this instagram_url

        [Found] -> link_max_account():
          - Add max_id to existing User
          - Set messenger_type = MAX
          - Skip remaining registration steps
          - Bot: "We found your account! All data is preserved."

        [Not found] -> standard new User registration with max_id
```

## Service Layer

New method in `UserRoleService`:

```python
async def link_max_account(
    self,
    max_id: str,
    instagram_url: str,
    username: str,
) -> User | None:
    """
    Find existing user by instagram_url via BloggerProfileRepository.
    If found, attach max_id and set messenger_type to MAX.
    Returns User if linked, None if not found.
    """
    blogger_profile = await self.blogger_profile_repo.get_by_instagram_url(
        instagram_url
    )
    if blogger_profile is None:
        return None

    existing = await self.user_repo.get(blogger_profile.user_id)
    if existing is None:
        return None

    updated = replace(
        existing,
        max_id=max_id,
        messenger_type=MessengerType.MAX,
        username=username,
    )
    await self.user_repo.save(updated)
    return updated
```

Requires injecting `blogger_profile_repo` into `UserRoleService`.

## Max Handler Changes

In `bot/max/handlers/blogger_registration.py`, after successful Instagram verification:

```python
linked_user = await user_role_service.link_max_account(
    max_id=incoming.user.external_id,
    instagram_url=verified_instagram_url,
    username=incoming.user.username,
)

if linked_user:
    # Account linked, skip registration
    await messenger.send_text(
        chat_id=incoming.chat_id,
        text="We found your account! All data is preserved.",
    )
else:
    # New user, continue standard registration
    await user_role_service.set_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
        username=incoming.user.username,
    )
    # ... remaining registration steps
```

## Edge Cases

1. **User already has a `max_id`:** Reject. One User = one Telegram + one Max account.
2. **`max_id` already taken by another User:** Check before save, return error. DB UNIQUE constraint is the safety net.
3. **Someone enters another person's Instagram:** Instagram verification (code in bio/story) prevents this.
4. **Unlinking accounts:** Out of scope for now.
5. **Notifications after linking:** `messenger_type = MAX` means bot notifications go to Max. User should understand this.

## What Does NOT Change

- Telegram bot — no changes
- Miniapp — already supports both platforms via `external_id` + `platform`
- User model / DB schema — `telegram_id` and `max_id` fields already exist
- Repositories — `get_by_instagram_url` already exists
- Advertisers in Max — standard registration, no linking

## Changes Summary

| Component | Change |
|-----------|--------|
| `UserRoleService` | New `link_max_account` method + `blogger_profile_repo` dependency |
| Max creator registration handler | Call `link_max_account` after Instagram verification, branch on result |
| Bot texts | New message: "We found your account! All data is preserved." |
| Tests | Unit tests for `link_max_account` (linked, not found, already taken) |
