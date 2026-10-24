"""Assignment grounds, approved rates and immutable work maturity facts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from ugc_bot.infrastructure.db.financial_lifecycle_models import TABLES
from ugc_bot.infrastructure.db.financial_lifecycle_schema import (
    ACTIVE_CANDIDATES,
    RATE_CHECK,
)

revision = "financial_lifecycle_v1"
down_revision = "creator_identity_history_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE financial_obligations, financial_movements, "
            "rate_snapshots IN ACCESS EXCLUSIVE MODE"
        )
    )
    duplicate = connection.execute(
        sa.text(
            "SELECT paid_item_id, kind FROM ("
            + ACTIVE_CANDIDATES
            + ") live GROUP BY paid_item_id, kind HAVING count(*)>1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Review multiple live financial grounds before migration"
        )
    TABLES[0].create(connection)
    op.add_column(
        "rate_snapshots",
        sa.Column(
            "rate_source",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'standard'"),
        ),
    )
    op.add_column(
        "rate_snapshots",
        sa.Column("override_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_snapshot_rate_override",
        "rate_snapshots",
        "financial_rate_overrides",
        ["override_id"],
        ["override_id"],
    )
    op.create_check_constraint(
        "ck_snapshot_rate_provenance", "rate_snapshots", RATE_CHECK
    )
    op.drop_constraint(
        "uq_obligation_economic_basis", "financial_obligations", type_="unique"
    )
    op.create_index(
        "uq_obligation_client_basis",
        "financial_obligations",
        ["paid_item_id", "recipient_id", "kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'client_referral'"),
    )
    op.create_index(
        "uq_obligation_assignment_basis",
        "financial_obligations",
        ["paid_item_id", "assignment_id", "recipient_id", "kind"],
        unique=True,
        postgresql_where=sa.text("kind IN ('creator_referral','management')"),
    )
    op.create_unique_constraint(
        "uq_obligation_work_scope",
        "financial_obligations",
        ["id", "assignment_id", "paid_item_id"],
    )
    op.create_unique_constraint(
        "uq_obligation_active_scope",
        "financial_obligations",
        ["id", "paid_item_id", "kind", "recipient_id", "currency"],
    )
    TABLES[1].create(connection)
    TABLES[2].create(connection)
    connection.execute(
        sa.text(
            "INSERT INTO financial_active_grounds "
            "(obligation_id,paid_item_id,kind,recipient_id,currency) "
            + ACTIVE_CANDIDATES
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Cannot discard financial provenance and maturity history"
    )
