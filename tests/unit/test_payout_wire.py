"""The payout wire preserves money exactly before JSON loses precision."""

from copy import deepcopy

import pytest


def wire():
    from ugc_bot.miniapp import payout_wire

    return payout_wire


@pytest.mark.parametrize("amount", [2**53 - 1, 2**53, 2**53 + 1, 2**63 - 1])
def test_minor_wire_preserves_53_bit_and_bigint_boundaries(amount):
    adapter = wire()
    assert adapter.parse_minor(str(amount), observed=False) == amount
    assert adapter.parse_minor(amount, observed=False) == amount
    assert adapter.payout_to_wire({"amount_minor": amount}) == {
        "amount_minor": str(amount)
    }


@pytest.mark.parametrize("amount", [None, 0, -1, -(2**63 - 1), 2**63 - 1])
def test_observed_signed_zero_and_null(amount):
    adapter = wire()
    assert (
        adapter.parse_minor(
            None if amount is None else str(amount), observed=True
        )
        == amount
    )


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        1.0,
        "1.0",
        "1e3",
        " 1",
        "1 ",
        "+1",
        "01",
        "-0",
        "١",
        "１",
        "",
        "9223372036854775808",
        "1" * 10000,
        "-9223372036854775808",
    ],
)
@pytest.mark.parametrize("observed", [False, True])
def test_invalid_minor_grammar_is_never_coerced(value, observed):
    with pytest.raises(ValueError, match="payout_amount_invalid"):
        wire().parse_minor(value, observed=observed)


@pytest.mark.parametrize("value", [None, 0, "0", -1, "-1"])
def test_reserve_requires_positive_minor(value):
    with pytest.raises(ValueError, match="payout_amount_invalid"):
        wire().parse_minor(value, observed=False)


def test_nested_money_copy_leaves_versions_and_original_receipt_unchanged():
    original = {
        "version": 2,
        "applied": False,
        "history": [
            {
                "amount_minor": 2**63 - 1,
                "details": {"available_minor": -1, "amount_minor": None},
            }
        ],
        "recipient_details": {"bank_account": "001"},
    }
    before = deepcopy(original)
    reply = wire().payout_to_wire(original)
    assert original == before
    assert reply["version"] == 2 and reply["applied"] is False
    assert reply["history"][0]["amount_minor"] == "9223372036854775807"
    assert reply["history"][0]["details"] == {
        "available_minor": "-1",
        "amount_minor": None,
    }
    assert reply["recipient_details"] == {"bank_account": "001"}
