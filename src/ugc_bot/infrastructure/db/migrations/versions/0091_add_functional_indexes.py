"""Add functional indexes for case-insensitive lookups.

- ix_users_telegram_lower: supports get_by_telegram() with func.lower()
- ix_blogger_profiles_instagram_username_lower: supports lookups by username

Revision ID: 0091
Revises: 0090
"""

from alembic import op
from sqlalchemy import text

revision = "0091"
down_revision = "0090"


def upgrade() -> None:
    op.create_index(
        "ix_users_telegram_lower",
        "users",
        [text("lower(telegram)")],
        postgresql_where=text("telegram IS NOT NULL"),
    )
    op.create_index(
        "ix_blogger_profiles_ig_username_lower",
        "blogger_profiles",
        [text("lower(instagram_username)")],
        postgresql_where=text("instagram_username IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_blogger_profiles_ig_username_lower", "blogger_profiles")
    op.drop_index("ix_users_telegram_lower", "users")
