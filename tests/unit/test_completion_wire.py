"""Strict commercial fields do not silently coerce financial/user decisions."""

import pytest
from pydantic import ValidationError

from ugc_bot.miniapp.order_intake_api import IntakeTargeting


@pytest.mark.parametrize(
    "values",
    [
        dict(min_age=True),
        dict(min_followers="100"),
        dict(max_age=18.5),
        dict(gender="unknown"),
        dict(min_age=30, max_age=20),
        dict(min_age=121),
        dict(extra="forged"),
        dict(geography="весь мир"),
    ],
)
def test_targeting_wire_rejects_coercion_and_unknown_fields(values):
    with pytest.raises(ValidationError):
        IntakeTargeting.model_validate(values)


def test_targeting_wire_preserves_optional_exact_filters():
    assert IntakeTargeting.model_validate(
        dict(min_followers=1000, gender="f")
    ).model_dump() == dict(
        min_followers=1000,
        max_followers=None,
        min_age=None,
        max_age=None,
        gender="f",
        city=None,
        platforms=[],
        content_usage=None,
        brief_link=None,
        deadlines=None,
    )
