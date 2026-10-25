"""Actual incoming repayment proofs and immutable case-scoped recovery."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.debt_recovery_schema import (
    debt_recovery_guards,
    debt_recovery_tables,
)

revision = "0115_debt_recovery"
down_revision = "0114_refund_replacements"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name, key in (
        ("users", "user_id"),
        ("financial_obligations", "id"),
        ("financial_movements", "id"),
    ):
        sa.Table(name, metadata, sa.Column(key, UUID, primary_key=True))
    return debt_recovery_tables(metadata)


def upgrade():
    connection = op.get_bind()
    for owned in tables():
        connection.execute(sa.schema.CreateTable(owned))
    connection.exec_driver_sql(debt_recovery_guards())


def downgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned:
        connection.execute(
            sa.text(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        )
        if connection.scalar(sa.select(sa.func.count()).select_from(table)):
            raise RuntimeError("repayment_history_exists")
    for table in reversed(owned):
        connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql(
        "DROP FUNCTION repayment_check_source(); "
        "DROP FUNCTION repayment_check_observation(); "
        "DROP FUNCTION repayment_check_authority(); "
        "DROP FUNCTION repayment_deny_mutation();"
    )
