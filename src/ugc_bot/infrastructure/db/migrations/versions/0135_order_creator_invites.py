"""Persist scoped creator invitations without changing existing paid records."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.creator_invite_models import invite_table

revision = "0135_order_creator_invites"
down_revision = "0134_creator_social_links"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    for name, key in (
        ("orders", "order_id"),
        ("order_items", "paid_item_id"),
        ("users", "user_id"),
        ("paid_selection_interests", "interest_id"),
    ):
        sa.Table(name, metadata, sa.Column(key, sa.Uuid(), primary_key=True))
    bind = op.get_bind()
    invite_table(metadata).create(bind)
    op.drop_constraint(
        "ck_selection_delivery_job",
        "paid_selection_delivery_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_selection_delivery_job",
        "paid_selection_delivery_jobs",
        "state IN ('card_ready','ready','sending','accepted','failed',"
        "'unknown','obsolete') AND attempt_count >= 0",
    )


def downgrade():
    bind = op.get_bind()
    bind.exec_driver_sql(
        "LOCK TABLE order_creator_invites IN ACCESS EXCLUSIVE MODE"
    )
    if bind.exec_driver_sql(
        "SELECT 1 FROM order_creator_invites LIMIT 1"
    ).first():
        raise RuntimeError("order_creator_invite_history_exists")
    op.drop_table("order_creator_invites")
    op.drop_constraint(
        "ck_selection_delivery_job",
        "paid_selection_delivery_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_selection_delivery_job",
        "paid_selection_delivery_jobs",
        "state IN ('ready','sending','accepted','failed','unknown',"
        "'obsolete') AND attempt_count >= 0",
    )
