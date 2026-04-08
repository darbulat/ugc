"""Add functional indexes for case-insensitive lookups.

- ix_users_telegram_lower: supports get_by_telegram() with func.lower()
- ix_blogger_profiles_instagram_username_lower: supports lookups by username

Revision ID: 0091
Revises: 0090
"""

from alembic import op

revision = "0091"
down_revision = "0090"


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_telegram_lower "
        "ON users (lower(telegram)) WHERE telegram IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_blogger_profiles_ig_username_lower "
        "ON blogger_profiles (lower(instagram_username)) "
        "WHERE instagram_username IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_blogger_profiles_ig_username_lower")
    op.execute("DROP INDEX IF EXISTS ix_users_telegram_lower")
