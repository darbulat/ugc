"""Add file_ids to complaints and admin flag to users."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_add_complaint_file_ids_user_admin"
down_revision = "0020_rename_contacts_sent_at_to_completed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add file_ids column to complaints and admin column to users."""
    op.add_column(
        "complaints",
        sa.Column("file_ids", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("admin", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    """Remove file_ids from complaints and admin from users."""
    op.drop_column("complaints", "file_ids")
    op.drop_column("users", "admin")
