"""Allow creators to save links for Dzen, Rutube and another platform."""

from alembic import op

revision = "0134_creator_social_links"
down_revision = "0133_order_position_review"
branch_labels = None
depends_on = None

TABLE = "creator_social_accounts"
CONSTRAINT = "ck_creator_social_platform"
ORIGINAL = "'instagram', 'tiktok', 'youtube', 'telegram', 'vk'"
EXTRA = "'dzen', 'rutube', 'other'"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, f"platform IN ({ORIGINAL}, {EXTRA})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE")
    if bind.exec_driver_sql(
        f"SELECT 1 FROM {TABLE} WHERE platform IN ({EXTRA}) LIMIT 1"
    ).first():
        raise RuntimeError("creator_social_links_exist")
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(CONSTRAINT, TABLE, f"platform IN ({ORIGINAL})")
