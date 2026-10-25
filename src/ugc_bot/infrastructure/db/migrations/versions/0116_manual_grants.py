"""Separate superadmin positive adjustments and their immutable 14-day hold."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.ledger_schema import (
    IMMUTABILITY_SQL as TRIGGER_SQL,
)
from ugc_bot.infrastructure.db.management_basis_schema import (
    GRADE_EXPRESSION,
    REFERRAL_EXPRESSION,
)
from ugc_bot.infrastructure.db.manual_grant_schema import (
    MANUAL_CHECKS,
    MANUAL_FIELDS,
    manual_grant_guards,
    manual_grant_tables,
)

revision = "0116_manual_grants"
down_revision = "0115_debt_recovery"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name, key, type_ in (
        ("users", "user_id", UUID),
        ("orders", "order_id", UUID),
        ("order_items", "paid_item_id", UUID),
        ("payments", "payment_id", UUID),
        ("outbox_events", "event_id", UUID),
        ("financial_policy_versions", "version", sa.String),
    ):
        sa.Table(name, metadata, sa.Column(key, type_, primary_key=True))
    return manual_grant_tables(metadata)


def upgrade():
    db = op.get_bind()
    owned = tables()
    for table in owned.values():
        db.execute(sa.schema.CreateTable(table))
    for name, (table_name, expression) in MANUAL_CHECKS.items():
        db.exec_driver_sql(f"ALTER TABLE {table_name} DROP CONSTRAINT {name}")
        db.exec_driver_sql(
            f"ALTER TABLE {table_name} ADD CONSTRAINT {name} "
            f"CHECK({expression})"
        )
    db.exec_driver_sql(
        "ALTER TABLE rate_snapshots ADD CONSTRAINT "
        f"ck_snapshot_manual_fields_na CHECK({MANUAL_FIELDS})"
    )
    db.exec_driver_sql(manual_grant_guards(owned))


def downgrade():
    db = op.get_bind()
    owned = tables()
    db.exec_driver_sql(
        (
            "LOCK TABLE "
            "financial_manual_grants,financial_manual_grant_commands,financial_obligations,rate_snapshots,financial_movements"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    if any(
        db.execute(sa.select(t).limit(1)).first() for t in owned.values()
    ) or db.scalar(
        sa.text(
            (
                "SELECT 1 FROM financial_obligations WHERE "
                "kind='manual_adjustment' LIMIT 1"
            )
        )
    ):
        raise RuntimeError("manual_grant_history_exists")
    db.exec_driver_sql(
        "DROP TRIGGER manual_grant_movement_guard ON financial_movements"
    )
    a = TRIGGER_SQL.index("CREATE FUNCTION ledger_check_obligation_scope()")
    b = TRIGGER_SQL.index("CREATE TRIGGER ledger_obligation_scope", a)
    db.exec_driver_sql(
        TRIGGER_SQL[a:b].replace(
            "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1
        )
    )
    old = dict(MANUAL_CHECKS)
    old["ck_obligation_kind"] = (
        "financial_obligations",
        "kind IN ('client_referral','creator_referral','management')",
    )
    old["ck_snapshot_policy"] = (
        "rate_snapshots",
        (
            "side IN ('client','creator','management') AND currency='RUB' AND"
            " age_rule IN ('first_year','after_anniversary','management') AND"
            " effective_at>=registered_at"
        ),
    )
    old["ck_snapshot_referral_fields_present"] = (
        "rate_snapshots",
        REFERRAL_EXPRESSION,
    )
    old["ck_snapshot_grade_applicable"] = ("rate_snapshots", GRADE_EXPRESSION)
    db.exec_driver_sql(
        (
            "ALTER TABLE rate_snapshots DROP CONSTRAINT "
            "ck_snapshot_manual_fields_na"
        )
    )
    for name, (table_name, expression) in old.items():
        db.exec_driver_sql(f"ALTER TABLE {table_name} DROP CONSTRAINT {name}")
        db.exec_driver_sql(
            f"ALTER TABLE {table_name} ADD CONSTRAINT {name} "
            f"CHECK({expression})"
        )
    for table in reversed(tuple(owned.values())):
        db.execute(sa.schema.DropTable(table))
    db.exec_driver_sql(
        (
            "DROP FUNCTION manual_grant_check_source(); DROP FUNCTION "
            "manual_grant_check_movement();"
        )
    )
