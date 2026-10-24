"""Exact payout transport; stored/domain integers never become wire floats."""

import re

from ugc_bot.domain.financial import MAX_MINOR


def parse_minor(value: object, *, observed: bool) -> int | None:
    if value is None and observed:
        return None
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(
        r"(?:0|-?[1-9][0-9]*)" if observed else r"[1-9][0-9]*", value
    ):
        # Bound before int conversion; avoid unbounded digit/CPU input.
        if len(value.lstrip("-")) > 19:
            raise ValueError("payout_amount_invalid")
        number = int(value)
    else:
        raise ValueError("payout_amount_invalid")
    if not (
        -MAX_MINOR <= number <= MAX_MINOR
        if observed
        else 0 < number <= MAX_MINOR
    ):
        raise ValueError("payout_amount_invalid")
    return number


def payout_to_wire(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: str(item)
            if key.endswith("_minor") and type(item) is int
            else payout_to_wire(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [payout_to_wire(item) for item in value]
    return value
