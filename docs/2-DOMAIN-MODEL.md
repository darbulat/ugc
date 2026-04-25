---
title: Domain Model
tags: [domain, entities, core]
aliases: [Domain Model, Entities]
---

# Domain Model

The domain layer defines pure business entities and enums without any framework dependencies.

## Core Entities

### User
Main entity representing a platform user.

**Attributes:**
- `id` (UUID) — Unique internal identifier
- `external_id` (str) — External ID from messenger (Telegram user_id, etc.)
- `messenger_type` (MessengerType) — Which messenger (TELEGRAM, MAX, INSTAGRAM)
- `username` (str | None) — Username from messenger
- `phone` (str | None) — Phone number (E.164 format)
- `role` (UserRole) — CREATOR, BRAND, ADMIN
- `status` (UserStatus) — ACTIVE, BLOCKED, PENDING_VERIFICATION
- `language_code` (str) — ISO 639-1 code (en, ru, etc.)
- `created_at` (datetime)
- `updated_at` (datetime)

**Key Invariants:**
- `external_id + messenger_type` is unique
- User can have multiple messenger accounts (same person)
- Role determines available features

### Offer
An assignment from a brand to a creator to create content.

**Attributes:**
- `id` (UUID)
- `brand_id` (UUID) — References User (role=BRAND)
- `title` (str) — Short title of what content is needed
- `description` (str) — Detailed requirements
- `budget_usd` (Decimal) — Payment amount
- `budget_currency` (str) — ISO 4217 currency code
- `status` (OfferStatus) — ACTIVE, ACCEPTED, REJECTED, COMPLETED, PAID
- `created_at` (datetime)
- `expires_at` (datetime | None)
- `created_by_user_id` (UUID)

**Statuses:**
```
ACTIVE → ACCEPTED → COMPLETED → PAID
      ↘ REJECTED ↗
```

### OfferResponse
Creator's response to an offer.

**Attributes:**
- `id` (UUID)
- `offer_id` (UUID)
- `creator_id` (UUID) — References User (role=CREATOR)
- `status` (OfferResponseStatus) — PENDING, ACCEPTED, REJECTED
- `message` (str | None) — Creator's message with proposal
- `created_at` (datetime)

### BloggerRating
Rating system for creators (bloggers).

**Attributes:**
- `id` (UUID)
- `creator_id` (UUID)
- `rating` (float) — 0.0 to 5.0
- `total_reviews` (int)
- `completion_rate` (float) — 0 to 1.0 (completed/accepted)
- `avg_response_time_hours` (float | None)
- `last_updated` (datetime)

## Enums

### UserRole
```python
CREATOR = "creator"      # Content creator (individual blogger)
BRAND = "brand"          # Brand/business placing offers
ADMIN = "admin"          # Platform administrator
```

### UserStatus
```python
ACTIVE = "active"                    # Normal user
BLOCKED = "blocked"                  # Banned by admin
PENDING_VERIFICATION = "pending"     # Awaiting email/phone verification
```

### OfferStatus
```python
ACTIVE = "active"          # Open for applications
ACCEPTED = "accepted"      # Creator accepted the offer
REJECTED = "rejected"      # Brand rejected
COMPLETED = "completed"    # Work delivered by creator
PAID = "paid"              # Brand paid the creator
CANCELLED = "cancelled"    # Cancelled by brand
```

### OfferResponseStatus
```python
PENDING = "pending"        # Waiting for brand decision
ACCEPTED = "accepted"      # Brand approved, ready to work
REJECTED = "rejected"      # Brand declined
WITHDRAWN = "withdrawn"    # Creator cancelled response
```

### MessengerType
```python
TELEGRAM = "telegram"      # Telegram app
MAX = "max"                # VK Max (formerly VK Me)
INSTAGRAM = "instagram"    # Instagram DMs (future)
WHATSAPP = "whatsapp"      # WhatsApp (future)
```

### OfferMatchStatus
```python
SUGGESTED = "suggested"    # Auto-matched by algorithm
VIEWED = "viewed"          # Creator viewed the offer
APPLIED = "applied"        # Creator applied
ACCEPTED = "accepted"      # Brand accepted
```

## Value Objects

### Phone
Represents an E.164 formatted phone number.
```python
class Phone:
    number: str  # "+1234567890" format
    country_code: str  # "US"
    is_valid() -> bool
```

### Money
Represents a monetary amount with currency.
```python
class Money:
    amount: Decimal
    currency: str  # ISO 4217
    convert_to(target_currency) -> Money
```

## Relationships

```
User (BRAND)
  └─ Offer (1:*)
      └─ OfferResponse (1:*)
          └─ User (CREATOR)

User (CREATOR)
  ├─ OfferResponse (1:*)
  └─ BloggerRating (1:1)

BloggerRating
  └─ Creator User (1:1)
```

## Business Rules

### Creator Can Only:
- View active offers from brands
- Submit responses to offers
- View their own rating and stats
- Update profile (bio, portfolio, etc.)

### Brand Can Only:
- Create offers with budget
- View responses to their offers
- Accept/reject creators
- Mark work as completed
- Pay creators

### Admin Can:
- View all users and offers
- Moderate content
- Block/unblock users
- Set featured creators
- View analytics

---

## Related Documents
- [[Development Workflow]]
- [[Architecture Overview]]
- [[Database Schema]]
