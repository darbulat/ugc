"""Add manager_orders table, round robin index, manager_id."""

import sqlalchemy as sa
from alembic import op

revision = "0068_add_manager_orders"
down_revision = "0067_add_languages_kk_be_uz"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_orders",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.user_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.order_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "order_id"),
    )
    op.add_column(
        "orders",
        sa.Column(
            "last_round_robin_index",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "offer_dispatches",
        sa.Column("manager_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_offer_dispatches_manager_id_users",
        "offer_dispatches",
        "users",
        ["manager_id"],
        ["user_id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_offer_dispatches_manager_id_users",
        "offer_dispatches",
        type_="foreignkey",
    )
    op.drop_column("offer_dispatches", "manager_id")
    op.drop_column("orders", "last_round_robin_index")
    op.drop_table("manager_orders")
