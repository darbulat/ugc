"""Persist support, typed service inquiries, and activity followup delivery."""

from alembic import op

from ugc_bot.infrastructure.db.customer_workflow_models import TABLES

revision = "0121_customer_workflows"
down_revision = "0120_variable_tariff"
branch_labels = None
depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind(), checkfirst=True)


def downgrade():
    for table in reversed(TABLES):
        table.drop(op.get_bind(), checkfirst=True)
