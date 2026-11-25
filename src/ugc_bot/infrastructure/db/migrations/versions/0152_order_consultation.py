"""Store optional consultation checkout and dedicated delivery queues."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.consultation_models import (
    CONSULTATION_ATTEMPTS,
    CONSULTATIONS,
)
from ugc_bot.infrastructure.db.order_notice_models import (
    CONSULTATION_DELIVERIES,
    CONSULTATION_EVENTS,
)

revision = "0152_order_consultation"
down_revision = "0151_offer_card_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        CONSULTATIONS,
        CONSULTATION_ATTEMPTS,
        CONSULTATION_EVENTS,
        CONSULTATION_DELIVERIES,
    ):
        table.create(op.get_bind())
    op.execute("""
        CREATE TRIGGER consultation_checkout_paid_immutable
        BEFORE UPDATE OR DELETE ON consultation_checkout_attempts FOR EACH ROW
        WHEN (OLD.state='paid') EXECUTE FUNCTION financial_deny_mutation()
    """)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("LOCK TABLE order_consultations IN ACCESS EXCLUSIVE MODE")
    )
    if connection.execute(sa.select(CONSULTATIONS.c.order_id).limit(1)).first():
        raise RuntimeError(
            "Cannot discard consultation order or payment history"
        )
    for table in (
        CONSULTATION_DELIVERIES,
        CONSULTATION_EVENTS,
        CONSULTATION_ATTEMPTS,
        CONSULTATIONS,
    ):
        table.drop(op.get_bind())
