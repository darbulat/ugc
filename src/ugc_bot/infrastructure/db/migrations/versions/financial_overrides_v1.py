"""Append-only administrative rate command and temporal revocation facts."""

from alembic import op

from ugc_bot.infrastructure.db.override_models import TABLES

revision = "financial_overrides_v1"
down_revision = "financial_entitlements_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in TABLES:
        table.create(op.get_bind())


def downgrade() -> None:
    raise RuntimeError("Cannot discard immutable override command history")
