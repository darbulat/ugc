"""Frozen original rates and cumulative half-up cancellation targets."""

import pytest

from ugc_bot.domain.financial import MAX_MINOR


@pytest.mark.parametrize(
    "base,refunded,rate,want",
    [
        (1_500_000, 250_000, 1000, 25_000),
        (50_000, 0, 1000, 0),
        (50_000, 50_000, 1000, 5000),
        (50_000, 15, 333, 0),
        (50_000, 30, 333, 1),
        (50_000, 50_000, 1750, 8750),
        (50_000, 50_000, 0, 0),
        (MAX_MINOR, MAX_MINOR, 10_000, MAX_MINOR),
        (0, 0, 1000, 0),
    ],
)
def test_cumulative_target_uses_original_gross_minus_remaining_commission(
    base, refunded, rate, want
):
    from ugc_bot.domain.corrections import cumulative_cancellation_target

    assert cumulative_cancellation_target(base, refunded, rate, "RUB") == want


@pytest.mark.parametrize(
    "changes",
    [
        {"base_minor": True},
        {"base_minor": 1.0},
        {"base_minor": -1},
        {"base_minor": MAX_MINOR + 1},
        {"cumulative_refund_minor": True},
        {"cumulative_refund_minor": 1.0},
        {"cumulative_refund_minor": -1},
        {"cumulative_refund_minor": 50_001},
        {"cumulative_refund_minor": MAX_MINOR + 1},
        {"frozen_rate_bps": True},
        {"frozen_rate_bps": 0.1},
        {"frozen_rate_bps": -1},
        {"frozen_rate_bps": 10_001},
        {"currency": "USD"},
    ],
)
def test_cumulative_target_rejects_noninteger_or_unbounded_economics(changes):
    from ugc_bot.domain.corrections import cumulative_cancellation_target

    values = dict(
        base_minor=50_000,
        cumulative_refund_minor=30,
        frozen_rate_bps=333,
        currency="RUB",
    )
    values.update(changes)
    with pytest.raises(ValueError):
        cumulative_cancellation_target(**values)


@pytest.mark.parametrize(
    "refunded,already,pending,want",
    [(15, 0, 1665, 0), (30, 0, 1665, 1), (30, 1, 1664, 0)],
)
def test_source_linked_delta_is_cumulative_and_replay_safe(
    refunded, already, pending, want
):
    from ugc_bot.domain.corrections import pending_cancellation_delta

    assert (
        pending_cancellation_delta(
            50_000,
            refunded,
            333,
            "RUB",
            already_source_linked_cancelled=already,
            pending_minor=pending,
        )
        == want
    )


def test_30_paid_25_delivered_5_full_refunds_only_cancel_original_pending():
    from ugc_bot.domain.corrections import pending_cancellation_delta

    # Hand-derived selection base and original pending: 30 * 50000, 10%.
    delta = pending_cancellation_delta(
        1_500_000,
        250_000,
        1000,
        "RUB",
        already_source_linked_cancelled=0,
        pending_minor=150_000,
    )
    assert delta == 25_000
    assert 1_500_000 - 250_000 == 1_250_000
    assert 150_000 - delta == 125_000


@pytest.mark.parametrize(
    "changes",
    [
        {"already_source_linked_cancelled": True},
        {"already_source_linked_cancelled": -1},
        {"already_source_linked_cancelled": 2},
        {"pending_minor": 1664},
        {"pending_minor": True},
        {"pending_minor": MAX_MINOR + 1},
        {"bucket": "available"},
        {"bucket": "reserved"},
        {"bucket": "paid"},
        {"bucket": "hold"},
        {"bucket": "executing"},
        {"bucket": "unknown"},
    ],
)
def test_delta_refuses_inconsistent_or_nonpending_original_liability(changes):
    from ugc_bot.domain.corrections import pending_cancellation_delta

    values = dict(
        base_minor=50_000,
        cumulative_refund_minor=30,
        frozen_rate_bps=333,
        currency="RUB",
        already_source_linked_cancelled=0,
        pending_minor=1665,
    )
    values.update(changes)
    with pytest.raises(ValueError):
        pending_cancellation_delta(**values)
