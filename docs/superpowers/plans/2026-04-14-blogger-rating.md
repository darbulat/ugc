# Blogger Rating System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 1–5 star rating system for bloggers where managers, advertisers, and admins leave one rating per order; ratings filter and sort offer dispatch.

**Architecture:** Separate `BloggerRating` domain entity + `BloggerRatingRepository` port following hexagonal patterns already in the codebase. `OfferDispatchService` gains an optional `blogger_rating_repo` field and applies rating filter/sort inside `_collect_eligible_users`. Interfaces: SQLAdmin view, Telegram FSM handler, Mini App endpoints.

**Tech Stack:** Python 3.12, SQLAlchemy async, Alembic, aiogram 3, FastAPI, PostgreSQL 16

---

## Files

**Create:**
- `src/ugc_bot/application/services/blogger_rating_service.py`
- `src/ugc_bot/infrastructure/db/repositories/ratings.py`
- `src/ugc_bot/infrastructure/db/migrations/versions/0092_add_blogger_ratings.py`
- `src/ugc_bot/bot/telegram/handlers/blogger_rating.py`
- `tests/unit/test_blogger_rating_service.py`
- `tests/integration/test_blogger_rating_repository.py`

**Modify:**
- `src/ugc_bot/domain/enums.py` — add `RaterRole`
- `src/ugc_bot/domain/entities.py` — add `BloggerRating`; add `min_rating` to `Order`
- `src/ugc_bot/application/errors.py` — add `RatingAlreadyExistsError`, `InvalidRatingScoreError`
- `src/ugc_bot/application/ports.py` — add `BloggerRatingRepository`
- `src/ugc_bot/infrastructure/memory_repositories.py` — add `InMemoryBloggerRatingRepository`
- `src/ugc_bot/infrastructure/db/models.py` — add `BloggerRatingModel`; add `min_rating` to `OrderModel`
- `src/ugc_bot/infrastructure/db/repositories/orders.py` — add `min_rating` to entity/model mappers
- `src/ugc_bot/infrastructure/db/repositories/__init__.py` — re-export `SqlAlchemyBloggerRatingRepository`
- `src/ugc_bot/application/services/offer_dispatch_service.py` — rating filter + sort in `_collect_eligible_users`
- `src/ugc_bot/container/repository_factory.py` — add `rating_repo`
- `src/ugc_bot/container/service_factory.py` — add `blogger_rating_service`, wire into `OfferDispatchService`
- `src/ugc_bot/admin/app.py` — add `BloggerRatingAdmin`, expose `min_rating` on `OrderAdmin`
- `src/ugc_bot/miniapp/api.py` — add `POST /ratings`, `GET /bloggers/{blogger_id}/rating`

---

## Task 1: Domain — `RaterRole` enum + `BloggerRating` entity

**Files:**
- Modify: `src/ugc_bot/domain/enums.py`
- Modify: `src/ugc_bot/domain/entities.py`

- [ ] **Step 1: Add `RaterRole` enum to `enums.py`**

Add after the last enum in the file:

```python
class RaterRole(StrEnum):
    """Who left the blogger rating."""

    MANAGER = "manager"
    ADVERTISER = "advertiser"
    ADMIN = "admin"
```

- [ ] **Step 2: Add `BloggerRating` entity to `entities.py`**

Add the import of `RaterRole` in the imports block at top of file:

```python
from ugc_bot.domain.enums import (
    ...
    RaterRole,
    ...
)
```

Then add the dataclass at the end of the file:

```python
@dataclass(frozen=True)
class BloggerRating:
    """Blogger rating left by manager, advertiser, or admin after an order.

    When adding a new field:
    1. Add it here (and to the ORM model + migration if persisted).
    2. Find all usages: grep -r "BloggerRating(" src/
    3. For updates use dataclasses.replace(rating, ...).
    4. Update _to_blogger_rating_entity in infrastructure/db/repositories/ratings.py.
    """

    rating_id: UUID
    blogger_id: UUID
    order_id: UUID
    rater_id: UUID
    rater_role: RaterRole
    score: int  # 1–5
    comment: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None
```

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/domain/enums.py src/ugc_bot/domain/entities.py
git commit -m "feat: add BloggerRating domain entity and RaterRole enum"
```

---

## Task 2: Application errors + port

**Files:**
- Modify: `src/ugc_bot/application/errors.py`
- Modify: `src/ugc_bot/application/ports.py`

- [ ] **Step 1: Add errors to `errors.py`**

Add at the end of the file:

```python
class RatingAlreadyExistsError(ValueError):
    """Raised when a rating already exists for this blogger+order pair."""


class InvalidRatingScoreError(ValueError):
    """Raised when score is outside the allowed range 1–5."""
```

- [ ] **Step 2: Add `BloggerRatingRepository` port to `ports.py`**

Add import of `BloggerRating` in the imports block:

```python
from ugc_bot.domain.entities import (
    ...
    BloggerRating,
    ...
)
```

Add the ABC class after existing repositories (e.g. after `NpsRepository`):

```python
class BloggerRatingRepository(ABC):
    """Port for blogger rating persistence."""

    @abstractmethod
    async def save(
        self, rating: BloggerRating, session: object | None = None
    ) -> None:
        """Persist a blogger rating (insert or update)."""

    @abstractmethod
    async def get_by_blogger_and_order(
        self,
        blogger_id: UUID,
        order_id: UUID,
        session: object | None = None,
    ) -> Optional[BloggerRating]:
        """Fetch rating for a specific blogger+order pair, or None."""

    @abstractmethod
    async def get_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> Optional[float]:
        """Return average score for a blogger, or None if no ratings."""

    @abstractmethod
    async def list_by_blogger(
        self, blogger_id: UUID, session: object | None = None
    ) -> List[BloggerRating]:
        """Return all ratings for a blogger, newest first."""

    @abstractmethod
    async def get_avg_ratings_for_bloggers(
        self,
        blogger_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, float]:
        """Return avg score keyed by blogger_id; omits bloggers with no ratings."""
```

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/application/errors.py src/ugc_bot/application/ports.py
git commit -m "feat: add BloggerRatingRepository port and rating errors"
```

---

## Task 3: In-memory fake repository

**Files:**
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py`

- [ ] **Step 1: Add import of `BloggerRating`, `BloggerRatingRepository`, `RaterRole` at top of file**

In the ports import block add:
```python
    BloggerRatingRepository,
```

In the entities import block add:
```python
    BloggerRating,
```

In the enums import block add:
```python
    RaterRole,
```

- [ ] **Step 2: Add `InMemoryBloggerRatingRepository` at end of file**

```python
@dataclass
class InMemoryBloggerRatingRepository(BloggerRatingRepository):
    """In-memory implementation of blogger rating repository for tests."""

    ratings: list[BloggerRating] = field(default_factory=list)

    async def save(
        self, rating: BloggerRating, session: object | None = None
    ) -> None:
        """Persist a rating, replacing existing one for same blogger+order."""
        self.ratings = [
            r
            for r in self.ratings
            if not (r.blogger_id == rating.blogger_id and r.order_id == rating.order_id)
        ]
        self.ratings.append(rating)

    async def get_by_blogger_and_order(
        self,
        blogger_id: UUID,
        order_id: UUID,
        session: object | None = None,
    ) -> Optional[BloggerRating]:
        """Fetch rating for a specific blogger+order pair."""
        for r in self.ratings:
            if r.blogger_id == blogger_id and r.order_id == order_id:
                return r
        return None

    async def get_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> Optional[float]:
        """Return average score, or None if no ratings."""
        scores = [r.score for r in self.ratings if r.blogger_id == blogger_id]
        return sum(scores) / len(scores) if scores else None

    async def list_by_blogger(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[BloggerRating]:
        """Return ratings for blogger, newest first."""
        return sorted(
            [r for r in self.ratings if r.blogger_id == blogger_id],
            key=lambda r: r.created_at,
            reverse=True,
        )

    async def get_avg_ratings_for_bloggers(
        self,
        blogger_ids: List[UUID],
        session: object | None = None,
    ) -> Dict[UUID, float]:
        """Return avg score keyed by blogger_id."""
        result: Dict[UUID, float] = {}
        for bid in blogger_ids:
            avg = await self.get_avg_rating(bid)
            if avg is not None:
                result[bid] = avg
        return result
```

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/infrastructure/memory_repositories.py
git commit -m "feat: add InMemoryBloggerRatingRepository for tests"
```

---

## Task 4: `BloggerRatingService` + unit tests

**Files:**
- Create: `src/ugc_bot/application/services/blogger_rating_service.py`
- Create: `tests/unit/test_blogger_rating_service.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_blogger_rating_service.py`:

```python
"""Unit tests for BloggerRatingService."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryBloggerRatingRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_service() -> tuple[BloggerRatingService, InMemoryBloggerRatingRepository]:
    repo = InMemoryBloggerRatingRepository()
    service = BloggerRatingService(rating_repo=repo)
    return service, repo


@pytest.mark.asyncio
async def test_rate_blogger_saves_rating():
    service, repo = _build_service()
    blogger_id = uuid4()
    order_id = uuid4()
    rater_id = uuid4()

    rating = await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=order_id,
        rater_id=rater_id,
        rater_role=RaterRole.MANAGER,
        score=4,
        comment="Good job",
    )

    assert rating.blogger_id == blogger_id
    assert rating.order_id == order_id
    assert rating.rater_id == rater_id
    assert rating.rater_role == RaterRole.MANAGER
    assert rating.score == 4
    assert rating.comment == "Good job"
    stored = await repo.get_by_blogger_and_order(blogger_id, order_id)
    assert stored is not None
    assert stored.score == 4


@pytest.mark.asyncio
async def test_rate_blogger_no_comment():
    service, repo = _build_service()
    blogger_id = uuid4()
    order_id = uuid4()

    rating = await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=order_id,
        rater_id=uuid4(),
        rater_role=RaterRole.ADVERTISER,
        score=3,
    )

    assert rating.comment is None


@pytest.mark.asyncio
async def test_rate_blogger_duplicate_raises():
    service, _ = _build_service()
    blogger_id = uuid4()
    order_id = uuid4()
    rater_id = uuid4()

    await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=order_id,
        rater_id=rater_id,
        rater_role=RaterRole.ADMIN,
        score=5,
    )

    with pytest.raises(RatingAlreadyExistsError):
        await service.rate_blogger(
            blogger_id=blogger_id,
            order_id=order_id,
            rater_id=uuid4(),
            rater_role=RaterRole.MANAGER,
            score=3,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_score", [0, 6, -1, 10])
async def test_rate_blogger_invalid_score_raises(bad_score: int):
    service, _ = _build_service()

    with pytest.raises(InvalidRatingScoreError):
        await service.rate_blogger(
            blogger_id=uuid4(),
            order_id=uuid4(),
            rater_id=uuid4(),
            rater_role=RaterRole.MANAGER,
            score=bad_score,
        )


@pytest.mark.asyncio
async def test_get_blogger_avg_rating():
    service, repo = _build_service()
    blogger_id = uuid4()

    assert await service.get_blogger_avg_rating(blogger_id) is None

    await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=uuid4(),
        rater_id=uuid4(),
        rater_role=RaterRole.MANAGER,
        score=4,
    )
    await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=uuid4(),
        rater_id=uuid4(),
        rater_role=RaterRole.ADVERTISER,
        score=2,
    )

    avg = await service.get_blogger_avg_rating(blogger_id)
    assert avg == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_get_blogger_ratings_returns_list():
    service, _ = _build_service()
    blogger_id = uuid4()

    await service.rate_blogger(
        blogger_id=blogger_id,
        order_id=uuid4(),
        rater_id=uuid4(),
        rater_role=RaterRole.MANAGER,
        score=5,
    )

    ratings = await service.get_blogger_ratings(blogger_id)
    assert len(ratings) == 1
    assert ratings[0].score == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_blogger_rating_service.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` for `blogger_rating_service`.

- [ ] **Step 3: Implement `BloggerRatingService`**

Create `src/ugc_bot/application/services/blogger_rating_service.py`:

```python
"""Service for blogger rating management."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.ports import BloggerRatingRepository
from ugc_bot.domain.entities import BloggerRating
from ugc_bot.domain.enums import RaterRole


@dataclass(slots=True)
class BloggerRatingService:
    """Manage blogger ratings."""

    rating_repo: BloggerRatingRepository

    async def rate_blogger(
        self,
        blogger_id: UUID,
        order_id: UUID,
        rater_id: UUID,
        rater_role: RaterRole,
        score: int,
        comment: Optional[str] = None,
        session: object | None = None,
    ) -> BloggerRating:
        """Create a rating for a blogger on an order.

        Raises:
            InvalidRatingScoreError: if score not in 1–5.
            RatingAlreadyExistsError: if rating already exists for this order.
        """
        if score < 1 or score > 5:
            raise InvalidRatingScoreError(
                f"Score must be between 1 and 5, got {score}"
            )
        existing = await self.rating_repo.get_by_blogger_and_order(
            blogger_id, order_id, session=session
        )
        if existing is not None:
            raise RatingAlreadyExistsError(
                f"Rating already exists for blogger {blogger_id} on order {order_id}"
            )
        rating = BloggerRating(
            rating_id=uuid4(),
            blogger_id=blogger_id,
            order_id=order_id,
            rater_id=rater_id,
            rater_role=rater_role,
            score=score,
            comment=comment,
            created_at=datetime.now(timezone.utc),
        )
        await self.rating_repo.save(rating, session=session)
        return rating

    async def get_blogger_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> Optional[float]:
        """Return average rating score for a blogger, or None if unrated."""
        return await self.rating_repo.get_avg_rating(blogger_id, session=session)

    async def get_blogger_ratings(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[BloggerRating]:
        """Return all ratings for a blogger, newest first."""
        return await self.rating_repo.list_by_blogger(
            blogger_id, session=session
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_blogger_rating_service.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/blogger_rating_service.py \
        tests/unit/test_blogger_rating_service.py
git commit -m "feat: add BloggerRatingService with unit tests"
```

---

## Task 5: DB Model — `BloggerRatingModel` + `min_rating` on `OrderModel`

**Files:**
- Modify: `src/ugc_bot/infrastructure/db/models.py`

- [ ] **Step 1: Add `BloggerRatingModel` to `models.py`**

At the end of the file, add:

```python
class BloggerRatingModel(Base):
    """Blogger rating ORM model."""

    __tablename__ = "blogger_ratings"
    __table_args__ = (
        UniqueConstraint("blogger_id", "order_id", name="uq_blogger_rating_per_order"),
    )

    rating_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    blogger_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("orders.order_id", ondelete="CASCADE"),
        nullable=False,
    )
    rater_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    rater_role: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Check that `SmallInteger` and `UniqueConstraint` are already imported at the top of `models.py`. If not, add them to the SQLAlchemy imports line.

- [ ] **Step 2: Add `min_rating` column to `OrderModel`**

In `OrderModel`, after `brief_link` column, add:

```python
    min_rating: Mapped[Optional[float]] = mapped_column(
        Numeric(3, 1), nullable=True
    )
```

- [ ] **Step 3: Verify imports**

Run:
```bash
uv run python -c "from ugc_bot.infrastructure.db.models import BloggerRatingModel, OrderModel; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/infrastructure/db/models.py
git commit -m "feat: add BloggerRatingModel ORM model and min_rating to OrderModel"
```

---

## Task 6: SQL Repository for blogger ratings

**Files:**
- Create: `src/ugc_bot/infrastructure/db/repositories/ratings.py`
- Modify: `src/ugc_bot/infrastructure/db/repositories/__init__.py`

- [ ] **Step 1: Create `ratings.py`**

```python
"""SQLAlchemy blogger rating repository."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.application.ports import BloggerRatingRepository
from ugc_bot.domain.entities import BloggerRating
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.db.models import BloggerRatingModel
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


def _to_blogger_rating_entity(model: BloggerRatingModel) -> BloggerRating:
    """Map ORM model to domain entity."""
    return BloggerRating(
        rating_id=model.rating_id,
        blogger_id=model.blogger_id,
        order_id=model.order_id,
        rater_id=model.rater_id,
        rater_role=RaterRole(model.rater_role),
        score=model.score,
        comment=model.comment,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _to_blogger_rating_model(rating: BloggerRating) -> BloggerRatingModel:
    """Map domain entity to ORM model."""
    return BloggerRatingModel(
        rating_id=rating.rating_id,
        blogger_id=rating.blogger_id,
        order_id=rating.order_id,
        rater_id=rating.rater_id,
        rater_role=str(rating.rater_role),
        score=rating.score,
        comment=rating.comment,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )


@dataclass(slots=True)
class SqlAlchemyBloggerRatingRepository(BloggerRatingRepository):
    """SQLAlchemy-backed blogger rating repository."""

    session_factory: async_sessionmaker[AsyncSession]

    async def save(
        self, rating: BloggerRating, session: object | None = None
    ) -> None:
        """Persist a rating (insert or update)."""
        async with _resolve_session(self.session_factory, session) as db:
            await db.merge(_to_blogger_rating_model(rating))

    async def get_by_blogger_and_order(
        self,
        blogger_id: UUID,
        order_id: UUID,
        session: object | None = None,
    ) -> Optional[BloggerRating]:
        """Fetch rating for blogger+order pair."""
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.execute(
                select(BloggerRatingModel).where(
                    BloggerRatingModel.blogger_id == blogger_id,
                    BloggerRatingModel.order_id == order_id,
                )
            )
            model = result.scalar_one_or_none()
            return _to_blogger_rating_entity(model) if model else None

    async def get_avg_rating(
        self, blogger_id: UUID, session: object | None = None
    ) -> Optional[float]:
        """Return average score for a blogger."""
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.execute(
                select(func.avg(BloggerRatingModel.score)).where(
                    BloggerRatingModel.blogger_id == blogger_id
                )
            )
            avg = result.scalar_one_or_none()
            return float(avg) if avg is not None else None

    async def list_by_blogger(
        self, blogger_id: UUID, session: object | None = None
    ) -> list[BloggerRating]:
        """Return ratings for a blogger, newest first."""
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.execute(
                select(BloggerRatingModel)
                .where(BloggerRatingModel.blogger_id == blogger_id)
                .order_by(BloggerRatingModel.created_at.desc())
            )
            return [_to_blogger_rating_entity(m) for m in result.scalars()]

    async def get_avg_ratings_for_bloggers(
        self,
        blogger_ids: list[UUID],
        session: object | None = None,
    ) -> dict[UUID, float]:
        """Return avg score keyed by blogger_id for a list of bloggers."""
        if not blogger_ids:
            return {}
        async with _resolve_session(self.session_factory, session) as db:
            result = await db.execute(
                select(
                    BloggerRatingModel.blogger_id,
                    func.avg(BloggerRatingModel.score).label("avg_score"),
                )
                .where(BloggerRatingModel.blogger_id.in_(blogger_ids))
                .group_by(BloggerRatingModel.blogger_id)
            )
            return {row.blogger_id: float(row.avg_score) for row in result}
```

- [ ] **Step 2: Add to `__init__.py`**

In `infrastructure/db/repositories/__init__.py`, add import:

```python
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)
```

And add to `__all__`:

```python
    "SqlAlchemyBloggerRatingRepository",
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from ugc_bot.infrastructure.db.repositories import SqlAlchemyBloggerRatingRepository; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/infrastructure/db/repositories/ratings.py \
        src/ugc_bot/infrastructure/db/repositories/__init__.py
git commit -m "feat: add SqlAlchemyBloggerRatingRepository"
```

---

## Task 7: Alembic migration

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0092_add_blogger_ratings.py`

- [ ] **Step 1: Create the migration file**

```python
"""Add blogger_ratings table and min_rating to orders.

Revision ID: 0092
Revises: 0091
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0092"
down_revision = "0091"


def upgrade() -> None:
    op.create_table(
        "blogger_ratings",
        sa.Column(
            "rating_id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            primary_key=True,
        ),
        sa.Column(
            "blogger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rater_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rater_role", sa.String(20), nullable=False),
        sa.Column("score", sa.SmallInteger, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_blogger_ratings_blogger_id",
        "blogger_ratings",
        ["blogger_id"],
    )
    op.create_unique_constraint(
        "uq_blogger_rating_per_order",
        "blogger_ratings",
        ["blogger_id", "order_id"],
    )
    op.add_column(
        "orders",
        sa.Column("min_rating", sa.Numeric(3, 1), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "min_rating")
    op.drop_table("blogger_ratings")
```

- [ ] **Step 2: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0092_add_blogger_ratings.py
git commit -m "feat: add migration 0092 for blogger_ratings table and orders.min_rating"
```

---

## Task 8: `Order` entity + mapper update for `min_rating`

**Files:**
- Modify: `src/ugc_bot/domain/entities.py`
- Modify: `src/ugc_bot/infrastructure/db/repositories/orders.py`

- [ ] **Step 1: Add `min_rating` to `Order` entity**

In `entities.py`, in the `Order` dataclass, add after `brief_link`:

```python
    min_rating: Optional[float] = None
```

- [ ] **Step 2: Update `_to_order_entity` in `orders.py`**

In `_to_order_entity`, add after `brief_link=model.brief_link,`:

```python
        min_rating=(
            float(model.min_rating) if model.min_rating is not None else None
        ),
```

- [ ] **Step 3: Update `_to_order_model` in `orders.py`**

In `_to_order_model`, add after `brief_link=order.brief_link,`:

```python
        min_rating=order.min_rating,
```

- [ ] **Step 4: Run unit tests to check nothing broken**

```bash
uv run pytest tests/unit/test_creator_order_management.py tests/unit/test_manager_service.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/domain/entities.py \
        src/ugc_bot/infrastructure/db/repositories/orders.py
git commit -m "feat: add min_rating field to Order entity and mapper"
```

---

## Task 9: Offer dispatch rating filter + sort

**Files:**
- Modify: `src/ugc_bot/application/services/offer_dispatch_service.py`
- Create: `tests/unit/test_offer_dispatch_rating.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_offer_dispatch_rating.py`:

```python
"""Unit tests for rating filter and sort in offer dispatch."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.services.offer_dispatch_service import (
    _passes_rating_filter,
    _sort_by_rating,
)
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus


def _make_user() -> User:
    return User(
        user_id=uuid4(),
        telegram_id=str(uuid4()),
        messenger_type=MessengerType.TELEGRAM,
        username="user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )


def test_passes_rating_filter_no_threshold():
    user = _make_user()
    # No threshold — all pass regardless of avg
    assert _passes_rating_filter(user.user_id, avg_ratings={}, min_rating=None) is True
    assert _passes_rating_filter(user.user_id, avg_ratings={user.user_id: 1.0}, min_rating=None) is True


def test_passes_rating_filter_with_threshold_above():
    uid = uuid4()
    assert _passes_rating_filter(uid, avg_ratings={uid: 4.0}, min_rating=3.0) is True


def test_passes_rating_filter_with_threshold_below():
    uid = uuid4()
    assert _passes_rating_filter(uid, avg_ratings={uid: 2.5}, min_rating=3.0) is False


def test_passes_rating_filter_no_rating_with_threshold():
    # Blogger has no rating but threshold is set → fails
    uid = uuid4()
    assert _passes_rating_filter(uid, avg_ratings={}, min_rating=3.0) is False


def test_sort_by_rating_descending():
    uid_high = uuid4()
    uid_low = uuid4()
    uid_none = uuid4()
    users = [
        User(user_id=uid_none, telegram_id="1", messenger_type=MessengerType.TELEGRAM,
             username="a", status=UserStatus.ACTIVE, issue_count=0,
             created_at=datetime.now(timezone.utc)),
        User(user_id=uid_low, telegram_id="2", messenger_type=MessengerType.TELEGRAM,
             username="b", status=UserStatus.ACTIVE, issue_count=0,
             created_at=datetime.now(timezone.utc)),
        User(user_id=uid_high, telegram_id="3", messenger_type=MessengerType.TELEGRAM,
             username="c", status=UserStatus.ACTIVE, issue_count=0,
             created_at=datetime.now(timezone.utc)),
    ]
    avg_ratings = {uid_high: 5.0, uid_low: 2.0}
    sorted_users = _sort_by_rating(users, avg_ratings)

    assert sorted_users[0].user_id == uid_high
    assert sorted_users[1].user_id == uid_low
    assert sorted_users[2].user_id == uid_none  # no rating goes last
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/unit/test_offer_dispatch_rating.py -v
```

Expected: `ImportError` — `_passes_rating_filter` and `_sort_by_rating` don't exist yet.

- [ ] **Step 3: Add `blogger_rating_repo` field and helper functions to `offer_dispatch_service.py`**

Add the import at the top:

```python
from ugc_bot.application.ports import (
    ...
    BloggerRatingRepository,
)
```

Add two module-level helper functions (before `SkipResult`):

```python
def _passes_rating_filter(
    blogger_id: UUID,
    avg_ratings: dict,
    min_rating: float | None,
) -> bool:
    """Return True if blogger passes the minimum rating threshold.

    Bloggers with no rating fail when a threshold is set.
    """
    if min_rating is None:
        return True
    avg = avg_ratings.get(blogger_id)
    if avg is None:
        return False
    return avg >= min_rating


def _sort_by_rating(users: list[User], avg_ratings: dict) -> list[User]:
    """Sort users by avg rating descending; unrated go last."""
    return sorted(
        users,
        key=lambda u: avg_ratings.get(u.user_id, -1.0),
        reverse=True,
    )
```

Add `blogger_rating_repo` field to `OfferDispatchService` dataclass (after `transaction_manager`):

```python
    blogger_rating_repo: BloggerRatingRepository | None = None
```

- [ ] **Step 4: Apply filter + sort in `_collect_eligible_users`**

At the end of `_collect_eligible_users`, just before `return users`, add:

```python
        # Rating filter and sort (only if repo is wired and order has min_rating)
        min_rating = getattr(order, "min_rating", None)
        if self.blogger_rating_repo is not None and users:
            user_ids = [u.user_id for u in users]
            avg_ratings = await self.blogger_rating_repo.get_avg_ratings_for_bloggers(
                user_ids, session=session
            )
            if min_rating is not None:
                users = [
                    u
                    for u in users
                    if _passes_rating_filter(u.user_id, avg_ratings, min_rating)
                ]
            users = _sort_by_rating(users, avg_ratings)

        return users
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_offer_dispatch_rating.py tests/unit/test_blogger_rating_service.py -v
```

Expected: all PASS.

- [ ] **Step 6: Run full unit suite to check nothing regressed**

```bash
uv run pytest tests/unit/ -v --timeout=5
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/application/services/offer_dispatch_service.py \
        tests/unit/test_offer_dispatch_rating.py
git commit -m "feat: add rating filter and sort to offer dispatch service"
```

---

## Task 10: Container wiring

**Files:**
- Modify: `src/ugc_bot/container/repository_factory.py`
- Modify: `src/ugc_bot/container/service_factory.py`

- [ ] **Step 1: Add `rating_repo` to `repository_factory.py`**

In the imports, add:

```python
from ugc_bot.infrastructure.db.repositories import (
    ...
    SqlAlchemyBloggerRatingRepository,
)
```

In `build_repos`, add to the returned dict:

```python
        "rating_repo": SqlAlchemyBloggerRatingRepository(
            session_factory=session_factory
        ),
```

- [ ] **Step 2: Add `blogger_rating_service` to `service_factory.py`**

In the imports, add:

```python
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
```

In `build_offer_dispatch_service`, add `blogger_rating_repo` kwarg:

```python
def build_offer_dispatch_service(
    repos, transaction_manager, currency_symbol="₽"
):
    """Build OfferDispatchService for Kafka consumer."""
    return OfferDispatchService(
        user_repo=repos["user_repo"],
        blogger_repo=repos["blogger_repo"],
        order_repo=repos["order_repo"],
        offer_dispatch_repo=repos["offer_dispatch_repo"],
        country_repo=repos.get("country_repo"),
        interaction_repo=repos["interaction_repo"],
        instagram_stats_repo=repos.get("instagram_stats_repo"),
        manager_order_repo=repos.get("manager_order_repo"),
        transaction_manager=transaction_manager,
        currency_symbol=currency_symbol,
        blogger_rating_repo=repos.get("rating_repo"),
    )
```

In `build_bot_services`, add `blogger_rating_service` to the returned dict and wire `blogger_rating_repo` into `OfferDispatchService`. Find the existing `"offer_dispatch_service"` entry and add the kwarg:

```python
        "offer_dispatch_service": OfferDispatchService(
            user_repo=repos["user_repo"],
            blogger_repo=repos["blogger_repo"],
            order_repo=repos["order_repo"],
            offer_dispatch_repo=repos["offer_dispatch_repo"],
            interaction_repo=repos["interaction_repo"],
            country_repo=repos.get("country_repo"),
            manager_order_repo=repos.get("manager_order_repo"),
            transaction_manager=transaction_manager,
            currency_symbol=config.market.currency_symbol,
            blogger_rating_repo=repos.get("rating_repo"),
        ),
```

Add `blogger_rating_service` and `rating_repo` to the returned dict:

```python
        "blogger_rating_service": BloggerRatingService(
            rating_repo=repos["rating_repo"],
        ),
        "rating_repo": repos["rating_repo"],
```

- [ ] **Step 3: Verify container test still passes**

```bash
uv run pytest tests/unit/test_container.py tests/unit/test_service_factory.py -v
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/container/repository_factory.py \
        src/ugc_bot/container/service_factory.py
git commit -m "feat: wire BloggerRatingRepository and BloggerRatingService into container"
```

---

## Task 11: Integration tests for SQL repository

**Files:**
- Create: `tests/integration/test_blogger_rating_repository.py`

- [ ] **Step 1: Write integration tests**

Create `tests/integration/test_blogger_rating_repository.py`:

```python
"""Integration tests for SqlAlchemyBloggerRatingRepository."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import BloggerRating
from ugc_bot.domain.enums import RaterRole
from ugc_bot.infrastructure.db.repositories.ratings import (
    SqlAlchemyBloggerRatingRepository,
)


def _make_rating(
    blogger_id=None,
    order_id=None,
    rater_id=None,
    score=4,
) -> BloggerRating:
    return BloggerRating(
        rating_id=uuid4(),
        blogger_id=blogger_id or uuid4(),
        order_id=order_id or uuid4(),
        rater_id=rater_id or uuid4(),
        rater_role=RaterRole.MANAGER,
        score=score,
        comment="Test comment",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.integration
async def test_save_and_get_by_blogger_and_order(session_factory):
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    rating = _make_rating()

    await repo.save(rating)
    fetched = await repo.get_by_blogger_and_order(
        rating.blogger_id, rating.order_id
    )

    assert fetched is not None
    assert fetched.rating_id == rating.rating_id
    assert fetched.score == rating.score
    assert fetched.rater_role == RaterRole.MANAGER


@pytest.mark.integration
async def test_get_avg_rating(session_factory):
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    blogger_id = uuid4()

    assert await repo.get_avg_rating(blogger_id) is None

    await repo.save(_make_rating(blogger_id=blogger_id, score=4))
    await repo.save(_make_rating(blogger_id=blogger_id, score=2))

    avg = await repo.get_avg_rating(blogger_id)
    assert avg == pytest.approx(3.0)


@pytest.mark.integration
async def test_list_by_blogger(session_factory):
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    blogger_id = uuid4()

    await repo.save(_make_rating(blogger_id=blogger_id, score=5))
    await repo.save(_make_rating(blogger_id=blogger_id, score=3))

    ratings = await repo.list_by_blogger(blogger_id)
    assert len(ratings) == 2


@pytest.mark.integration
async def test_get_avg_ratings_for_bloggers(session_factory):
    repo = SqlAlchemyBloggerRatingRepository(session_factory=session_factory)
    bid1, bid2 = uuid4(), uuid4()

    await repo.save(_make_rating(blogger_id=bid1, score=5))
    await repo.save(_make_rating(blogger_id=bid2, score=3))

    avgs = await repo.get_avg_ratings_for_bloggers([bid1, bid2, uuid4()])
    assert avgs[bid1] == pytest.approx(5.0)
    assert avgs[bid2] == pytest.approx(3.0)
    assert uuid4() not in avgs  # unknown blogger absent
```

- [ ] **Step 2: Commit**

```bash
git add tests/integration/test_blogger_rating_repository.py
git commit -m "test: add integration tests for SqlAlchemyBloggerRatingRepository"
```

---

## Task 12: Admin panel

**Files:**
- Modify: `src/ugc_bot/admin/app.py`

- [ ] **Step 1: Add `BloggerRatingModel` import**

In the imports block in `admin/app.py`, add to the models import:

```python
from ugc_bot.infrastructure.db.models import (
    ...
    BloggerRatingModel,
)
```

- [ ] **Step 2: Add `BloggerRatingAdmin` view**

Before the function that creates the `Admin` instance, add:

```python
class BloggerRatingAdmin(ModelView, model=BloggerRatingModel):
    """Admin view for blogger ratings."""

    name = "Blogger Rating"
    name_plural = "Blogger Ratings"
    icon = "fa-solid fa-star"
    column_list = [
        BloggerRatingModel.rating_id,
        BloggerRatingModel.blogger_id,
        BloggerRatingModel.order_id,
        BloggerRatingModel.rater_id,
        BloggerRatingModel.rater_role,
        BloggerRatingModel.score,
        BloggerRatingModel.comment,
        BloggerRatingModel.created_at,
    ]
    column_searchable_list = [
        BloggerRatingModel.blogger_id,
        BloggerRatingModel.order_id,
    ]
    column_sortable_list = [
        BloggerRatingModel.score,
        BloggerRatingModel.created_at,
    ]
    can_create = True
    can_edit = True
    can_delete = True
```

- [ ] **Step 3: Register view and expose `min_rating` on orders**

Find where other views are registered with the `admin` object (search for `admin.add_view`) and add:

```python
admin.add_view(BloggerRatingAdmin)
```

Find `OrderAdmin` class in `app.py` and add `min_rating` to `column_list` and `form_columns`:

```python
# In OrderAdmin.column_list, add:
OrderModel.min_rating,

# In OrderAdmin.form_columns (or column_details_list), add:
"min_rating",
```

- [ ] **Step 4: Verify admin app loads**

```bash
uv run python -c "from ugc_bot.admin.app import create_app; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/admin/app.py
git commit -m "feat: add BloggerRatingAdmin view and min_rating to OrderAdmin"
```

---

## Task 13: Telegram bot FSM rating handler

**Files:**
- Create: `src/ugc_bot/bot/telegram/handlers/blogger_rating.py`
- Modify: `src/ugc_bot/telegram_webhook_app.py` (or wherever routers are registered)

- [ ] **Step 1: Create handler file**

Create `src/ugc_bot/bot/telegram/handlers/blogger_rating.py`:

```python
"""Telegram FSM handler for leaving a blogger rating."""

import logging
from uuid import UUID

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from ugc_bot.application.errors import (
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.services.blogger_rating_service import (
    BloggerRatingService,
)
from ugc_bot.domain.enums import RaterRole

router = Router()
logger = logging.getLogger(__name__)

_STAR_BUTTONS = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data="rate:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data="rate:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data="rate:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data="rate:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data="rate:5"),
        ]
    ]
)

_SKIP_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Пропустить", callback_data="rate_skip")]
    ]
)


class RatingStates(StatesGroup):
    """FSM states for blogger rating flow."""

    waiting_score = State()
    waiting_comment = State()


@router.callback_query(lambda c: c.data and c.data.startswith("start_rating:"))
async def start_rating(
    callback: CallbackQuery,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
) -> None:
    """Entry point: callback_data = 'start_rating:<blogger_id>:<order_id>'."""
    _, blogger_id_str, order_id_str = callback.data.split(":", 2)
    await state.update_data(
        blogger_id=blogger_id_str, order_id=order_id_str
    )
    await state.set_state(RatingStates.waiting_score)
    await callback.message.answer(
        "Оцените работу блогера от 1 до 5 звёзд:",
        reply_markup=_STAR_BUTTONS,
    )
    await callback.answer()


@router.callback_query(
    RatingStates.waiting_score,
    lambda c: c.data and c.data.startswith("rate:"),
)
async def handle_score(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Receive score, ask for optional comment."""
    score = int(callback.data.split(":")[1])
    await state.update_data(score=score)
    await state.set_state(RatingStates.waiting_comment)
    await callback.message.answer(
        f"Оценка: {'⭐' * score}\n\nНапишите комментарий или нажмите «Пропустить»:",
        reply_markup=_SKIP_KEYBOARD,
    )
    await callback.answer()


@router.callback_query(
    RatingStates.waiting_comment, lambda c: c.data == "rate_skip"
)
async def handle_skip_comment(
    callback: CallbackQuery,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
) -> None:
    """Save rating without comment."""
    await _save_rating(callback.message, state, blogger_rating_service, comment=None)
    await callback.answer()


@router.message(RatingStates.waiting_comment)
async def handle_comment(
    message: Message,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
) -> None:
    """Save rating with comment text."""
    await _save_rating(message, state, blogger_rating_service, comment=message.text)


async def _save_rating(
    message: Message,
    state: FSMContext,
    blogger_rating_service: BloggerRatingService,
    comment: str | None,
) -> None:
    """Persist the rating and clear FSM state."""
    data = await state.get_data()
    blogger_id = UUID(data["blogger_id"])
    order_id = UUID(data["order_id"])
    score = int(data["score"])
    rater_id = UUID(str(message.from_user.id))  # Telegram user id as UUID seed

    # Determine rater_role from FSM data (set by the caller of start_rating)
    rater_role = RaterRole(data.get("rater_role", RaterRole.MANAGER))

    try:
        await blogger_rating_service.rate_blogger(
            blogger_id=blogger_id,
            order_id=order_id,
            rater_id=rater_id,
            rater_role=rater_role,
            score=score,
            comment=comment,
        )
        await message.answer("✅ Рейтинг сохранён. Спасибо!")
    except RatingAlreadyExistsError:
        await message.answer("❌ Рейтинг для этого заказа уже выставлен.")
    except InvalidRatingScoreError:
        await message.answer("❌ Некорректная оценка. Выберите от 1 до 5.")
    finally:
        await state.clear()
```

**Note on `rater_id`:** The current bot uses `UUID`-based user IDs from the DB, not Telegram IDs. You'll need to look up the `User` entity from `user_repo` using the Telegram `from_user.id`. Update `_save_rating` to receive a `user_repo` parameter and fetch the correct `user_id`. Add `user_repo` to the handler signature using aiogram DI (same pattern as other handlers that receive `user_repo`).

- [ ] **Step 2: Register router in the webhook app**

Find `src/ugc_bot/telegram_webhook_app.py` (or the file where routers are included). Add:

```python
from ugc_bot.bot.telegram.handlers.blogger_rating import router as rating_router

# In the dispatcher setup:
dp.include_router(rating_router)
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from ugc_bot.bot.telegram.handlers.blogger_rating import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/bot/telegram/handlers/blogger_rating.py
git commit -m "feat: add Telegram FSM handler for blogger rating"
```

---

## Task 14: Mini App endpoints

**Files:**
- Modify: `src/ugc_bot/miniapp/api.py`

- [ ] **Step 1: Add Pydantic models and endpoints to `miniapp/api.py`**

Add imports near the top:

```python
from ugc_bot.application.errors import (
    ...
    InvalidRatingScoreError,
    RatingAlreadyExistsError,
)
from ugc_bot.application.services.blogger_rating_service import BloggerRatingService
from ugc_bot.domain.enums import RaterRole
```

Add Pydantic request/response models (in the models section):

```python
class RatingCreateBody(BaseModel):
    """Body for creating a blogger rating."""

    init_data: str = Field(..., description="WebApp.initData string")
    platform: Platform = Field(default="telegram")
    blogger_id: UUID
    order_id: UUID
    score: int = Field(..., ge=1, le=5, description="Rating score 1–5")
    comment: str | None = Field(default=None, max_length=500)


class RatingResponse(BaseModel):
    """Single rating in response."""

    rating_id: UUID
    blogger_id: UUID
    order_id: UUID
    rater_role: str
    score: int
    comment: str | None
    created_at: str


class BloggerRatingListResponse(BaseModel):
    """Response for blogger rating endpoint."""

    avg_rating: float | None
    ratings: list[RatingResponse]
```

Add endpoints (at the end of the router, after existing endpoints):

```python
@router.post("/ratings", status_code=201)
async def create_rating(
    body: RatingCreateBody,
    request: Request,
) -> RatingResponse:
    """Create a rating for a blogger (one per order)."""
    blogger_rating_service: BloggerRatingService = request.app.state.blogger_rating_service
    user_repo = request.app.state.user_repo

    external_id, _ = get_telegram_user_id_and_username(
        validate_init_data_for_platform(body.init_data, body.platform, body.platform)
    )
    user = await user_repo.get_by_external(
        external_id, MessengerType.TELEGRAM
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Determine rater_role from user attributes
    if user.admin:
        rater_role = RaterRole.ADMIN
    else:
        # Simplified: non-admin users are treated as advertiser for mini app
        rater_role = RaterRole.ADVERTISER

    try:
        rating = await blogger_rating_service.rate_blogger(
            blogger_id=body.blogger_id,
            order_id=body.order_id,
            rater_id=user.user_id,
            rater_role=rater_role,
            score=body.score,
            comment=body.comment,
        )
    except RatingAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Rating already exists for this order")
    except InvalidRatingScoreError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return RatingResponse(
        rating_id=rating.rating_id,
        blogger_id=rating.blogger_id,
        order_id=rating.order_id,
        rater_role=str(rating.rater_role),
        score=rating.score,
        comment=rating.comment,
        created_at=rating.created_at.isoformat(),
    )


@router.get("/bloggers/{blogger_id}/rating")
async def get_blogger_rating(
    blogger_id: UUID,
    request: Request,
) -> BloggerRatingListResponse:
    """Get average rating and all ratings for a blogger."""
    blogger_rating_service: BloggerRatingService = request.app.state.blogger_rating_service

    avg = await blogger_rating_service.get_blogger_avg_rating(blogger_id)
    ratings = await blogger_rating_service.get_blogger_ratings(blogger_id)

    return BloggerRatingListResponse(
        avg_rating=avg,
        ratings=[
            RatingResponse(
                rating_id=r.rating_id,
                blogger_id=r.blogger_id,
                order_id=r.order_id,
                rater_role=str(r.rater_role),
                score=r.score,
                comment=r.comment,
                created_at=r.created_at.isoformat(),
            )
            for r in ratings
        ],
    )
```

- [ ] **Step 2: Mount `blogger_rating_service` on `app.state`**

Find where the miniapp FastAPI `app` is created and services are attached to `app.state`. Add:

```python
app.state.blogger_rating_service = services["blogger_rating_service"]
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from ugc_bot.miniapp.api import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/ugc_bot/miniapp/api.py
git commit -m "feat: add POST /ratings and GET /bloggers/{id}/rating mini app endpoints"
```

---

## Task 15: Final check + `make fix`

- [ ] **Step 1: Run full code quality**

```bash
make fix
```

Fix any formatting or lint errors reported.

- [ ] **Step 2: Run all tests**

```bash
make test
```

Expected: all PASS, coverage ≥ 98%.

- [ ] **Step 3: If coverage drops below 98%, add missing tests**

Run:
```bash
uv run pytest --cov=ugc_bot --cov-report=term-missing tests/unit/ tests/integration/ -v
```

Add tests for any uncovered lines in the new files.

- [ ] **Step 4: Commit any fixes**

```bash
git add -p
git commit -m "fix: code quality and coverage after blogger rating feature"
```
