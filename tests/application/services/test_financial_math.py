"""v1 money is independent of legacy float commission arithmetic."""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

import pytest

from ugc_bot.domain.financial import (
    MAX_MINOR,
    commission_minor,
    first_anniversary,
    rate_bps,
    utc,
)


def test_financial_math_boundaries():
    from ugc_bot.domain.financial import (
        commission_minor,
        first_anniversary,
        rate_bps,
    )

    registered = datetime(2024, 2, 29, 12, tzinfo=timezone.utc)
    anniversary = datetime(2025, 2, 28, 12, tzinfo=timezone.utc)
    assert first_anniversary(registered) == anniversary
    assert (
        rate_bps(registered, anniversary, side="creator", verified_count=400)
        == 300
    )
    assert commission_minor(5, 1000, "RUB") == 1


def test_commission_rejects_nonpersistable_minor_basis():
    import pytest

    from ugc_bot.domain.financial import commission_minor

    with pytest.raises(ValueError, match="minor_amount"):
        commission_minor(2**63, 1000, "RUB")


@pytest.mark.parametrize(
    "base", [0, 1, 4, 5, 6, 14, 15, 16, 49999, 50000, MAX_MINOR]
)
@pytest.mark.parametrize("rate", [0, 300, 1000, 1200, 1500, 2000, 10000])
def test_commission_matches_independent_decimal_half_up(base, rate):
    expected = int(
        (Decimal(base) * Decimal(rate) / Decimal(10000)).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )
    result = commission_minor(base, rate, "RUB")
    assert type(result) is int
    assert result == expected


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, 1000),
        (99, 1000),
        (100, 1200),
        (199, 1200),
        (200, 1500),
        (399, 1500),
        (400, 2000),
        (1000000, 2000),
    ],
)
def test_creator_grade_and_utc_first_anniversary(count, expected):
    registered = datetime(2024, 2, 29, 12, tzinfo=timezone.utc)
    boundary = first_anniversary(registered)
    assert (
        rate_bps(
            registered,
            boundary - timedelta(microseconds=1),
            side="creator",
            verified_count=count,
        )
        == expected
    )
    assert (
        rate_bps(registered, boundary, side="creator", verified_count=count)
        == 300
    )
    assert (
        rate_bps(
            registered,
            boundary + timedelta(days=365),
            side="creator",
            verified_count=count,
        )
        == 300
    )
    assert (
        rate_bps(
            registered,
            boundary - timedelta(microseconds=1),
            side="client",
            verified_count=count,
        )
        == 1000
    )


@pytest.mark.parametrize("value", [-1, True, 1.0, Decimal(1), None, "1"])
def test_commission_rejects_ambiguous_minor_basis(value):
    with pytest.raises(ValueError, match="minor_amount"):
        commission_minor(value, 1000, "RUB")


@pytest.mark.parametrize("value", [-1, 10001, True, 1.0, Decimal(1), None])
def test_commission_rejects_ambiguous_rate(value):
    with pytest.raises(ValueError, match="rate_bps"):
        commission_minor(100, value, "RUB")


@pytest.mark.parametrize("currency", [None, "", "USD", "rub", "RUR"])
def test_no_unknown_currency_or_silent_fx(currency):
    with pytest.raises(ValueError, match="currency"):
        commission_minor(100, 1000, currency)


@pytest.mark.parametrize("value", [None, "2026-01-01", datetime(2026, 1, 1)])
def test_missing_or_naive_time_never_becomes_now_or_epoch(value):
    with pytest.raises(ValueError, match="aware_timestamp"):
        utc(value)


@pytest.mark.parametrize("count", [-1, True, 100.0, "100", None])
def test_verified_grade_input_is_not_a_frontend_coercion(count):
    registered = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="verified_count"):
        rate_bps(registered, registered, side="creator", verified_count=count)


def test_unknown_side_and_snapshot_before_registration_fail_closed():
    registered = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="referral_side"):
        rate_bps(registered, registered, side="manager")
    with pytest.raises(ValueError, match="snapshot_before"):
        rate_bps(
            registered, registered - timedelta(microseconds=1), side="client"
        )


def test_rounding_is_per_item_and_full_refund_recognizes_actual_zero():
    assert sum(commission_minor(base, 1000, "RUB") for base in [5, 5]) == 2
    assert commission_minor(10, 1000, "RUB") == 1
    assert commission_minor(0, 1000, "RUB") == 0
