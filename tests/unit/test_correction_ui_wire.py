"""Exact wire values cannot turn backend corruption into public money."""

import pytest

from ugc_bot.miniapp.correction_wire import (
    correction_to_wire,
    parse_observed_minor,
    public_correction_code,
)


@pytest.mark.parametrize(
    "value",
    [
        True,
        1,
        1.5,
        {},
        "00",
        "-0",
        "1e3",
        "9223372036854775808",
        "-9223372036854775809",
    ],
)
def test_observed_input_requires_bounded_canonical_decimal_string(value):
    with pytest.raises(ValueError, match="correction_observed_minor_invalid"):
        parse_observed_minor(value)


@pytest.mark.parametrize(
    "value", [True, 0.1, "1.0", "01", 9223372036854775808, -9223372036854775809]
)
def test_invalid_nested_backend_money_never_leaves_as_numeric_or_text(value):
    with pytest.raises(ValueError, match="correction_source_unavailable"):
        correction_to_wire({"history": [{"amount_minor": value}]})


def test_wire_preserves_exact_signed_values_and_hides_unknown_blocker():
    assert correction_to_wire(
        {
            "amount_minor": "9007199254740993",
            "nested": ({"gross_minor": 50000}, {"amount_minor": None}),
            "blockers": ["PRIVATE:raw-source"],
        }
    ) == {
        "amount_minor": "9007199254740993",
        "nested": [{"gross_minor": "50000"}, {"amount_minor": None}],
        "blockers": ["correction_unavailable"],
    }
    assert (
        public_correction_code(ValueError("PRIVATE"))
        == "correction_unavailable"
    )
