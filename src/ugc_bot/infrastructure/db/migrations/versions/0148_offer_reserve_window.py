"""Bound reserve intake without changing financial or work status."""

import sqlalchemy as sa
from alembic import op

revision = "0148_offer_reserve_window"
down_revision = "0147_instagram_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("offer_reserve_until", sa.DateTime(timezone=True))
    )
    # Existing full orders get no fresh window on rollout. Closed historical
    # orders retain NULL and remain closed. Only future filling starts 72h.
    op.execute("""
        UPDATE orders o SET offer_reserve_until = CURRENT_TIMESTAMP
        WHERE o.status = 'active' AND o.bloggers_needed > 0 AND (
          CASE WHEN o.financial_version IS NOT NULL AND NOT o.complimentary
          THEN (SELECT count(*) FROM item_assignments a
                JOIN order_items i ON i.paid_item_id = a.paid_item_id
                WHERE i.order_id = o.order_id AND a.valid_to IS NULL)
          ELSE (SELECT count(*) FROM offer_dispatches d
                WHERE d.order_id = o.order_id AND d.in_offer AND d.accepted)
          END
        ) >= o.bloggers_needed
    """)


def downgrade() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (
        SELECT 1 FROM orders WHERE offer_reserve_until IS NOT NULL
      ) THEN
        RAISE EXCEPTION 'reserve_deadlines_require_retention_decision';
      END IF;
    END $$;""")
    op.drop_column("orders", "offer_reserve_until")
