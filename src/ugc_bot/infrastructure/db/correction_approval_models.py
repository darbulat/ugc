"""Install the final approval guard after all historical table hooks."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.correction_approval_schema import (
    correction_approval_pending_sql,
    correction_approval_tables,
    correction_approval_trigger_sql,
)
from ugc_bot.infrastructure.db.correction_models import (
    TABLE_MAP as BASE_TABLE_MAP,
)

TABLE_MAP = correction_approval_tables(Base.metadata)
TABLES = tuple(TABLE_MAP.values())
for table in TABLES:
    sa.event.listen(
        table,
        "after_create",
        sa.DDL(correction_approval_pending_sql(table)).execute_if(
            dialect="postgresql"
        ),
    )


def install_final_guard(metadata, connection, **kw):
    if connection.dialect.name != "postgresql":
        return
    names = set(sa.inspect(connection).get_table_names())
    required = {t.name for t in (*TABLES, *BASE_TABLE_MAP.values())} | {
        "users",
        "orders",
        "order_items",
        "payments",
        "outbox_events",
        "payment_item_allocations",
        "order_intake_receipts",
        "item_assignments",
        "paid_selection_accepted_deliveries",
        "financial_policy_versions",
        "financial_obligations",
        "rate_snapshots",
        "financial_movements",
        "financial_audit_events",
        "financial_wallets",
    }
    if required <= names:
        connection.exec_driver_sql(correction_approval_trigger_sql(TABLE_MAP))
        from ugc_bot.infrastructure.db.financial_completion_metadata import (
            install_financial_completion_guards,
        )

        install_financial_completion_guards(connection, names)


sa.event.listen(Base.metadata, "after_create", install_final_guard)
