"""Private invitation preferences and evidence for manual contacts."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base

metadata = Base.metadata
SHARING = sa.Table(
    "order_invite_contact_sharing",
    metadata,
    sa.Column(
        "order_id", sa.Uuid, sa.ForeignKey("orders.order_id"), primary_key=True
    ),
    sa.Column(
        "client_id", sa.Uuid, sa.ForeignKey("users.user_id"), nullable=False
    ),
    sa.Column("enabled", sa.Boolean, nullable=False),
)
VISITS = sa.Table(
    "order_creator_invite_visits",
    metadata,
    sa.Column(
        "invite_id",
        sa.Uuid,
        sa.ForeignKey("order_creator_invites.id"),
        primary_key=True,
    ),
    sa.Column(
        "user_id", sa.Uuid, sa.ForeignKey("users.user_id"), primary_key=True
    ),
    sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
)
NOTICES = sa.Table(
    "order_creator_invite_notices",
    metadata,
    sa.Column(
        "invite_id",
        sa.Uuid,
        sa.ForeignKey("order_creator_invites.id"),
        primary_key=True,
    ),
    sa.Column("kind", sa.String(12), primary_key=True),
    sa.Column("state", sa.String(12), nullable=False),
    sa.CheckConstraint("kind IN ('creator', 'customer')"),
    sa.CheckConstraint("state IN ('sending', 'sent', 'failed', 'unknown')"),
)
STAFF_DELIVERIES = sa.Table(
    "order_invite_staff_deliveries",
    metadata,
    sa.Column(
        "paid_item_id",
        sa.Uuid,
        sa.ForeignKey("order_items.paid_item_id"),
        primary_key=True,
    ),
    sa.Column(
        "delivery_id",
        sa.Uuid,
        sa.ForeignKey("order_creator_invites.id"),
        unique=True,
        nullable=False,
    ),
    sa.Column(
        "order_id", sa.Uuid, sa.ForeignKey("orders.order_id"), nullable=False
    ),
    sa.Column(
        "payment_id",
        sa.Uuid,
        sa.ForeignKey("payments.payment_id"),
        nullable=False,
    ),
    sa.Column(
        "client_id", sa.Uuid, sa.ForeignKey("users.user_id"), nullable=False
    ),
    sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
)
