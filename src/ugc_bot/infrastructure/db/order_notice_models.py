"""Idempotent order events and one delivery per destination and event."""

import sqlalchemy as sa

metadata = sa.MetaData()
ORDER_NOTICE_EVENTS = sa.Table(
    "order_notice_events",
    metadata,
    sa.Column("order_id", sa.Uuid, primary_key=True),
    sa.Column("event_kind", sa.String(16), primary_key=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "expanded", sa.Boolean, nullable=False, server_default=sa.false()
    ),
    sa.CheckConstraint(
        "event_kind IN ('created','paid')", name="ck_order_notice_event_kind"
    ),
)
ORDER_NOTICE_DELIVERIES = sa.Table(
    "order_notice_deliveries",
    metadata,
    sa.Column("job_id", sa.Uuid, primary_key=True),
    sa.Column("order_id", sa.Uuid, nullable=False),
    sa.Column("event_kind", sa.String(16), nullable=False),
    sa.Column("recipient", sa.String(128), nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("last_error", sa.String(256)),
    sa.UniqueConstraint(
        "order_id", "event_kind", "recipient", name="uq_order_notice_recipient"
    ),
    sa.ForeignKeyConstraint(
        ["order_id", "event_kind"],
        ["order_notice_events.order_id", "order_notice_events.event_kind"],
    ),
    sa.CheckConstraint(
        "state IN ('pending','leased','sending','sent','failed','unknown')",
        name="ck_order_notice_delivery_state",
    ),
)
