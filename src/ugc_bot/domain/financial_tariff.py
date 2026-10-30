"""Invoice storage and supported tariffs in integer minor units."""

from ugc_bot.domain.financial import MANAGEMENT_REWARD_MINOR

# payments.amount is NUMERIC(10, 2); RUB has 100 minor units per major unit.
MAX_INVOICE_MINOR = 9_999_999_999
MAX_POSITION_COUNT = 200
MAX_POSITION_TOTAL_MINOR = MAX_INVOICE_MINOR // MAX_POSITION_COUNT


def require_invoice_total(total_minor: int) -> None:
    if (
        type(total_minor) is not int
        or not 1 <= total_minor <= MAX_INVOICE_MINOR
    ):
        raise ValueError("invoice_amount_out_of_range")


def require_tariff(selection_minor: int, accompaniment_minor: int) -> None:
    """Every published pair must support the largest fully accompanied order."""
    if (
        type(selection_minor) is not int
        or type(accompaniment_minor) is not int
        or selection_minor < 1
        or accompaniment_minor < MANAGEMENT_REWARD_MINOR
        or selection_minor + accompaniment_minor > MAX_POSITION_TOTAL_MINOR
    ):
        raise ValueError("invalid_policy_tariff")
