"""Strict requested-service command validation before transactional writes."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest


def values():
    return dict(
        client_id=uuid4(),
        operation_key="click-1",
        policy_version="policy:v1",
        product_link="https://example.test/product",
        offer_text="brief",
        honorarium=Decimal("999.00"),
        contact_reference="client contact",
        selection_due_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
        service_mode="self_service",
    )


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"client_id": UUID(int=0)}, "client_identity"),
        ({"operation_key": " "}, "intake_provenance"),
        ({"operation_key": "x" * 257}, "intake_provenance"),
        ({"policy_version": " "}, "intake_provenance"),
        ({"contact_reference": " "}, "intake_provenance"),
        ({"service_mode": "pick-manager-id"}, "service_mode"),
        ({"accompaniment_ordinals": frozenset({1})}, "self_service"),
        (
            {
                "service_mode": "with_manager",
                "accompaniment_ordinals": frozenset(),
            },
            "accompaniment",
        ),
        (
            {
                "service_mode": "with_manager",
                "accompaniment_ordinals": frozenset({0}),
            },
            "accompaniment",
        ),
        (
            {
                "service_mode": "with_manager",
                "accompaniment_ordinals": frozenset({31}),
            },
            "accompaniment",
        ),
        (
            {
                "service_mode": "with_manager",
                "accompaniment_ordinals": frozenset({True}),
            },
            "accompaniment",
        ),
        ({"honorarium": Decimal("NaN")}, "honorarium"),
        ({"honorarium": Decimal("Infinity")}, "honorarium"),
        ({"honorarium": Decimal("-1")}, "honorarium"),
        ({"honorarium": Decimal("1.234")}, "honorarium"),
        ({"honorarium": "not-a-number"}, "honorarium"),
        ({"selection_due_at": datetime(2026, 10, 25)}, "aware"),
    ],
)
def test_invalid_intake_never_produces_an_ambiguous_command(changes, reason):
    from ugc_bot.domain.order_intake import OrderIntakeCommand

    with pytest.raises(ValueError, match=reason):
        OrderIntakeCommand(**(values() | changes))


def test_normalized_equivalent_click_has_same_economic_hash():
    from ugc_bot.domain.order_intake import OrderIntakeCommand

    first_values = values()
    original = OrderIntakeCommand(**first_values)
    changed = OrderIntakeCommand(
        **(
            first_values
            | dict(
                honorarium=Decimal("999"),
                operation_key=" click-1 ",
                contact_reference=" client contact ",
                selection_due_at=first_values["selection_due_at"].astimezone(
                    timezone(timedelta(hours=3))
                ),
            )
        )
    )
    assert original.payload_hash == changed.payload_hash
    assert original.request_id == changed.request_id
    assert original.order_id == changed.order_id
