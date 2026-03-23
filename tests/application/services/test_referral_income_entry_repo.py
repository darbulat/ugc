"""Tests for InMemoryReferralIncomeEntryRepository."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from ugc_bot.domain.entities import ReferralIncomeEntry
from ugc_bot.domain.enums import ReferralIncomeType
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryReferralIncomeEntryRepository,
)


def _make_entry(
    *,
    referrer_user_id=None,
    referred_user_id=None,
    order_id=None,
    income_type=ReferralIncomeType.CREATOR,
    currency="RUB",
    commission_amount=Decimal("100.00"),
    created_at=None,
) -> ReferralIncomeEntry:
    return ReferralIncomeEntry(
        entry_id=uuid4(),
        referrer_user_id=referrer_user_id or uuid4(),
        referred_user_id=referred_user_id or uuid4(),
        order_id=order_id or uuid4(),
        income_type=income_type,
        currency=currency,
        platform_revenue=Decimal("1000.00"),
        commission_rate=Decimal("0.1000"),
        commission_amount=commission_amount,
        created_at=created_at or datetime.now(tz=timezone.utc),
    )


@pytest.mark.asyncio
async def test_save_and_get_totals_by_currency() -> None:
    """Save entries in RUB and GEL, verify totals grouped by currency."""
    repo = InMemoryReferralIncomeEntryRepository()
    uid = uuid4()

    await repo.save(
        _make_entry(
            referrer_user_id=uid,
            currency="RUB",
            commission_amount=Decimal("100.00"),
        )
    )
    await repo.save(
        _make_entry(
            referrer_user_id=uid,
            currency="RUB",
            commission_amount=Decimal("50.00"),
        )
    )
    await repo.save(
        _make_entry(
            referrer_user_id=uid,
            currency="GEL",
            commission_amount=Decimal("30.00"),
        )
    )

    totals = await repo.get_totals_by_currency(uid)

    assert totals == {"RUB": Decimal("150.00"), "GEL": Decimal("30.00")}


@pytest.mark.asyncio
async def test_save_idempotent_on_conflict() -> None:
    """Duplicate key is silently ignored."""
    repo = InMemoryReferralIncomeEntryRepository()
    uid = uuid4()
    oid = uuid4()
    referred = uuid4()

    entry1 = _make_entry(
        referrer_user_id=uid,
        referred_user_id=referred,
        order_id=oid,
        income_type=ReferralIncomeType.CREATOR,
        commission_amount=Decimal("100.00"),
    )
    entry2 = _make_entry(
        referrer_user_id=uid,
        referred_user_id=referred,
        order_id=oid,
        income_type=ReferralIncomeType.CREATOR,
        commission_amount=Decimal("999.00"),
    )

    await repo.save(entry1)
    await repo.save(entry2)

    totals = await repo.get_totals_by_currency(uid)
    assert totals == {"RUB": Decimal("100.00")}


@pytest.mark.asyncio
async def test_get_orders_count_by_currency() -> None:
    """Count distinct order_ids by currency."""
    repo = InMemoryReferralIncomeEntryRepository()
    uid = uuid4()

    oid1, oid2, oid3 = uuid4(), uuid4(), uuid4()
    await repo.save(
        _make_entry(referrer_user_id=uid, order_id=oid1, currency="RUB")
    )
    await repo.save(
        _make_entry(referrer_user_id=uid, order_id=oid2, currency="RUB")
    )
    await repo.save(
        _make_entry(referrer_user_id=uid, order_id=oid3, currency="GEL")
    )

    counts = await repo.get_orders_count_by_currency(uid)
    assert counts == {"RUB": 2, "GEL": 1}


@pytest.mark.asyncio
async def test_get_current_month_totals_by_currency() -> None:
    """Only current month entries are counted."""
    repo = InMemoryReferralIncomeEntryRepository()
    uid = uuid4()

    now = datetime.now(tz=timezone.utc)
    last_month = now - timedelta(days=40)

    await repo.save(
        _make_entry(
            referrer_user_id=uid,
            currency="RUB",
            commission_amount=Decimal("200.00"),
            created_at=now,
        )
    )
    await repo.save(
        _make_entry(
            referrer_user_id=uid,
            currency="RUB",
            commission_amount=Decimal("500.00"),
            created_at=last_month,
        )
    )

    monthly = await repo.get_current_month_totals_by_currency(uid)
    assert monthly == {"RUB": Decimal("200.00")}
