"""Owner and retention facts for private original JPEG attachments."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def image_table(metadata):
    return sa.Table(
        "order_images",
        metadata,
        sa.Column("token", sa.Uuid, primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid,
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("byte_count", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False, index=True
        ),
        sa.Column(
            "order_id",
            sa.Uuid,
            sa.ForeignKey("orders.order_id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.CheckConstraint(
            "byte_count BETWEEN 1 AND 5000000", name="ck_order_image_bytes"
        ),
    )


IMAGES = image_table(Base.metadata)
