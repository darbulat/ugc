"""Published manual subscription tariffs, payments and pilot evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.order_funnel_schema import funnel_table
from ugc_bot.infrastructure.db.subscription_schema import (
    SUBSCRIPTION_GUARDS,
    subscription_table,
)

revision = "0110_commercial_completion"
down_revision = "00e0_financial_completion"
branch_labels = None
depends_on = None


def table():
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("user_id", UUID, primary_key=True))
    sa.Table("orders", metadata, sa.Column("order_id", UUID, primary_key=True))
    return subscription_table(metadata), funnel_table(metadata)


def upgrade():
    connection = op.get_bind()
    for owned in table():
        connection.execute(sa.schema.CreateTable(owned))
    connection.exec_driver_sql(SUBSCRIPTION_GUARDS)


def downgrade():
    connection = op.get_bind()
    owned, funnel = table()
    connection.execute(
        sa.text(
            "LOCK TABLE manager_subscription_events IN ACCESS EXCLUSIVE MODE"
        )
    )
    if connection.scalar(sa.select(sa.func.count()).select_from(owned)):
        raise RuntimeError("subscription_history_exists")
    if connection.scalar(sa.select(sa.func.count()).select_from(funnel)):
        raise RuntimeError("intake_funnel_history_exists")
    connection.execute(sa.schema.DropTable(funnel))
    connection.execute(sa.schema.DropTable(owned))
    connection.exec_driver_sql(
        "DROP FUNCTION subscription_fact_immutable(); "
        "DROP FUNCTION subscription_check_authority();"
    )
