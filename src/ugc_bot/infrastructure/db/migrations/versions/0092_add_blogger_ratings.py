"""Add blogger ratings and min_rating filter on orders."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0092"
down_revision = "0091"


def upgrade() -> None:
    """Create blogger_ratings table and add orders.min_rating."""
    op.add_column(
        "orders",
        sa.Column("min_rating", sa.Numeric(3, 2), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        rater_role_enum = postgresql.ENUM(
            "manager",
            "advertiser",
            "admin",
            name="rater_role",
            create_type=True,
        )
        rater_role_enum.create(bind, checkfirst=True)
        rater_role_column_type: sa.types.TypeEngine = postgresql.ENUM(
            "manager",
            "advertiser",
            "admin",
            name="rater_role",
            create_type=False,
        )
    else:
        rater_role_column_type = sa.Enum(
            "manager",
            "advertiser",
            "admin",
            name="rater_role",
        )

    op.create_table(
        "blogger_ratings",
        sa.Column(
            "rating_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("blogger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rater_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rater_role", rater_role_column_type, nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["blogger_id"],
            ["users.user_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.order_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rater_id"],
            ["users.user_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score"),
        sa.PrimaryKeyConstraint("rating_id"),
        sa.UniqueConstraint(
            "blogger_id",
            "order_id",
            name="uq_blogger_order_rating",
        ),
    )
    op.create_index(
        "ix_blogger_ratings_blogger_id",
        "blogger_ratings",
        ["blogger_id"],
    )
    op.create_index(
        "ix_blogger_ratings_order_id",
        "blogger_ratings",
        ["order_id"],
    )
    op.create_index(
        "ix_blogger_ratings_rater_id",
        "blogger_ratings",
        ["rater_id"],
    )


def downgrade() -> None:
    """Drop blogger_ratings table and orders.min_rating."""
    op.drop_index("ix_blogger_ratings_rater_id", table_name="blogger_ratings")
    op.drop_index("ix_blogger_ratings_order_id", table_name="blogger_ratings")
    op.drop_index("ix_blogger_ratings_blogger_id", table_name="blogger_ratings")
    op.drop_table("blogger_ratings")
    op.drop_column("orders", "min_rating")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("DROP TYPE IF EXISTS rater_role"))
