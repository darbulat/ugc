"""Keep stopped followup history while allowing one new active series."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.customer_workflow_models import INTENTS

revision = "0126_followup_new_orders"
down_revision = "0125_order_notice_leases"
branch_labels = None
depends_on = None

_TABLE = "client_followup_series"
_ACTIVE_INDEX = "uq_client_followup_active_user"
_HISTORY_INDEX = "ix_client_followup_user_created"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "stopped_at" not in {
        column["name"] for column in inspector.get_columns(_TABLE)
    }:
        op.add_column(
            _TABLE, sa.Column("stopped_at", sa.DateTime(timezone=True))
        )
    for constraint in inspector.get_unique_constraints(_TABLE):
        if constraint["column_names"] == ["user_id"]:
            name = constraint["name"]
            if not name:
                raise RuntimeError("Unnamed followup user constraint")
            op.drop_constraint(name, _TABLE, type_="unique")
    if _ACTIVE_INDEX not in {
        index["name"] for index in inspector.get_indexes(_TABLE)
    }:
        op.create_index(
            _ACTIVE_INDEX,
            _TABLE,
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("stop_reason IS NULL"),
        )
    if _HISTORY_INDEX not in {
        index["name"] for index in inspector.get_indexes(_TABLE)
    }:
        op.create_index(_HISTORY_INDEX, _TABLE, ["user_id", "created_at"])
    # Old stopped rows have no recorded observation time.  Treat the upgrade
    # as their boundary so a delayed pre-upgrade event cannot revive them.
    op.execute(
        "UPDATE client_followup_series SET stopped_at = now() "
        "WHERE stop_reason IS NOT NULL AND stopped_at IS NULL"
    )
    INTENTS.create(bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            "SELECT 1 FROM client_followup_series GROUP BY user_id "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Cannot downgrade followups with multiple series "
            "without losing history"
        )
    if bind.execute(
        sa.text("SELECT 1 FROM client_followup_intents LIMIT 1")
    ).first():
        raise RuntimeError(
            "Cannot downgrade followups without losing intent history"
        )
    INTENTS.drop(bind, checkfirst=True)
    op.drop_index(_HISTORY_INDEX, table_name=_TABLE)
    op.drop_index(_ACTIVE_INDEX, table_name=_TABLE)
    op.create_unique_constraint(
        "uq_client_followup_series_user_id", _TABLE, ["user_id"]
    )
    op.drop_column(_TABLE, "stopped_at")
