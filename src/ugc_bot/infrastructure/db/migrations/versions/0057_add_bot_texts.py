"""Add bot_texts table for localized bot messages."""

import sqlalchemy as sa
from alembic import op

revision = "0057_add_bot_texts"
down_revision = "0056_drop_orders_radius_km"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create bot_texts table (key, locale, value)."""
    op.create_table(
        "bot_texts",
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", "locale"),
    )


def downgrade() -> None:
    """Drop bot_texts table."""
    op.drop_table("bot_texts")
