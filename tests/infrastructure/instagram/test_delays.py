"""Tests for Instagram random delay helper."""

from ugc_bot.infrastructure.instagram.delays import random_delay_seconds


def test_random_delay_seconds_in_range() -> None:
    """random_delay_seconds is within base*min_factor and base*max_factor."""
    base = 2.0
    min_factor = 0.6
    max_factor = 1.6
    for _ in range(50):
        delay = random_delay_seconds(base, min_factor, max_factor)
        assert delay >= base * min_factor
        assert delay <= base * max_factor


def test_random_delay_seconds_minimum_floor() -> None:
    """random_delay_seconds never returns below 0.1."""
    for _ in range(30):
        delay = random_delay_seconds(0.01, 0.5, 1.0)
        assert delay >= 0.1


def test_random_delay_seconds_default_factors() -> None:
    """With default factors, delay is within 0.6*base and 1.6*base."""
    base = 1.0
    for _ in range(30):
        delay = random_delay_seconds(base)
        assert 0.6 <= delay <= 1.6
        assert delay >= 0.1
