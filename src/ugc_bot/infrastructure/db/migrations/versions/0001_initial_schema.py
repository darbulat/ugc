"""Initial schema for UGC bot."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""

    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    messenger_type = postgresql.ENUM(
        "telegram", "max", "whatsapp", name="messenger_type"
    )
    user_role = postgresql.ENUM("blogger", "advertiser", "both", name="user_role")
    user_status = postgresql.ENUM("active", "pause", "blocked", name="user_status")
    audience_gender = postgresql.ENUM("m", "f", "all", name="audience_gender")
    order_status = postgresql.ENUM("new", "active", "closed", name="order_status")
    interaction_status = postgresql.ENUM(
        "ok", "no_deal", "issue", name="interaction_status"
    )
    complaint_status = postgresql.ENUM(
        "pending", "reviewed", "dismissed", "action_taken", name="complaint_status"
    )

    for enum_type in (
        messenger_type,
        user_role,
        user_status,
        audience_gender,
        order_status,
        interaction_status,
        complaint_status,
    ):
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column(
            "messenger_type",
            postgresql.ENUM(
                "telegram",
                "max",
                "whatsapp",
                name="messenger_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "blogger", "advertiser", "both", name="user_role", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active", "pause", "blocked", name="user_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("external_id", "messenger_type"),
    )

    op.create_table(
        "blogger_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("instagram_url", sa.String(), nullable=False, unique=True),
        sa.Column(
            "confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("topics", postgresql.JSONB(), nullable=False),
        sa.Column(
            "audience_gender",
            postgresql.ENUM("m", "f", "all", name="audience_gender", create_type=False),
            nullable=False,
        ),
        sa.Column("audience_age_min", sa.Integer(), nullable=False),
        sa.Column("audience_age_max", sa.Integer(), nullable=False),
        sa.Column("audience_geo", sa.String(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("price > 0"),
        sa.CheckConstraint("audience_age_max >= audience_age_min"),
    )

    op.create_table(
        "advertiser_profiles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("contact", sa.String(), nullable=False),
    )

    op.create_table(
        "orders",
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "advertiser_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_link", sa.String(), nullable=False),
        sa.Column("offer_text", sa.Text(), nullable=False),
        sa.Column("ugc_requirements", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("bloggers_needed", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "new", "active", "closed", name="order_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("contacts_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("price > 0"),
        sa.CheckConstraint("bloggers_needed IN (3, 10, 20, 30, 50)"),
    )

    op.create_table(
        "order_responses",
        sa.Column(
            "response_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blogger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "responded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("order_id", "blogger_id"),
    )

    op.create_table(
        "interactions",
        sa.Column(
            "interaction_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "blogger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "advertiser_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "ok", "no_deal", "issue", name="interaction_status", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("from_advertiser", sa.Text(), nullable=True),
        sa.Column("from_blogger", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "instagram_verification_codes",
        sa.Column(
            "code_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "complaints",
        sa.Column(
            "complaint_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "reporter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reported_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "reviewed",
                "dismissed",
                "action_taken",
                name="complaint_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_users_external_messenger_status",
        "users",
        ["external_id", "messenger_type", "status"],
    )
    op.create_index(
        "ix_orders_advertiser_status", "orders", ["advertiser_id", "status"]
    )
    op.create_index(
        "ix_orders_active",
        "orders",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_order_responses_order_id", "order_responses", ["order_id"])
    op.create_index("ix_order_responses_blogger_id", "order_responses", ["blogger_id"])
    op.create_index("ix_interactions_order_id", "interactions", ["order_id"])
    op.create_index(
        "ix_interactions_issue",
        "interactions",
        ["status"],
        postgresql_where=sa.text("status = 'issue'"),
    )


def downgrade() -> None:
    """Downgrade database schema."""

    op.drop_index("ix_interactions_issue", table_name="interactions")
    op.drop_index("ix_interactions_order_id", table_name="interactions")
    op.drop_index("ix_order_responses_blogger_id", table_name="order_responses")
    op.drop_index("ix_order_responses_order_id", table_name="order_responses")
    op.drop_index("ix_orders_active", table_name="orders")
    op.drop_index("ix_orders_advertiser_status", table_name="orders")
    op.drop_index("ix_users_external_messenger_status", table_name="users")

    op.drop_table("complaints")
    op.drop_table("instagram_verification_codes")
    op.drop_table("interactions")
    op.drop_table("order_responses")
    op.drop_table("orders")
    op.drop_table("advertiser_profiles")
    op.drop_table("blogger_profiles")
    op.drop_table("users")

    for enum_name in (
        "complaint_status",
        "interaction_status",
        "order_status",
        "audience_gender",
        "user_status",
        "user_role",
        "messenger_type",
    ):
        op.execute(f'DROP TYPE IF EXISTS "{enum_name}"')
