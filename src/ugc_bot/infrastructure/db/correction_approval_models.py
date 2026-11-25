"""Install the final approval guard after all historical table hooks."""

from importlib import import_module

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.browser_checkout_models import (
    BROWSER_ATTEMPTS,
)
from ugc_bot.infrastructure.db.browser_checkout_models import (
    GUARD_SQL as BROWSER_CHECKOUT_GUARDS,
)
from ugc_bot.infrastructure.db.consultation_models import (
    CONSULTATION_ATTEMPTS,
    CONSULTATIONS,
)
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

        if install_financial_completion_guards(connection, names):
            # Match the final migrated authority only for complete metadata.
            # Partial historical metadata keeps its original guard boundary.
            public_scope = import_module(
                "ugc_bot.infrastructure.db.migrations.versions."
                "0127_public_policy_scope"
            )
            connection.exec_driver_sql(public_scope._authority_sql(public=True))
            from ugc_bot.infrastructure.db.invite_handoff_schema import (
                TABLES as HANDOFF_TABLES,
            )
            from ugc_bot.infrastructure.db.invite_handoff_schema import (
                install_invite_handoff_guards,
            )

            if {table.name for table in HANDOFF_TABLES} <= names:
                install_invite_handoff_guards(connection.exec_driver_sql)
                _install_browser_authority(
                    connection, names, kw.get("tables", ())
                )


def _install_browser_authority(connection, names, new_tables):
    if BROWSER_ATTEMPTS.name not in names:
        return
    if BROWSER_ATTEMPTS in new_tables:
        connection.exec_driver_sql(BROWSER_CHECKOUT_GUARDS)
    if {CONSULTATIONS.name, CONSULTATION_ATTEMPTS.name} <= names:
        combined = import_module(
            "ugc_bot.infrastructure.db.migrations.versions.0153_combined_checkout"
        )
        combined.install_combined_checkout(connection)
    else:
        browser = import_module(
            "ugc_bot.infrastructure.db.migrations.versions.0140_browser_checkout"
        )
        connection.exec_driver_sql(browser._authority_sql(browser=True))


sa.event.listen(Base.metadata, "after_create", install_final_guard)
