"""A compact display reference; ownership always uses the full internal ID."""

from uuid import UUID


def public_order_number(order_id: UUID) -> str:
    return "UMC-" + order_id.hex[:8].upper()
