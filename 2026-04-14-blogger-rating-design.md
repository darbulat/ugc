# Blogger Rating System — Design

**Date:** 2026-04-14  
**Status:** Approved

## Summary

A rating system for bloggers where managers, advertisers, and admins leave 1–5 star ratings with optional comments after an order. Ratings affect offer dispatch: bloggers below a minimum threshold are filtered out, and remaining bloggers are sorted by average rating descending.

---

## Domain Model

### New entity: `BloggerRating`

```python
@dataclass(frozen=True)
class BloggerRating:
    rating_id: UUID
    blogger_id: UUID        # FK → users.user_id
    order_id: UUID          # FK → orders.order_id
    rater_id: UUID          # FK → users.user_id
    rater_role: RaterRole   # manager / advertiser / admin
    score: int              # 1–5
    comment: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]
```

### New enum: `RaterRole`

```python
class RaterRole(StrEnum):
    MANAGER = "manager"
    ADVERTISER = "advertiser"
    ADMIN = "admin"
```

### DB table: `blogger_ratings`

| Column | Type | Notes |
|---|---|---|
| `rating_id` | UUID PK | `uuid_generate_v4()` default |
| `blogger_id` | UUID FK users | NOT NULL, indexed |
| `order_id` | UUID FK orders | NOT NULL |
| `rater_id` | UUID FK users | NOT NULL |
| `rater_role` | varchar | NOT NULL |
| `score` | smallint | NOT NULL, CHECK 1–5 |
| `comment` | text | nullable |
| `created_at` | timestamptz | NOT NULL, default now() |
| `updated_at` | timestamptz | nullable |

**Unique constraint:** `UNIQUE(blogger_id, order_id)` — one rating per order per blogger.

---

## Application Layer

### Port: `BloggerRatingRepository` (in `application/ports.py`)

```python
class BloggerRatingRepository(ABC):
    async def save(self, rating: BloggerRating, session=None) -> None: ...
    async def get_by_blogger_and_order(
        self, blogger_id: UUID, order_id: UUID, session=None
    ) -> Optional[BloggerRating]: ...
    async def get_avg_rating(
        self, blogger_id: UUID, session=None
    ) -> Optional[float]: ...
    async def list_by_blogger(
        self, blogger_id: UUID, session=None
    ) -> list[BloggerRating]: ...
```

### Service: `BloggerRatingService` (new file `application/services/blogger_rating_service.py`)

Responsibilities:
- `rate_blogger(blogger_id, order_id, rater_id, rater_role, score, comment)` — validates score in [1,5], checks no duplicate rating for this order, saves
- `get_blogger_avg_rating(blogger_id)` → `Optional[float]`
- `get_blogger_ratings(blogger_id)` → `list[BloggerRating]`

Errors raised:
- `RatingAlreadyExistsError` — rating already given for this order
- `InvalidRatingScoreError` — score outside 1–5

### Offer Dispatch Integration

**`Order` entity** gains one new admin-only field:

```python
min_rating: Optional[float] = None   # e.g. 3.0; None = no filter
```

**`_DispatchCriteria`** gains:

```python
min_rating: Optional[float]
min_rating_enabled: bool
```

**Dispatch loop changes:**

1. If `min_rating_enabled`: fetch avg_rating for each blogger; skip if avg_rating < min_rating (bloggers with no ratings pass if no threshold set, are moved to end if threshold is set and they have no rating)
2. After filtering: sort eligible bloggers by avg_rating descending; bloggers with no rating go last

---

## Interfaces

### Admin Panel (SQLAdmin)

- New `BloggerRatingAdmin(ModelView)` for `BloggerRatingModel` — list/create/edit ratings
- `BloggerProfileAdmin`: add read-only computed column showing avg rating
- `OrderAdmin`: expose `min_rating` field for dispatch configuration (alongside existing `min_followers`, `min_age`, etc.)

### Telegram Bot

Trigger: when an order transitions to `OrderStatus.CLOSED`, the bot sends a rating prompt to the manager and the advertiser assigned to that order.

Flow:
1. Bot sends message with inline buttons ⭐1–⭐5
2. User selects a score
3. Bot asks for an optional comment ("Напишите комментарий или нажмите «Пропустить»")
4. Rating is saved via `BloggerRatingService`

New handler in `bot/` — FSM states: `RatingStates.waiting_score`, `RatingStates.waiting_comment`.

### Mini App (`miniapp/api.py`)

Two new endpoints:

```
POST /ratings
  Body: { blogger_id, order_id, score, comment? }
  Auth: existing user auth (rater_role inferred from user role)

GET /bloggers/{blogger_id}/rating
  Response: { avg_rating: float|null, ratings: [...] }
```

Rating shown in blogger card: average stars + list of reviews with rater_role, score, comment, date.

---

## Testing

### Unit tests (`tests/unit/`)

- `BloggerRatingService.rate_blogger`:
  - valid score saved correctly
  - duplicate for same order raises `RatingAlreadyExistsError`
  - score outside 1–5 raises `InvalidRatingScoreError`
- `_passes_rating_filter` in `offer_dispatch_service`:
  - blogger above threshold passes
  - blogger below threshold fails
  - blogger with no rating and threshold set goes to end (does not pass filter)
  - blogger with no rating and no threshold passes
- Dispatch sorting: bloggers sorted by avg_rating desc, no-rating bloggers last

### Integration tests (`tests/integration/`)

- `BloggerRatingRepository.save` + `get_avg_rating`: multiple ratings average correctly
- `UNIQUE(blogger_id, order_id)` constraint: duplicate raises DB error

### In-memory fake

`InMemoryBloggerRatingRepository` added to `infrastructure/memory_repositories.py` for unit test use.

---

## Migration

One Alembic migration:
1. Add `min_rating` column to `orders` table (nullable float)
2. Create `blogger_ratings` table with all columns and constraints
