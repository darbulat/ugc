"""Tests for age range parsing helper."""

from __future__ import annotations

import pytest

from ugc_bot.bot.handlers.blogger_registration import _parse_age_range


def test_parse_age_range_success() -> None:
    """Parse a valid age range."""

    assert _parse_age_range("18-35") == (18, 35)


@pytest.mark.parametrize("value", ["", "18", "35-", "a-b", "40-30"])
def test_parse_age_range_invalid(value: str) -> None:
    """Reject invalid age range inputs."""

    with pytest.raises(ValueError):
        _parse_age_range(value)
