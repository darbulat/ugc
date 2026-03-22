"""Replace external_id with telegram_id and max_id on users table.

Revision ID: 0081
Revises: 0080
"""

import sqlalchemy as sa
from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add new columns (nullable)
    op.add_column("users", sa.Column("telegram_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("max_id", sa.String(), nullable=True))

    # 2. Migrate data: existing users are all Telegram users
    op.execute(
        "UPDATE users SET telegram_id = external_id"
        " WHERE messenger_type = 'telegram'"
    )
    op.execute(
        "UPDATE users SET max_id = external_id WHERE messenger_type = 'max'"
    )

    # 3. Drop old constraint and index
    op.drop_constraint(
        "users_external_id_messenger_type_key", "users", type_="unique"
    )
    op.drop_index("ix_users_external_messenger_status", table_name="users")

    # 4. Drop old column
    op.drop_column("users", "external_id")

    # 5. Create new unique constraints and indexes
    op.create_unique_constraint(
        "uq_users_telegram_id", "users", ["telegram_id"]
    )
    op.create_unique_constraint("uq_users_max_id", "users", ["max_id"])
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_index("ix_users_max_id", "users", ["max_id"])


def downgrade() -> None:
    # 1. Re-add external_id column
    op.add_column("users", sa.Column("external_id", sa.String(), nullable=True))

    # 2. Restore data
    op.execute(
        "UPDATE users SET external_id = telegram_id"
        " WHERE telegram_id IS NOT NULL"
    )
    op.execute(
        "UPDATE users SET external_id = max_id "
        "WHERE external_id IS NULL AND max_id IS NOT NULL"
    )

    # 3. Make external_id NOT NULL
    op.alter_column("users", "external_id", nullable=False)

    # 4. Drop new constraints/indexes
    op.drop_index("ix_users_max_id", table_name="users")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_constraint("uq_users_max_id", "users", type_="unique")
    op.drop_constraint("uq_users_telegram_id", "users", type_="unique")

    # 5. Drop new columns
    op.drop_column("users", "max_id")
    op.drop_column("users", "telegram_id")

    # 6. Restore old constraint and index
    op.create_unique_constraint(
        "uq_users_external_id_messenger_type",
        "users",
        ["external_id", "messenger_type"],
    )
    op.create_index(
        "ix_users_external_messenger_status",
        "users",
        ["external_id", "messenger_type", "status"],
    )
