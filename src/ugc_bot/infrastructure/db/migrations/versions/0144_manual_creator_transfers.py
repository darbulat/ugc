"""Keep supplemental manual handoffs outside the paid-position ledger."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.creator_transfer_models import (
    GUARD_SQL,
    transfer_table,
)

revision = "0144_manual_creator_transfers"
down_revision = "0143_manager_creator_followups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = transfer_table(sa.MetaData())
    # Existing foreign-key targets are resolved by PostgreSQL, not created here.
    for name, column in (("orders", "order_id"), ("users", "user_id")):
        sa.Table(
            name, table.metadata, sa.Column(column, sa.Uuid(), primary_key=True)
        )
    table.create(op.get_bind(), checkfirst=False)
    op.execute(GUARD_SQL)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
     IF EXISTS (SELECT 1 FROM order_creator_transfers) THEN
      RAISE EXCEPTION 'creator_transfer_history_required';
     END IF;
    END $$;""")
    op.drop_table("order_creator_transfers")
    op.execute("DROP FUNCTION creator_transfer_preserve_history()")
