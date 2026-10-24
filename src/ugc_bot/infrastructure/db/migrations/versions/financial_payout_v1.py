"""Versioned secure reserve/manual payout authority, preserving legacy facts."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.payout_schema import (
    GUARD_SQL,
    IMMUTABILITY_SQL,
    NAMES,
    SCOPE_GUARD_SQL,
    payout_tables,
)

revision = "financial_payout_v1"
down_revision = "campaign_foundation_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_payout_obligation_owner",
        "financial_obligations",
        ["id", "recipient_id", "currency"],
    )
    op.add_column(
        "payout_requests",
        sa.Column("payout_protocol", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_payout_protocol",
        "payout_requests",
        "payout_protocol IS NULL OR payout_protocol='financial_v1'",
    )
    op.execute("DROP INDEX uq_payout_requests_user_id_request_date")
    op.execute("DROP INDEX uq_payout_request_user_currency_day")
    op.execute(
        "CREATE UNIQUE INDEX uq_payout_requests_user_id_request_date ON "
        "payout_requests(user_id, (CAST(requested_at AT TIME ZONE 'UTC' "
        "AS date))) WHERE payout_protocol IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_payout_request_user_currency_day ON "
        "payout_requests(user_id,currency,DATE(requested_at AT TIME ZONE "
        "'UTC')) WHERE payout_protocol IS NULL AND status NOT IN "
        "('cancelled','deleted')"
    )
    metadata = sa.MetaData()
    metadata.reflect(
        op.get_bind(),
        only=[
            "users",
            "payout_requests",
            "financial_movements",
            "financial_obligations",
        ],
    )
    tables = payout_tables(metadata)
    op.execute(IMMUTABILITY_SQL)
    for name, table in tables.items():
        table.create(op.get_bind())
        if name != "states":
            op.execute(
                f"CREATE TRIGGER payout_immutable BEFORE UPDATE OR DELETE OR "
                f"TRUNCATE ON {table.name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION payout_deny_mutation()"
            )
    op.execute(GUARD_SQL)
    op.execute(SCOPE_GUARD_SQL)


def downgrade():
    db = op.get_bind()
    db.execute(
        sa.text(
            "LOCK TABLE payout_requests,financial_movements,"
            + ",".join(NAMES)
            + " IN ACCESS EXCLUSIVE MODE"
        )
    )
    for name in NAMES:
        if db.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {name})")):
            raise RuntimeError("Cannot discard payout history")
    if db.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM payout_requests WHERE "
            "payout_protocol IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard payout anchors")
    db.execute(
        sa.text("DROP TRIGGER payout_movement_guard ON financial_movements")
    )
    db.execute(sa.text("DROP FUNCTION payout_check_movement()"))
    db.execute(sa.text("DROP TRIGGER payout_anchor_guard ON payout_requests"))
    db.execute(sa.text("DROP FUNCTION payout_guard_anchor()"))
    op.execute("DROP FUNCTION payout_check_request_anchor() CASCADE")
    op.execute("DROP FUNCTION payout_check_settlement() CASCADE")
    for name in reversed(NAMES):
        op.drop_table(name)
    op.execute("DROP FUNCTION payout_deny_mutation()")
    op.execute("DROP INDEX uq_payout_requests_user_id_request_date")
    op.execute("DROP INDEX uq_payout_request_user_currency_day")
    op.execute(
        "CREATE UNIQUE INDEX uq_payout_requests_user_id_request_date ON "
        "payout_requests(user_id, (CAST(requested_at AT TIME ZONE 'UTC' "
        "AS date)))"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_payout_request_user_currency_day ON "
        "payout_requests(user_id,currency,DATE(requested_at AT TIME ZONE "
        "'UTC')) WHERE status NOT IN ('cancelled','deleted')"
    )
    op.drop_constraint("ck_payout_protocol", "payout_requests")
    op.drop_column("payout_requests", "payout_protocol")
    op.drop_constraint(
        "uq_payout_obligation_owner", "financial_obligations", type_="unique"
    )
