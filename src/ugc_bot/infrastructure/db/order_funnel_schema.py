"""Bounded intake stage observations, containing no brief or contact data."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


def funnel_table(metadata):
    return sa.Table(
        "order_intake_funnel",
        metadata,
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column("funnel_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("stage", sa.String(20), primary_key=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id"),
            unique=True,
        ),
        sa.CheckConstraint(
            "stage IN ('opened','brief','filters','package','created')",
            name="ck_intake_funnel_stage",
        ),
        sa.CheckConstraint(
            "(stage='created')=(order_id IS NOT NULL)",
            name="ck_intake_funnel_created",
        ),
    )
