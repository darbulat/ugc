"""Private owner-scoped order image metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0123_order_images"
down_revision = "0122_advertiser_ratings"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE order_type ADD VALUE IF NOT EXISTS 'stories'")
    op.create_table(
        "order_images",
        sa.Column("token", sa.Uuid, primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid,
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("byte_count", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "order_id",
            sa.Uuid,
            sa.ForeignKey("orders.order_id", ondelete="RESTRICT"),
        ),
        sa.CheckConstraint(
            "byte_count BETWEEN 1 AND 5000000", name="ck_order_image_bytes"
        ),
    )
    for field in ("owner_id", "expires_at", "order_id"):
        op.create_index(f"ix_order_images_{field}", "order_images", [field])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM order_images")):
        raise RuntimeError("order_image_history_exists")
    op.drop_table("order_images")
