"""Operational ownership and staff notice history for paid positions."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def order_review_tables(metadata):
    owners = sa.Table(
        "order_review_owners",
        metadata,
        sa.Column(
            "paid_item_id",
            sa.Uuid(),
            sa.ForeignKey("order_items.paid_item_id"),
            primary_key=True,
        ),
        sa.Column(
            "manager_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
    )
    alerts = sa.Table(
        "order_review_alerts",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(10), nullable=False),
        sa.Column(
            "recipient_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("provider_reference", sa.String(100)),
        sa.UniqueConstraint(
            "order_id",
            "deadline",
            "stage",
            "recipient_id",
            name="uq_order_review_alert_recipient",
        ),
        sa.CheckConstraint(
            "stage IN ('upcoming','overdue')", name="ck_order_review_stage"
        ),
        sa.CheckConstraint(
            "state IN ('ready','sending','accepted','failed',"
            "'unknown','obsolete')",
            name="ck_order_review_delivery",
        ),
        sa.CheckConstraint(
            "(state='accepted') = (provider_reference IS NOT NULL)",
            name="ck_order_review_receipt",
        ),
        sa.Index("ix_order_review_alert_ready", "state", "ready_at"),
    )
    return owners, alerts


OWNERS, ALERTS = order_review_tables(Base.metadata)
