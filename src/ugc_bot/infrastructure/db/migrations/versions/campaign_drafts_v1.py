"""Append-only own campaign draft commands, identities and revisions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.campaign_review_schema import (
    draft_tables,
    immutability_sql,
)

revision = "campaign_drafts_v1"
down_revision = "messenger_linking_v1"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("user_id", UUID, primary_key=True))
    sa.Table(
        "campaign_policy_events",
        metadata,
        sa.Column("version", sa.Integer, primary_key=True),
    )
    sa.Table(
        "campaign_publisher_events",
        metadata,
        sa.Column("owner_id", UUID, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
    )
    return draft_tables(metadata)


def upgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned:
        connection.execute(sa.schema.CreateTable(table))
        for index in table.indexes:
            connection.execute(sa.schema.CreateIndex(index))
    connection.exec_driver_sql(immutability_sql(owned))


def downgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned:
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
    for table in owned:
        if connection.execute(sa.select(table).limit(1)).first():
            raise RuntimeError(
                "Cannot discard immutable campaign draft history"
            )
    for table in reversed(owned):
        connection.execute(sa.schema.DropTable(table))
    connection.execute(sa.text("DROP FUNCTION campaign_drafts_deny_mutation()"))
