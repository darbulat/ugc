# Referral System Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five improvements to referral system: Decimal precision in fallback paths, per-currency payout aggregation, reconciliation scheduler, early-exit pre-check, and info-level logging for expected IntegrityError.

**Architecture:** Mostly modifications to existing services and repositories. One new entry point (reconciliation scheduler). All changes backward-compatible.

**Tech Stack:** Python, SQLAlchemy async, PostgreSQL, pytest-asyncio, Decimal

---

## Task 1: Float → Decimal in fallback paths

**Files:**
- Modify: `src/ugc_bot/application/services/referral_stats_service.py:243-420`
- Test: `tests/application/services/test_referral_income_service.py`

- [ ] **Step 1: Write failing test for Decimal precision in loader path**

Add to `tests/application/services/test_referral_income_service.py`:

```python
@pytest.mark.asyncio
async def test_compute_income_from_loader_uses_decimal_precision() -> None:
    """Loader fallback should produce same result as Decimal arithmetic."""
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock
    from uuid import uuid4

    from ugc_bot.application.services.referral_stats_service import (
        ReferralStatsService,
    )
    from ugc_bot.domain.entities import ReferralOrderIncomeRow
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryOfferDispatchRepository,
        InMemoryOrderRepository,
        InMemoryPaymentRepository,
        InMemoryPayoutRequestRepository,
        InMemoryUserReferralBindingRepository,
        InMemoryUserRepository,
    )

    now = datetime.now(timezone.utc)
    order_id = uuid4()
    # payment_amount=333 / bloggers_needed=3 = 111.0
    # With float: 111.0 * 0.1 = 11.1 (ok here, but edge cases differ)
    # With Decimal: Decimal("333") / 3 * Decimal("0.1") = Decimal("11.1")
    row = ReferralOrderIncomeRow(
        creator_created_at=now - timedelta(days=30),
        order_completed_at=now,
        payment_amount=333.0,
        bloggers_needed=3,
        order_id=order_id,
    )

    loader = MagicMock()
    loader.load_referral_order_income_rows_combined = AsyncMock(return_value=[row])

    service = ReferralStatsService(
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        offer_dispatch_repo=InMemoryOfferDispatchRepository(),
        order_repo=InMemoryOrderRepository(),
        payment_repo=InMemoryPaymentRepository(),
        interaction_repo=MagicMock(),
        user_repo=InMemoryUserRepository(),
        payout_request_repo=InMemoryPayoutRequestRepository(),
        referral_order_income_loader=loader,
    )

    session = MagicMock()
    income_cm, income_total, orders_count = (
        await service._compute_income_from_loader(
            uuid4(), limit=100, now=now, session=session
        )
    )
    # Result should be exactly 11.1, not 11.100000000000001
    assert income_total == 11.1
    assert orders_count == 1
```

- [ ] **Step 2: Run test to verify it passes (or shows float imprecision)**

```bash
uv run pytest tests/application/services/test_referral_income_service.py::test_compute_income_from_loader_uses_decimal_precision -v
```

- [ ] **Step 3: Convert `_compute_income_from_loader` to Decimal arithmetic**

In `src/ugc_bot/application/services/referral_stats_service.py`, replace lines 271-297:

```python
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        income_current_month = Decimal("0")
        income_total = Decimal("0")
        seen_orders: set[UUID] = set()
        for row in rows:
            if not row.bloggers_needed:
                continue
            platform_revenue = Decimal(str(row.payment_amount)) / row.bloggers_needed
            rate = Decimal(str(effective_rate(
                row.creator_created_at,
                row.order_completed_at,
                custom_rate,
            )))
            commission = platform_revenue * rate
            income_total += commission
            seen_orders.add(row.order_id)
            completed_utc = (
                row.order_completed_at
                if row.order_completed_at.tzinfo
                else row.order_completed_at.replace(tzinfo=timezone.utc)
            )
            if (
                completed_utc.month == now_utc.month
                and completed_utc.year == now_utc.year
            ):
                income_current_month += commission
        return (
            round(float(income_current_month), 2),
            round(float(income_total), 2),
            len(seen_orders),
        )
```

- [ ] **Step 4: Convert `_income_from_advertiser_orders` to Decimal arithmetic**

In `src/ugc_bot/application/services/referral_stats_service.py`, replace lines 308-339:

```python
        income_cm = Decimal("0")
        income_tot = Decimal("0")
        seen: set[UUID] = set()
        orders = list(
            await self.order_repo.list_by_advertiser(
                creator_id, session=session
            )
        )
        for order in orders:
            if order.status != OrderStatus.CLOSED:
                continue
            payment = await self.payment_repo.get_by_order(
                order.order_id, session=session
            )
            if payment is None or payment.status != PaymentStatus.PAID:
                continue
            completed_at = order.completed_at or order.created_at
            rate = Decimal(str(effective_rate(creator.created_at, completed_at, custom_rate)))
            commission = Decimal(str(payment.amount)) * rate
            income_tot += commission
            seen.add(order.order_id)
            completed_at_utc = (
                completed_at
                if completed_at.tzinfo
                else completed_at.replace(tzinfo=timezone.utc)
            )
            if (
                completed_at_utc.month == now_utc.month
                and completed_at_utc.year == now_utc.year
            ):
                income_cm += commission
        return round(float(income_cm), 2), round(float(income_tot), 2), seen
```

Note: return type changes from `tuple[float, float, set]` — the `set` stays, but float values are now computed via Decimal.

- [ ] **Step 5: Convert `_compute_income_from_bindings` to Decimal arithmetic**

In `src/ugc_bot/application/services/referral_stats_service.py`, replace lines 349-421:

```python
        income_current_month = Decimal("0")
        income_total = Decimal("0")
        seen_orders: set[UUID] = set()
        now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        for binding in bindings:
            creator_id = binding.referred_user_id
            creator = await self.user_repo.get_by_id(
                creator_id, session=session
            )
            if creator is None:
                continue
            responses = list(
                await self.offer_dispatch_repo.list_responses_by_blogger(
                    creator_id, session=session
                )
            )
            for response in responses:
                if not response.in_offer:
                    continue
                order = await self.order_repo.get_by_id(
                    response.order_id, session=session
                )
                if order is None or order.status != OrderStatus.CLOSED:
                    continue
                payment = await self.payment_repo.get_by_order(
                    order.order_id, session=session
                )
                if payment is None or payment.status != PaymentStatus.PAID:
                    continue
                interaction = await self.interaction_repo.get_by_participants(
                    order_id=order.order_id,
                    blogger_id=creator_id,
                    advertiser_id=order.advertiser_id,
                    session=session,
                )
                if (
                    interaction is None
                    or interaction.status != InteractionStatus.OK
                ):
                    continue
                if order.bloggers_needed <= 0:
                    continue
                completed_at = order.completed_at or order.created_at
                platform_revenue_per_creator = (
                    Decimal(str(payment.amount)) / order.bloggers_needed
                )
                rate = Decimal(str(effective_rate(
                    creator.created_at, completed_at, custom_rate
                )))
                commission = platform_revenue_per_creator * rate
                income_total += commission
                seen_orders.add(order.order_id)
                completed_at_utc = (
                    completed_at
                    if completed_at.tzinfo
                    else completed_at.replace(tzinfo=timezone.utc)
                )
                if (
                    completed_at_utc.month == now_utc.month
                    and completed_at_utc.year == now_utc.year
                ):
                    income_current_month += commission
            cm, tot, adv_seen = await self._income_from_advertiser_orders(
                creator_id, creator, now_utc, session, custom_rate
            )
            income_current_month += Decimal(str(cm))
            income_total += Decimal(str(tot))
            seen_orders |= adv_seen
        return (
            round(float(income_current_month), 2),
            round(float(income_total), 2),
            len(seen_orders),
        )
```

- [ ] **Step 6: Run all referral tests**

```bash
uv run pytest tests/application/services/test_referral_income_service.py -v
```

- [ ] **Step 7: Commit**

```bash
git add src/ugc_bot/application/services/referral_stats_service.py tests/application/services/test_referral_income_service.py
git commit -m "fix: use Decimal arithmetic in referral fallback income paths"
```

---

## Task 2: Per-currency payout aggregation in UserReferralStats

**Files:**
- Modify: `src/ugc_bot/application/services/referral_commission.py:15-26,78-111`
- Modify: `src/ugc_bot/application/services/referral_stats_service.py:500-517`
- Test: `tests/application/services/test_referral_income_service.py`

- [ ] **Step 1: Write failing test for paid_by_currency**

Add to `tests/application/services/test_referral_income_service.py`:

```python
def test_aggregate_payout_requests_returns_paid_by_currency() -> None:
    """aggregate_payout_requests should return per-currency paid breakdown."""
    from ugc_bot.application.services.referral_commission import (
        aggregate_payout_requests,
    )
    from ugc_bot.domain.entities import PayoutRequest
    from ugc_bot.domain.enums import PayoutRequestStatus
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    now = datetime.now(timezone.utc)
    uid = uuid4()
    requests = [
        PayoutRequest(
            request_id=uuid4(),
            user_id=uid,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("100"),
            currency="USD",
        ),
        PayoutRequest(
            request_id=uuid4(),
            user_id=uid,
            requested_at=now,
            status=PayoutRequestStatus.PAID,
            amount=Decimal("5000"),
            currency="RUB",
        ),
    ]
    paid_total, has_pending, has_request_today, paid_by_currency = (
        aggregate_payout_requests(requests, now)
    )
    assert paid_by_currency == {"USD": 100.0, "RUB": 5000.0}
    assert paid_total == 5100.0  # legacy sum
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/application/services/test_referral_income_service.py::test_aggregate_payout_requests_returns_paid_by_currency -v
```

Expected: FAIL (too many values to unpack — 3-tuple vs 4-tuple)

- [ ] **Step 3: Update `aggregate_payout_requests` to return 4-tuple**

In `src/ugc_bot/application/services/referral_commission.py`, replace lines 78-111:

```python
def aggregate_payout_requests(
    requests: list[PayoutRequest],
    now: datetime,
) -> tuple[float, bool, bool, dict[str, float]]:
    """Return (paid_total, has_pending, has_request_today, paid_by_currency).

    WARNING: paid_total sums amounts across all currencies (deprecated).
    Use paid_by_currency for accurate per-currency breakdowns.

    has_request_today: True if ANY currency has a non-cancelled request today.
    For per-currency check use has_request_today_by_currency() repo method.
    """
    paid_total = 0.0
    paid_by_currency: dict[str, float] = {}
    has_pending = False
    has_request_today = False
    now_date = (
        now.date() if now.tzinfo else now.replace(tzinfo=timezone.utc).date()
    )
    for req in requests:
        if req.status == PayoutRequestStatus.CANCELLED:
            continue
        if req.status == PayoutRequestStatus.PENDING:
            has_pending = True
        if req.status == PayoutRequestStatus.PAID and req.amount is not None:
            amt = float(req.amount)
            paid_total += amt
            paid_by_currency[req.currency] = (
                paid_by_currency.get(req.currency, 0.0) + amt
            )
        req_date = (
            req.requested_at.date()
            if req.requested_at.tzinfo
            else req.requested_at.replace(tzinfo=timezone.utc).date()
        )
        if req_date == now_date:
            has_request_today = True
    return (paid_total, has_pending, has_request_today, paid_by_currency)
```

- [ ] **Step 4: Add `paid_by_currency` field to `UserReferralStats`**

In `src/ugc_bot/application/services/referral_commission.py`, replace lines 15-26:

```python
@dataclass(slots=True)
class UserReferralStats:
    """Referrer user statistics (referrals, orders, income, payouts)."""

    creators_count: int
    orders_count: int
    income_current_month: float
    income_total: float
    paid_total: float
    has_pending_payout: bool
    has_request_today: bool
    paid_by_currency: dict[str, float] = field(default_factory=dict)
```

Add `from dataclasses import dataclass, field` at top (replace existing `from dataclasses import dataclass`).

- [ ] **Step 5: Update `_compute_stats` to unpack 4-tuple**

In `src/ugc_bot/application/services/referral_stats_service.py`, replace lines 505-517:

```python
        paid_total, has_pending_payout, has_request_today, paid_by_currency = (
            aggregate_payout_requests(payout_requests, now)
        )

        return UserReferralStats(
            creators_count=creators_count,
            orders_count=orders_count,
            income_current_month=round(income_current_month, 2),
            income_total=round(income_total, 2),
            paid_total=round(paid_total, 2),
            has_pending_payout=has_pending_payout,
            has_request_today=has_request_today,
            paid_by_currency=paid_by_currency,
        )
```

- [ ] **Step 6: Fix existing test `test_aggregate_cancelled_does_not_set_has_request_today`**

This test unpacks 3 values — update to 4:

```python
    paid_total, has_pending, has_request_today, paid_by_currency = (
        aggregate_payout_requests(requests, now)
    )
```

- [ ] **Step 7: Run all referral tests**

```bash
uv run pytest tests/application/services/test_referral_income_service.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/ugc_bot/application/services/referral_commission.py src/ugc_bot/application/services/referral_stats_service.py tests/application/services/test_referral_income_service.py
git commit -m "feat: add per-currency paid breakdown to aggregate_payout_requests"
```

---

## Task 3: Early-exit pre-check in ReferralIncomeRecorder

**Files:**
- Modify: `src/ugc_bot/application/ports.py:994-1028`
- Modify: `src/ugc_bot/infrastructure/db/repositories/referrals.py:382-512`
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py:382-455`
- Modify: `src/ugc_bot/application/services/referral_income_recorder.py`
- Test: `tests/application/services/test_referral_income_service.py`

- [ ] **Step 1: Write failing test for exists() method**

```python
@pytest.mark.asyncio
async def test_income_entry_exists_returns_true_when_present() -> None:
    """exists() should return True when entry already recorded."""
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryReferralIncomeEntryRepository,
    )
    from ugc_bot.domain.entities import ReferralIncomeEntry
    from ugc_bot.domain.enums import ReferralIncomeType
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    repo = InMemoryReferralIncomeEntryRepository()
    referrer_id = uuid4()
    order_id = uuid4()

    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=uuid4(),
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("1000"),
        commission_rate=Decimal("0.10"),
        commission_amount=Decimal("100"),
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(entry)

    assert await repo.exists(order_id, referrer_id, "creator") is True
    assert await repo.exists(order_id, referrer_id, "advertiser") is False
    assert await repo.exists(uuid4(), referrer_id, "creator") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/application/services/test_referral_income_service.py::test_income_entry_exists_returns_true_when_present -v
```

Expected: FAIL — `exists` method does not exist

- [ ] **Step 3: Add `exists()` to abstract port**

In `src/ugc_bot/application/ports.py`, add after the `save` method in `ReferralIncomeEntryRepository` (after line 1001):

```python
    @abstractmethod
    async def exists(
        self,
        order_id: UUID,
        referrer_user_id: UUID,
        income_type: str,
        session: object | None = None,
    ) -> bool:
        """Return True if entry already exists for this order+referrer+type."""
        ...  # pragma: no cover
```

- [ ] **Step 4: Implement `exists()` in SQL repository**

In `src/ugc_bot/infrastructure/db/repositories/referrals.py`, add to `SqlAlchemyReferralIncomeEntryRepository` after `save()` method (after line 413):

```python
    async def exists(
        self,
        order_id: UUID,
        referrer_user_id: UUID,
        income_type: str,
        session: object | None = None,
    ) -> bool:
        """Return True if entry exists for order+referrer+type."""
        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(func.count())
                .select_from(ReferralIncomeEntryModel)
                .where(
                    ReferralIncomeEntryModel.order_id == order_id,
                    ReferralIncomeEntryModel.referrer_user_id == referrer_user_id,
                    ReferralIncomeEntryModel.income_type == income_type,
                )
                .limit(1)
            )
            result = await db_session.execute(stmt)
            return (result.scalar_one() or 0) > 0
```

- [ ] **Step 5: Implement `exists()` in memory repository**

In `src/ugc_bot/infrastructure/memory_repositories.py`, add to `InMemoryReferralIncomeEntryRepository` (after `save()`):

```python
    async def exists(
        self,
        order_id: UUID,
        referrer_user_id: UUID,
        income_type: str,
        session: object | None = None,
    ) -> bool:
        """Return True if entry exists for order+referrer+type."""
        key = (order_id, referrer_user_id, income_type)
        return key in self._seen
```

Note: `_seen` stores `(entry.order_id, entry.referrer_user_id, entry.income_type)` tuples — but `income_type` is `ReferralIncomeType` enum, while `income_type` param is `str`. Need to compare correctly:

```python
    async def exists(
        self,
        order_id: UUID,
        referrer_user_id: UUID,
        income_type: str,
        session: object | None = None,
    ) -> bool:
        """Return True if entry exists for order+referrer+type."""
        for entry in self.entries:
            if (
                entry.order_id == order_id
                and entry.referrer_user_id == referrer_user_id
                and entry.income_type == income_type
            ):
                return True
        return False
```

- [ ] **Step 6: Run test to verify it passes**

```bash
uv run pytest tests/application/services/test_referral_income_service.py::test_income_entry_exists_returns_true_when_present -v
```

- [ ] **Step 7: Add early-exit to `record_creator_referral_income`**

In `src/ugc_bot/application/services/referral_income_recorder.py`, after getting binding (after line 45), add:

```python
        already_recorded = await self.referral_income_entry_repo.exists(
            order.order_id,
            binding.referrer_user_id,
            ReferralIncomeType.CREATOR,
            session=session,
        )
        if already_recorded:
            return
```

- [ ] **Step 8: Add early-exit to `record_advertiser_referral_income`**

After getting binding (after line 109), add:

```python
        already_recorded = await self.referral_income_entry_repo.exists(
            order.order_id,
            binding.referrer_user_id,
            ReferralIncomeType.ADVERTISER,
            session=session,
        )
        if already_recorded:
            return
```

- [ ] **Step 9: Write test for early-exit behavior**

```python
@pytest.mark.asyncio
async def test_record_creator_skips_when_already_exists() -> None:
    """record_creator_referral_income should skip if entry already exists."""
    # Reuse setup from test_record_creator_referral_income_idempotent
    # but verify that user_repo.get_by_id is NOT called on second invocation
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4
    from decimal import Decimal
    from datetime import datetime, timedelta, timezone

    from ugc_bot.application.services.referral_income_recorder import (
        ReferralIncomeRecorder,
    )
    from ugc_bot.domain.entities import (
        ContactPricing,
        Order,
        Payment,
        ReferralIncomeEntry,
        User,
        UserReferralBinding,
    )
    from ugc_bot.domain.enums import (
        OrderStatus,
        PaymentStatus,
        ReferralIncomeType,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryReferralIncomeEntryRepository,
    )

    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    binding = UserReferralBinding(
        referrer_user_id=referrer_id,
        referred_user_id=creator_id,
        created_at=now - timedelta(days=30),
    )
    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        completed_at=now,
    )

    income_repo = InMemoryReferralIncomeEntryRepository()
    # Pre-seed an existing entry
    entry = ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_id,
        referred_user_id=creator_id,
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("100"),
        commission_rate=Decimal("0.10"),
        commission_amount=Decimal("10"),
        created_at=now,
    )
    await income_repo.save(entry)

    binding_repo = AsyncMock()
    binding_repo.get_by_referred_user = AsyncMock(return_value=binding)
    user_repo = AsyncMock()
    # user_repo.get_by_id should NOT be called — early exit before it
    pricing_repo = AsyncMock()
    payment_repo = AsyncMock()

    recorder = ReferralIncomeRecorder(
        user_referral_binding_repo=binding_repo,
        user_repo=user_repo,
        referral_income_entry_repo=income_repo,
        contact_pricing_repo=pricing_repo,
        payment_repo=payment_repo,
    )

    await recorder.record_creator_referral_income(
        order=order, creator_id=creator_id, advertiser_country_code="ru"
    )

    # Early exit: pricing, payment, user repos should NOT be called
    pricing_repo.get_by_bloggers_count.assert_not_called()
    payment_repo.get_by_order.assert_not_called()
    user_repo.get_by_id.assert_not_called()
```

- [ ] **Step 10: Run all referral tests**

```bash
uv run pytest tests/application/services/test_referral_income_service.py -v
```

- [ ] **Step 11: Commit**

```bash
git add src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/db/repositories/referrals.py src/ugc_bot/infrastructure/memory_repositories.py src/ugc_bot/application/services/referral_income_recorder.py tests/application/services/test_referral_income_service.py
git commit -m "perf: early-exit in income recorder when entry already exists"
```

---

## Task 4: Reconciliation scheduler for missed income entries

**Files:**
- Modify: `src/ugc_bot/config.py:572-589`
- Modify: `src/ugc_bot/application/ports.py` (new methods)
- Modify: `src/ugc_bot/infrastructure/db/repositories/referrals.py` (new methods)
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py` (new methods)
- Modify: `src/ugc_bot/container/service_factory.py`
- Modify: `src/ugc_bot/container/__init__.py`
- Create: `src/ugc_bot/referral_reconciliation_scheduler.py`
- Create: `tests/scheduler/test_referral_reconciliation_scheduler.py`
- Modify: `docker-compose.yml`

### Subtask 4a: New domain entity and repository methods

- [ ] **Step 1: Add `MissingReferralIncome` dataclass to domain entities**

In `src/ugc_bot/domain/entities.py`, add after `ReferralOrderIncomeRow` class:

```python
@dataclass(frozen=True)
class MissingReferralIncome:
    """Order that qualifies for referral income but has no entry yet."""

    order_id: UUID
    referred_user_id: UUID
    advertiser_country_code: str
    income_type: str  # 'creator' or 'advertiser'
```

- [ ] **Step 2: Add port methods to `ReferralIncomeEntryRepository`**

In `src/ugc_bot/application/ports.py`, add to `ReferralIncomeEntryRepository` (before the closing of the class):

```python
    @abstractmethod
    async def find_missing_creator_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list[MissingReferralIncome]:
        """Find creator orders with binding but no income entry."""
        ...  # pragma: no cover

    @abstractmethod
    async def find_missing_advertiser_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list[MissingReferralIncome]:
        """Find advertiser orders with binding but no income entry."""
        ...  # pragma: no cover
```

Add `MissingReferralIncome` to imports from domain.entities.

- [ ] **Step 3: Implement SQL queries for finding missing income**

In `src/ugc_bot/infrastructure/db/repositories/referrals.py`, add to `SqlAlchemyReferralIncomeEntryRepository`:

```python
    async def find_missing_creator_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list[MissingReferralIncome]:
        """Find creator orders with binding + CLOSED + PAID + OK but no entry."""
        from ugc_bot.domain.entities import MissingReferralIncome

        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    OrderModel.order_id,
                    InteractionModel.blogger_id.label("referred_user_id"),
                    func.coalesce(UserModel.country, "ru").label(
                        "advertiser_country_code"
                    ),
                )
                .select_from(InteractionModel)
                .join(OrderModel, InteractionModel.order_id == OrderModel.order_id)
                .join(UserModel, OrderModel.advertiser_id == UserModel.user_id)
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserReferralBindingModel,
                    UserReferralBindingModel.referred_user_id
                    == InteractionModel.blogger_id,
                )
                .outerjoin(
                    ReferralIncomeEntryModel,
                    and_(
                        ReferralIncomeEntryModel.order_id == OrderModel.order_id,
                        ReferralIncomeEntryModel.referrer_user_id
                        == UserReferralBindingModel.referrer_user_id,
                        ReferralIncomeEntryModel.income_type == "creator",
                    ),
                )
                .where(
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    InteractionModel.status == InteractionStatus.OK,
                    OrderModel.bloggers_needed > 0,
                    ReferralIncomeEntryModel.entry_id.is_(None),
                )
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            return [
                MissingReferralIncome(
                    order_id=row.order_id,
                    referred_user_id=row.referred_user_id,
                    advertiser_country_code=row.advertiser_country_code,
                    income_type="creator",
                )
                for row in result.all()
            ]

    async def find_missing_advertiser_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list[MissingReferralIncome]:
        """Find advertiser orders with binding + CLOSED + PAID but no entry."""
        from ugc_bot.domain.entities import MissingReferralIncome

        async with _resolve_session(
            self.session_factory, session
        ) as db_session:
            stmt = (
                select(
                    OrderModel.order_id,
                    OrderModel.advertiser_id.label("referred_user_id"),
                    func.coalesce(UserModel.country, "ru").label(
                        "advertiser_country_code"
                    ),
                )
                .select_from(OrderModel)
                .join(UserModel, OrderModel.advertiser_id == UserModel.user_id)
                .join(
                    PaymentModel, OrderModel.order_id == PaymentModel.order_id
                )
                .join(
                    UserReferralBindingModel,
                    UserReferralBindingModel.referred_user_id
                    == OrderModel.advertiser_id,
                )
                .outerjoin(
                    ReferralIncomeEntryModel,
                    and_(
                        ReferralIncomeEntryModel.order_id == OrderModel.order_id,
                        ReferralIncomeEntryModel.referrer_user_id
                        == UserReferralBindingModel.referrer_user_id,
                        ReferralIncomeEntryModel.income_type == "advertiser",
                    ),
                )
                .where(
                    OrderModel.status == OrderStatus.CLOSED,
                    PaymentModel.status == PaymentStatus.PAID,
                    ReferralIncomeEntryModel.entry_id.is_(None),
                )
                .limit(limit)
            )
            result = await db_session.execute(stmt)
            return [
                MissingReferralIncome(
                    order_id=row.order_id,
                    referred_user_id=row.referred_user_id,
                    advertiser_country_code=row.advertiser_country_code,
                    income_type="advertiser",
                )
                for row in result.all()
            ]
```

- [ ] **Step 4: Implement in-memory stubs**

In `src/ugc_bot/infrastructure/memory_repositories.py`, add to `InMemoryReferralIncomeEntryRepository`:

```python
    async def find_missing_creator_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list:
        return []  # Not used in unit tests

    async def find_missing_advertiser_income(
        self,
        limit: int = 100,
        session: object | None = None,
    ) -> list:
        return []  # Not used in unit tests
```

- [ ] **Step 5: Commit repository changes**

```bash
git add src/ugc_bot/domain/entities.py src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/db/repositories/referrals.py src/ugc_bot/infrastructure/memory_repositories.py
git commit -m "feat: add find_missing_*_income repository methods for reconciliation"
```

### Subtask 4b: Config, container, scheduler

- [ ] **Step 6: Add config fields**

In `src/ugc_bot/config.py`, add to `ReferralConfig` (after `referral_stats_limit`):

```python
    referral_reconciliation_enabled: bool = Field(
        default=False,
        alias="REFERRAL_RECONCILIATION_ENABLED",
    )
    referral_reconciliation_interval_seconds: int = Field(
        default=300,
        alias="REFERRAL_RECONCILIATION_INTERVAL_SECONDS",
    )
```

- [ ] **Step 7: Add container method**

In `src/ugc_bot/container/service_factory.py`, add:

```python
def build_referral_reconciliation_deps(config: AppConfig, repos, transaction_manager):
    """Build deps for referral reconciliation scheduler."""
    return {
        "referral_income_entry_repo": repos["referral_income_entry_repo"],
        "order_repo": repos["order_repo"],
        "transaction_manager": transaction_manager,
        "recorder": ReferralIncomeRecorder(
            user_referral_binding_repo=repos["user_referral_binding_repo"],
            user_repo=repos["user_repo"],
            referral_income_entry_repo=repos["referral_income_entry_repo"],
            contact_pricing_repo=repos["pricing_repo"],
            payment_repo=repos["payment_repo"],
        ),
    }
```

Add `ReferralIncomeRecorder` to imports.

In `src/ugc_bot/container/__init__.py`, add:

```python
    def build_referral_reconciliation_deps(self) -> dict:
        """Deps for referral reconciliation scheduler."""
        repos = self.build_repos()
        return service_factory.build_referral_reconciliation_deps(
            self._config, repos, self._transaction_manager
        )
```

- [ ] **Step 8: Create scheduler**

Create `src/ugc_bot/referral_reconciliation_scheduler.py`:

```python
"""Scheduler that reconciles missing referral income entries."""

import asyncio
import logging
from dataclasses import dataclass

from ugc_bot.application.ports import ReferralIncomeEntryRepository
from ugc_bot.application.services.referral_income_recorder import (
    ReferralIncomeRecorder,
)
from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.db.session import with_optional_tx
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


async def run_once(
    income_entry_repo: ReferralIncomeEntryRepository,
    recorder: ReferralIncomeRecorder,
    order_repo,
    transaction_manager,
    batch_limit: int = 100,
) -> int:
    """Find and record missing referral income entries. Return count."""
    recorded = 0

    async def _run(session):
        nonlocal recorded
        missing_creators = await income_entry_repo.find_missing_creator_income(
            limit=batch_limit, session=session
        )
        for m in missing_creators:
            order = await order_repo.get_by_id(m.order_id, session=session)
            if order is None:
                continue
            try:
                await recorder.record_creator_referral_income(
                    order=order,
                    creator_id=m.referred_user_id,
                    advertiser_country_code=m.advertiser_country_code,
                    session=session,
                )
                recorded += 1
            except Exception:
                logger.error(
                    "Failed to reconcile creator income for order %s",
                    m.order_id,
                    exc_info=True,
                )

        missing_advertisers = (
            await income_entry_repo.find_missing_advertiser_income(
                limit=batch_limit, session=session
            )
        )
        for m in missing_advertisers:
            order = await order_repo.get_by_id(m.order_id, session=session)
            if order is None:
                continue
            try:
                await recorder.record_advertiser_referral_income(
                    order=order,
                    advertiser_id=m.referred_user_id,
                    advertiser_country_code=m.advertiser_country_code,
                    session=session,
                )
                recorded += 1
            except Exception:
                logger.error(
                    "Failed to reconcile advertiser income for order %s",
                    m.order_id,
                    exc_info=True,
                )

    await with_optional_tx(transaction_manager, _run)
    if recorded:
        logger.info("Reconciled %d missing referral income entries", recorded)
    return recorded


async def run_loop(
    income_entry_repo: ReferralIncomeEntryRepository,
    recorder: ReferralIncomeRecorder,
    order_repo,
    transaction_manager,
    interval_seconds: int,
    max_iterations: int | None = None,
) -> None:
    """Run periodic reconciliation."""
    install_asyncio_exception_handler("referral-reconciliation")
    iterations = 0
    logger.info("Referral reconciliation scheduler started")
    try:
        while True:
            iterations += 1
            await run_once(
                income_entry_repo, recorder, order_repo, transaction_manager
            )
            if max_iterations is not None and iterations >= max_iterations:
                return
            await asyncio.sleep(interval_seconds)
    finally:
        logger.info(
            "Referral reconciliation scheduler stopped",
            extra={"total_iterations": iterations},
        )


def main() -> None:
    """Entry point for referral reconciliation scheduler."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("referral-reconciliation")
    log_startup_info(
        logger=logger,
        service_name="Referral reconciliation scheduler",
        config=config,
    )

    if not config.referral.referral_reconciliation_enabled:
        logger.info("Referral reconciliation scheduler disabled by config")
        return

    if not config.db.database_url:
        logger.error("DATABASE_URL is required for reconciliation scheduler")
        return

    container = Container(config)
    deps = container.build_referral_reconciliation_deps()

    asyncio.run(
        run_loop(
            income_entry_repo=deps["referral_income_entry_repo"],
            recorder=deps["recorder"],
            order_repo=deps["order_repo"],
            transaction_manager=deps["transaction_manager"],
            interval_seconds=(
                config.referral.referral_reconciliation_interval_seconds
            ),
        )
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Write test for run_once**

Create `tests/scheduler/test_referral_reconciliation_scheduler.py`:

```python
"""Tests for referral reconciliation scheduler."""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from ugc_bot.domain.entities import (
    ContactPricing,
    MissingReferralIncome,
    Order,
    Payment,
    User,
    UserReferralBinding,
)
from ugc_bot.domain.enums import OrderStatus, PaymentStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryReferralIncomeEntryRepository,
)
from ugc_bot.referral_reconciliation_scheduler import run_once


@pytest.mark.asyncio
async def test_run_once_records_missing_creator_income() -> None:
    """run_once should find and record missing creator income."""
    now = datetime.now(timezone.utc)
    referrer_id = uuid4()
    creator_id = uuid4()
    order_id = uuid4()

    missing = MissingReferralIncome(
        order_id=order_id,
        referred_user_id=creator_id,
        advertiser_country_code="ru",
        income_type="creator",
    )

    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[missing])
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])

    order = Order(
        order_id=order_id,
        advertiser_id=uuid4(),
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        completed_at=now,
    )
    order_repo = MagicMock()
    order_repo.get_by_id = AsyncMock(return_value=order)

    recorder = MagicMock()
    recorder.record_creator_referral_income = AsyncMock()
    recorder.record_advertiser_referral_income = AsyncMock()

    # transaction_manager=None → run without tx
    count = await run_once(income_repo, recorder, order_repo, None)

    assert count == 1
    recorder.record_creator_referral_income.assert_called_once_with(
        order=order,
        creator_id=creator_id,
        advertiser_country_code="ru",
        session=None,
    )


@pytest.mark.asyncio
async def test_run_once_no_missing_returns_zero() -> None:
    """run_once should return 0 when nothing is missing."""
    income_repo = MagicMock()
    income_repo.find_missing_creator_income = AsyncMock(return_value=[])
    income_repo.find_missing_advertiser_income = AsyncMock(return_value=[])
    order_repo = MagicMock()
    recorder = MagicMock()

    count = await run_once(income_repo, recorder, order_repo, None)
    assert count == 0
```

- [ ] **Step 10: Run tests**

```bash
uv run pytest tests/scheduler/test_referral_reconciliation_scheduler.py -v
```

- [ ] **Step 11: Add docker-compose service**

In `docker-compose.yml`, add after `role_reminder_scheduler` service:

```yaml
  referral_reconciliation_scheduler:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg://${POSTGRES_USER:-ugc}:${POSTGRES_PASSWORD:-ugc}@pgbouncer:6432/${POSTGRES_DB:-ugc}
    depends_on:
      db:
        condition: service_healthy
      pgbouncer:
        condition: service_started
    command: ["python", "-m", "ugc_bot.referral_reconciliation_scheduler"]
    restart: unless-stopped
```

- [ ] **Step 12: Commit**

```bash
git add src/ugc_bot/config.py src/ugc_bot/container/ src/ugc_bot/referral_reconciliation_scheduler.py tests/scheduler/test_referral_reconciliation_scheduler.py docker-compose.yml src/ugc_bot/domain/entities.py src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/
git commit -m "feat: add referral reconciliation scheduler for missed income entries"
```

---

## Task 5: Info-level logging for expected IntegrityError in payout handler

**Files:**
- Modify: `src/ugc_bot/bot/handlers/referral.py:440-452`

- [ ] **Step 1: Add info-level log for IntegrityError**

In `src/ugc_bot/bot/handlers/referral.py`, replace lines 440-452:

```python
    try:
        await with_optional_tx(transaction_manager, _run)
    except (IntegrityError, ValueError):
        logger.info(
            "Duplicate payout request (expected race condition)",
            extra={
                "user_id": str(user.user_id),
                "currency": currency,
            },
        )
        msg = payout_msgs.get(
            "msg_referral_payout_today_currency",
            payout_msgs.get("msg_referral_payout_today", ""),
        ).format(currency=currency)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg,
            show_alert=True,
        )
        return
```

- [ ] **Step 2: Run handler tests**

```bash
uv run pytest tests/bot/handlers/test_referral.py -v
```

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/bot/handlers/referral.py
git commit -m "fix: log expected IntegrityError in payout handler at info level"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run make fix**

```bash
make fix
```

- [ ] **Step 2: Run make all (CI replica)**

```bash
make all
```

- [ ] **Step 3: Run all referral-related tests**

```bash
uv run pytest tests/application/services/test_referral_income_service.py tests/application/services/test_referral_service.py tests/bot/handlers/test_referral.py tests/scheduler/test_referral_reconciliation_scheduler.py -v
```
