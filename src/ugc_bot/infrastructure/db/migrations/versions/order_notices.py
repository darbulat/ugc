"""Durable created/paid order notifications, unique per recipient and event."""

from alembic import op

from ugc_bot.infrastructure.db.order_notice_models import metadata

revision = "0124_order_notices"
down_revision = "0123_order_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
