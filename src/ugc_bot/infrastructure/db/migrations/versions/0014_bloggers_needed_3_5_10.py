"""Update bloggers_needed constraint to allow 3, 5, 10 (match app UI)."""

from alembic import op

revision = "0014_bloggers_needed_3_5_10"
down_revision = "0013_nps_and_blogger_mark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Change bloggers_needed from (3,10,20,30,50) to (3,5,10)."""

    op.drop_constraint("orders_bloggers_needed_check", "orders", type_="check")


def downgrade() -> None:
    """Restore bloggers_needed to (3,10,20,30,50)."""

    op.create_check_constraint(
        "orders_bloggers_needed_check",
        "orders",
        "bloggers_needed IN (3, 10, 20, 30, 50)",
    )

    op.execute("DELETE FROM contact_pricing WHERE bloggers_count = 5")
