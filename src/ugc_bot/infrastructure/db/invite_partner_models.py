"""The partner selected by staff is independent of the working manager."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def partner_table(metadata):
    return sa.Table(
        "order_creator_invite_partners",
        metadata,
        sa.Column(
            "invite_id",
            sa.Uuid(),
            sa.ForeignKey("order_creator_invites.id"),
            primary_key=True,
        ),
        sa.Column(
            "referrer_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
    )


PARTNERS = partner_table(Base.metadata)
