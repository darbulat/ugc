"""Manual expenses retain their own group without changing legacy responses."""

from dataclasses import replace
from uuid import UUID

import pytest

from tests.application.services.test_partner_view_service import (
    facts,
    financial,
    view,
)


@pytest.mark.asyncio
async def test_manual_positive_amount_is_separate_from_standard_commissions():
    original = financial()
    basis = replace(
        original.obligations[0],
        obligation_id=UUID(int=99),
        kind="manual_adjustment",
        amount_minor=12345,
        base_minor=12345,
        rate_bps=None,
        rate_source="manual",
    )
    movement = replace(
        original.movements[0],
        movement_id=UUID(int=199),
        movement=replace(
            original.movements[0].movement,
            obligation_id=basis.obligation_id,
            operation_key="manual-positive",
            event_id="manual-positive",
            amount_minor=12345,
        ),
    )
    result = await view(
        replace(
            facts(),
            financial=replace(
                original,
                obligations=(*original.obligations, basis),
                movements=(*original.movements, movement),
                projection=original.projection | {"pending": 87345},
            ),
        )
    )
    money = result["financial"]
    assert money["state"] == "ready"
    assert {g["kind"]: g["balances"]["pending"] for g in money["groups"]} == {
        "client_referral": "5000",
        "creator_referral": "10000",
        "management": "60000",
        "manual_adjustment": "12345",
    }
    assert sum(int(g["balances"]["pending"]) for g in money["groups"]) == 87345
    manual = next(
        e
        for e in money["history"]["entries"]
        if e["kind"] == "manual_adjustment"
    )
    assert manual["rate_bps"] is None and manual["base_minor"] == "12345"
    legacy = (await view(replace(facts(), financial=original)))["financial"]
    assert len(legacy["groups"]) == 3
