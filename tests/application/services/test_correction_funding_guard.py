"""Ordinary forward permission never follows gross amounts alone."""

from dataclasses import replace
from typing import cast
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.correction_ports import CorrectionRepository
from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)
from ugc_bot.domain.corrections import ComponentFunding


class Reader:
    """Declared read-only port double with complete real funding values."""

    def __init__(self, result: object):
        self.result = result
        self.calls: list[tuple[UUID, object]] = []

    async def live_funding(self, paid_item_id, *, session):
        self.calls.append((paid_item_id, session))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def line():
    return ComponentFunding(
        allocation_key="synthetic:captured-selection",
        payment_id=uuid4(),
        paid_item_id=uuid4(),
        component="selection",
        currency="RUB",
        gross_minor=50000,
        cumulative_refund_minor=0,
        net_minor=50000,
    )


def guard(result):
    reader = Reader(result)
    return LiveCorrectionFundingGuard(
        cast(CorrectionRepository, reader)
    ), reader


@pytest.mark.asyncio
async def test_clear_captured_components_allow_forward_without_writes(line):
    accompaniment = replace(
        line,
        component="accompaniment",
        allocation_key="synthetic:captured-accompaniment",
        gross_minor=120000,
        net_minor=120000,
    )
    instance, reader = guard((line, accompaniment))
    session = object()
    await instance.require_forward_clear(line.paid_item_id, session=session)
    assert reader.calls == [(line.paid_item_id, session)]
    assert await instance.load_item(line.paid_item_id, session=session) == (
        line,
        accompaniment,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["case", "observation", "both"])
async def test_unresolved_evidence_denies_forward_without_deducting_gross(
    line, kind
):
    blocked = replace(
        line,
        unresolved_case_ids=(uuid4(),) if kind in ("case", "both") else (),
        unresolved_observation_ids=(uuid4(),)
        if kind in ("observation", "both")
        else (),
    )
    instance, _ = guard((blocked,))
    assert (await instance.load_item(line.paid_item_id, session=object()))[
        0
    ].net_minor == 50000
    with pytest.raises(ValueError, match="^correction_unresolved$"):
        await instance.require_forward_clear(
            line.paid_item_id, session=object()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [1, 50000])
async def test_any_applied_refund_denies_new_forward_entitlement(line, amount):
    instance, _ = guard(
        (
            replace(
                line, cumulative_refund_minor=amount, net_minor=50000 - amount
            ),
        )
    )
    with pytest.raises(ValueError, match="^correction_component_refunded$"):
        await instance.require_forward_clear(
            line.paid_item_id, session=object()
        )


@pytest.mark.asyncio
async def test_inconsistent_state_stays_unknown_instead_of_becoming_zero(line):
    instance, _ = guard(
        (replace(line, state_consistent=False, net_minor=None),)
    )
    assert (await instance.load_item(line.paid_item_id, session=object()))[
        0
    ].net_minor is None
    with pytest.raises(ValueError, match="^correction_funding_unavailable$"):
        await instance.require_forward_clear(
            line.paid_item_id, session=object()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "empty",
        "not_tuple",
        "not_funding",
        "foreign_item",
        "duplicate",
        "mixed_payment",
        "no_selection",
        "unsupported",
        "zero_gross",
    ],
)
async def test_missing_or_mixed_capture_funding_is_unavailable(line, kind):
    variants = {
        "empty": (),
        "not_tuple": [line],
        "not_funding": (None,),
        "foreign_item": (replace(line, paid_item_id=uuid4()),),
        "duplicate": (line, line),
        "mixed_payment": (
            line,
            replace(
                line,
                payment_id=uuid4(),
                allocation_key="synthetic:other-payment",
                component="accompaniment",
            ),
        ),
        "no_selection": (replace(line, component="accompaniment"),),
        "unsupported": (
            line,
            replace(
                line,
                component="management",
                allocation_key="synthetic:not-captured-component",
            ),
        ),
        "zero_gross": (replace(line, gross_minor=0, net_minor=0),),
    }
    instance, _ = guard(variants[kind])
    with pytest.raises(ValueError, match="^correction_funding_unavailable$"):
        await instance.require_forward_clear(
            line.paid_item_id, session=object()
        )


@pytest.mark.asyncio
async def test_database_failure_is_not_hidden_as_clear_funding(line):
    failure = RuntimeError("synthetic unavailable read")
    instance, _ = guard(failure)
    with pytest.raises(RuntimeError) as caught:
        await instance.require_forward_clear(
            line.paid_item_id, session=object()
        )
    assert caught.value is failure


@pytest.mark.asyncio
async def test_invalid_item_identity_is_refused_before_reading(line):
    instance, reader = guard((line,))
    with pytest.raises(ValueError, match="^correction_identity_invalid$"):
        await instance.require_forward_clear(UUID(int=0), session=object())
    assert reader.calls == []
