"""Extend alembic_version.version_num to VARCHAR(64) for long revision IDs."""

from alembic import op

revision = "0014_extend_alembic_version_col"
down_revision = "0014_bloggers_needed_3_5_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow longer revision IDs (default VARCHAR(32) is too short)."""
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")


def downgrade() -> None:
    """Restore version_num to VARCHAR(32)."""
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)")
