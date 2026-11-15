"""Register managers and save contacts supplied by staff with order consent."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.manager_application_models import (
    application_table,
)

revision = "0136_manager_onboarding"
down_revision = "0135_order_creator_invites"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    sa.Table(
        "users", metadata, sa.Column("user_id", sa.Uuid(), primary_key=True)
    )
    application_table(metadata).create(op.get_bind())
    op.add_column("order_creator_invites", sa.Column("telegram", sa.String(32)))
    op.add_column(
        "order_creator_invites",
        sa.Column("reported_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "order_creator_invites",
        sa.Column("reported_by", sa.String(64)),
    )
    op.add_column(
        "order_creator_invites", sa.Column("consent_source", sa.String(100))
    )
    op.add_column(
        "order_creator_invites", sa.Column("creator_name", sa.String(80))
    )
    op.add_column(
        "order_creator_invites",
        sa.Column("manager_notice_at", sa.DateTime(timezone=True)),
    )
    op.create_check_constraint(
        "ck_invite_staff_consent",
        "order_creator_invites",
        "(reported_at IS NULL AND reported_by IS NULL "
        "AND consent_source IS NULL) "
        "OR (reported_at IS NOT NULL "
        "AND reported_by IS NOT NULL "
        "AND consent_source IS NOT NULL AND telegram IS NOT NULL)",
    )
    op.create_index(
        "uq_invite_staff_position",
        "order_creator_invites",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text("reported_at IS NOT NULL"),
    )


def downgrade():
    db = op.get_bind()
    db.exec_driver_sql(
        "LOCK TABLE manager_applications, order_creator_invites "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if (
        db.exec_driver_sql("SELECT 1 FROM manager_applications LIMIT 1").first()
        or db.exec_driver_sql(
            "SELECT 1 FROM order_creator_invites "
            "WHERE telegram IS NOT NULL OR manager_notice_at IS NOT NULL "
            "LIMIT 1"
        ).first()
    ):
        raise RuntimeError("manager_onboarding_history_exists")
    op.drop_index(
        "uq_invite_staff_position", table_name="order_creator_invites"
    )
    op.drop_constraint(
        "ck_invite_staff_consent", "order_creator_invites", type_="check"
    )
    for column in (
        "manager_notice_at",
        "creator_name",
        "consent_source",
        "reported_by",
        "reported_at",
        "telegram",
    ):
        op.drop_column("order_creator_invites", column)
    op.drop_table("manager_applications")
