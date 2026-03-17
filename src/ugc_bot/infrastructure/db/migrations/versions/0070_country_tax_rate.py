"""Add tax_rate column to countries table."""

import sqlalchemy as sa
from alembic import op

revision = "0070_country_tax_rate"
down_revision = "0069_add_index_offer_dispatches_manager_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "countries",
        sa.Column(
            "tax_rate",
            sa.Numeric(5, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("countries", "tax_rate")
