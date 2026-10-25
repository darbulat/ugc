"""Persist real selection closure and support reviewed work rejection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.accompaniment_refund_schema import (
    accompaniment_refund_guards,
    accompaniment_refund_tables,
)
from ugc_bot.infrastructure.db.refund_original_schema import (
    ORIGINAL_VALIDATE_SQL,
    refund_original_guards,
    refund_original_tables,
)
from ugc_bot.infrastructure.db.selection_maturity_schema import (
    selection_maturity_guards,
    selection_maturity_tables,
)

revision = "00e0_financial_completion"
down_revision = "00f0_campaign_runtime"
branch_labels = None
depends_on = None


def tables():
    metadata = sa.MetaData()
    for name, key, type_ in (
        ("users", "user_id", UUID),
        ("orders", "order_id", UUID),
        ("payments", "payment_id", UUID),
        ("order_items", "paid_item_id", UUID),
        ("financial_policy_versions", "version", sa.String),
        ("item_assignments", "assignment_id", UUID),
        ("financial_refund_matches", "match_id", UUID),
        ("financial_correction_commands", "command_id", UUID),
        ("financial_correction_cases", "case_id", UUID),
        ("outbox_events", "event_id", UUID),
    ):
        sa.Table(name, metadata, sa.Column(key, type_, primary_key=True))
    return {
        **selection_maturity_tables(metadata),
        **{
            "accompaniment_" + key: value
            for key, value in accompaniment_refund_tables(metadata).items()
        },
        **refund_original_tables(metadata),
    }


def upgrade():
    connection = op.get_bind()
    owned = tables()
    for table in owned.values():
        connection.execute(sa.schema.CreateTable(table))
    connection.exec_driver_sql(
        selection_maturity_guards(
            {
                key: value
                for key, value in owned.items()
                if key in ("closures", "schedules")
            }
        )
    )
    connection.exec_driver_sql(
        accompaniment_refund_guards(
            {
                key: value
                for key, value in owned.items()
                if key.startswith("accompaniment_")
            }
        )
    )
    connection.exec_driver_sql(refund_original_guards())
    connection.exec_driver_sql(
        "ALTER TABLE financial_collaborations "
        "DROP CONSTRAINT ck_collaboration_state"
    )
    connection.exec_driver_sql(
        "ALTER TABLE financial_collaborations ADD CONSTRAINT "
        "ck_collaboration_state CHECK(state IN ('assigned','in_progress',"
        "'success_claimed','disputed','success_final','unconfirmed_expired',"
        "'available','rejected'))"
    )


def downgrade():
    connection = op.get_bind()
    owned = tables()
    connection.exec_driver_sql(
        "LOCK TABLE financial_selection_closures,"
        "financial_selection_schedules,financial_collaborations,"
        "financial_accompaniment_refund_commands,"
        "financial_accompaniment_refund_observations,"
        "financial_accompaniment_refund_applications,"
        "financial_accompaniment_management_reviews,"
        "financial_refund_original_assessments IN ACCESS EXCLUSIVE MODE"
    )
    if (
        any(
            connection.execute(sa.select(t).limit(1)).first()
            for t in owned.values()
        )
        or connection.execute(
            sa.text(
                "SELECT 1 FROM financial_collaborations "
                "WHERE state='rejected' LIMIT 1"
            )
        ).first()
    ):
        raise RuntimeError("Cannot discard financial completion history")
    connection.exec_driver_sql(
        "ALTER TABLE financial_collaborations "
        "DROP CONSTRAINT ck_collaboration_state"
    )
    connection.exec_driver_sql(
        "ALTER TABLE financial_collaborations ADD CONSTRAINT "
        "ck_collaboration_state CHECK(state IN ('assigned','in_progress',"
        "'success_claimed','disputed','success_final','unconfirmed_expired',"
        "'available'))"
    )
    for table in reversed(tuple(owned.values())):
        connection.execute(sa.schema.DropTable(table))
    connection.exec_driver_sql(ORIGINAL_VALIDATE_SQL)
    connection.exec_driver_sql(
        "DROP FUNCTION correction_check_original_assessment()"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION correction_original_ground_visible(uuid,uuid,text)"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION accompaniment_refund_check_application()"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION accompaniment_management_check_review()"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION financial_selection_deny_mutation()"
    )
    connection.exec_driver_sql(
        "DROP FUNCTION financial_selection_check_source()"
    )
