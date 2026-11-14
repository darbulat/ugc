"""Order-specific invitation and recorded consent for manual selections."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def invite_table(metadata):
    return sa.Table(
        "order_creator_invites",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            sa.Uuid(),
            sa.ForeignKey("order_items.paid_item_id"),
            nullable=False,
        ),
        sa.Column("manager_id", sa.Uuid(), sa.ForeignKey("users.user_id")),
        sa.Column("target_id", sa.Uuid(), sa.ForeignKey("users.user_id")),
        sa.Column("instagram", sa.String(30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True)),
        sa.Column("creator_id", sa.Uuid(), sa.ForeignKey("users.user_id")),
        sa.Column(
            "interest_id",
            sa.Uuid(),
            sa.ForeignKey("paid_selection_interests.interest_id"),
            unique=True,
        ),
        sa.CheckConstraint(
            "(consented_at IS NULL AND creator_id IS NULL "
            "AND interest_id IS NULL) OR "
            "(consented_at IS NOT NULL AND creator_id IS NOT NULL "
            "AND interest_id IS NOT NULL)",
            name="ck_order_creator_invite_consent",
        ),
        sa.Index("ix_order_creator_invite_order", "order_id"),
    )


# A pre-0134 scheduler has no invitation filter. The separate pending state
# also keeps manual contacts out of that worker during a rolling deployment.
MANUAL_READY = "card_ready"


INVITES = invite_table(Base.metadata)
