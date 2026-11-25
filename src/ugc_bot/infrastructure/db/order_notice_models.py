"""Idempotent order events and one delivery per destination and event."""

import sqlalchemy as sa

metadata = sa.MetaData()


def order_notice_tables(metadata, prefix):
    events = sa.Table(
        f"{prefix}_events",
        metadata,
        sa.Column("order_id", sa.Uuid, primary_key=True),
        sa.Column("event_kind", sa.String(16), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "expanded", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.CheckConstraint(
            "event_kind IN ('created','paid')", name=f"ck_{prefix}_event_kind"
        ),
    )
    deliveries = sa.Table(
        f"{prefix}_deliveries",
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
            "order_id", "event_kind", "recipient", name=f"uq_{prefix}_recipient"
        ),
        sa.ForeignKeyConstraint(
            ["order_id", "event_kind"],
            [f"{prefix}_events.order_id", f"{prefix}_events.event_kind"],
        ),
        sa.CheckConstraint(
            "state IN ('pending','leased','sending','sent','failed','unknown')",
            name=f"ck_{prefix}_delivery_state",
        ),
    )
    return events, deliveries


ORDER_NOTICE_EVENTS, ORDER_NOTICE_DELIVERIES = order_notice_tables(
    metadata, "order_notice"
)
CONSULTATION_EVENTS, CONSULTATION_DELIVERIES = order_notice_tables(
    sa.MetaData(), "consultation_notice"
)
