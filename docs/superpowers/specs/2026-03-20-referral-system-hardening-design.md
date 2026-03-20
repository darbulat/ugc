# Referral System Hardening — Design Spec

**Date:** 2026-03-20
**Goal:** Five targeted improvements to referral income calculation accuracy, data consistency, and resilience.

---

## 1. Float to Decimal in fallback paths

**Problem:** `_compute_income_from_bindings` and `_compute_income_from_loader` in `referral_stats_service.py` accumulate income via `float`, causing rounding divergence from the primary path (income_entries, which uses `Decimal`).

**Solution:**
- Replace all `float` arithmetic inside `_compute_income_from_bindings`, `_compute_income_from_loader`, and `_income_from_advertiser_orders` with `Decimal`.
- Wrap `effective_rate()` return values in `Decimal(str(...))` at call sites.
- Keep the return type `tuple[float, float, int]` for backward compatibility — convert to `float` only at the return statement via `round(float(...), 2)`.

**Files:** `src/ugc_bot/application/services/referral_stats_service.py`

---

## 2. Currency mixing in aggregate_payout_requests

**Problem:** `aggregate_payout_requests` sums `paid_total` across all currencies into one `float` — meaningless in multi-currency contexts. Used by `_compute_stats` → `UserReferralStats`.

**Solution:**
- Add `paid_by_currency: dict[str, float]` field to `UserReferralStats` dataclass (default `field(default_factory=dict)`).
- In `aggregate_payout_requests`, build a `paid_by_currency` dict alongside the existing `paid_total`.
- Return 4-tuple: `(paid_total, has_pending, has_request_today, paid_by_currency)`.
- Update `_compute_stats` to pass `paid_by_currency` into `UserReferralStats`.
- Mark `paid_total` as deprecated in docstring — callers should migrate to `paid_by_currency`.

**Files:** `src/ugc_bot/application/services/referral_commission.py`, `src/ugc_bot/application/services/referral_stats_service.py`

---

## 3. Reconciliation scheduler for missed income entries

**Problem:** If `record_creator_referral_income` fails (DB timeout, network error), the commission is lost forever — the error is logged but never retried.

**Solution:** Background scheduler following the `feedback_scheduler.py` pattern:

- **New file:** `src/ugc_bot/referral_reconciliation_scheduler.py`
  - `run_once()` — finds orders missing income entries and records them
  - `run_loop()` — calls `run_once` on interval
  - `main()` — entry point with config/container setup

- **New repository method** in `ReferralIncomeEntryRepository`:
  ```
  find_missing_creator_income(limit) -> list[MissingIncomeRow]
  find_missing_advertiser_income(limit) -> list[MissingIncomeRow]
  ```
  SQL: LEFT JOIN `referral_income_entries` on orders that are CLOSED + PAID + OK + have binding but no income entry.

- **New domain entity:** `MissingIncomeRow` dataclass with fields needed to call `ReferralIncomeRecorder`.

- Uses existing `ReferralIncomeRecorder` for writing — idempotent via `ON CONFLICT DO NOTHING`.

- **Config additions** to `AppConfig`:
  - `referral_reconciliation_enabled: bool = False`
  - `referral_reconciliation_interval_seconds: int = 300`

- **Docker:** Add service entry to docker-compose (like existing schedulers).

**Files:** new `referral_reconciliation_scheduler.py`, `application/ports.py`, `infrastructure/db/repositories/referrals.py`, `infrastructure/memory_repositories.py`, `config.py`, `container/`, `docker-compose.yml`

---

## 4. Pre-check before recording income (early exit)

**Problem:** When interaction transitions OK → ISSUE → OK, `record_creator_referral_income` is called again. `ON CONFLICT DO NOTHING` saves correctness, but 4 unnecessary queries (binding, pricing, payment, user) are executed.

**Solution:**
- Add `exists()` method to `ReferralIncomeEntryRepository`:
  ```python
  async def exists(
      self, order_id: UUID, referrer_user_id: UUID, income_type: str,
      session: object | None = None,
  ) -> bool
  ```
  Single `SELECT 1 ... LIMIT 1` query.

- In `ReferralIncomeRecorder.record_creator_referral_income`: after fetching binding, call `exists(order_id, binding.referrer_user_id, "creator")`. If `True`, return immediately.
- Same for `record_advertiser_referral_income`.

**Files:** `application/ports.py`, `infrastructure/db/repositories/referrals.py`, `infrastructure/memory_repositories.py`, `application/services/referral_income_recorder.py`

---

## 5. Race condition — optimistic concurrency (keep current approach)

**Problem:** Window between `has_request_today_by_currency` check and `payout_request_repo.save()` allows duplicate requests.

**Decision:** Keep current optimistic concurrency pattern. The DB unique constraint catches duplicates, and the handler already shows the correct user-facing message on `IntegrityError` (lines 442-452 in `bot/handlers/referral.py`).

**One small improvement:** Log the `IntegrityError` at `info` level instead of letting it propagate as an unhandled error — it is expected behavior, not a bug.

**Files:** `src/ugc_bot/bot/handlers/referral.py`
