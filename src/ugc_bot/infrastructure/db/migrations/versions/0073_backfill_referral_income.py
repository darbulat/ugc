"""Backfill referral_income_entries from historical closed orders."""

import sqlalchemy as sa
from alembic import op

revision = "0073_backfill_referral_income"
down_revision = "0072_referral_income_entries"
branch_labels = None
depends_on = None

_ADVERTISER_SQL = """\
INSERT INTO referral_income_entries
    (entry_id, referrer_user_id, referred_user_id, order_id,
     income_type, currency, platform_revenue, commission_rate,
     commission_amount, created_at)
SELECT
    gen_random_uuid(),
    urb.referrer_user_id,
    o.advertiser_id,
    o.order_id,
    'advertiser',
    cp.currency,
    cp.price,
    CASE
        WHEN u.referral_payout_rate IS NOT NULL
            THEN u.referral_payout_rate
        WHEN EXTRACT(EPOCH FROM
            (o.completed_at - u.created_at)
        ) / 86400.0 / 365.25 < 1.0
            THEN 0.10
        ELSE 0.03
    END,
    ROUND(cp.price * CASE
        WHEN u.referral_payout_rate IS NOT NULL
            THEN u.referral_payout_rate
        WHEN EXTRACT(EPOCH FROM
            (o.completed_at - u.created_at)
        ) / 86400.0 / 365.25 < 1.0
            THEN 0.10
        ELSE 0.03
    END, 2),
    COALESCE(o.completed_at, o.updated_at)
FROM orders o
JOIN users u
    ON u.user_id = o.advertiser_id
JOIN user_referral_bindings urb
    ON urb.referred_user_id = o.advertiser_id
JOIN contact_pricing cp
    ON cp.country_code = COALESCE(u.country, 'ru')
    AND cp.bloggers_count = o.bloggers_needed
WHERE o.status = 'closed'
  AND EXISTS (
      SELECT 1 FROM payments p
      WHERE p.order_id = o.order_id AND p.status = 'paid'
  )
  AND o.bloggers_needed > 0
ON CONFLICT (order_id, referrer_user_id, income_type)
    DO NOTHING
"""

_CREATOR_SQL = """\
INSERT INTO referral_income_entries
    (entry_id, referrer_user_id, referred_user_id, order_id,
     income_type, currency, platform_revenue, commission_rate,
     commission_amount, created_at)
SELECT
    gen_random_uuid(),
    urb.referrer_user_id,
    i.blogger_id,
    o.order_id,
    'creator',
    cp.currency,
    ROUND(cp.price::numeric / o.bloggers_needed, 2),
    CASE
        WHEN creator.referral_payout_rate IS NOT NULL
            THEN creator.referral_payout_rate
        WHEN EXTRACT(EPOCH FROM
            (o.completed_at - creator.created_at)
        ) / 86400.0 / 365.25 < 1.0
            THEN 0.10
        ELSE 0.03
    END,
    ROUND(
        ROUND(
            cp.price::numeric / o.bloggers_needed, 2
        ) * CASE
            WHEN creator.referral_payout_rate IS NOT NULL
                THEN creator.referral_payout_rate
            WHEN EXTRACT(EPOCH FROM
                (o.completed_at - creator.created_at)
            ) / 86400.0 / 365.25 < 1.0
                THEN 0.10
            ELSE 0.03
        END,
    2),
    COALESCE(o.completed_at, o.updated_at)
FROM interactions i
JOIN orders o ON o.order_id = i.order_id
JOIN users advertiser
    ON advertiser.user_id = o.advertiser_id
JOIN users creator
    ON creator.user_id = i.blogger_id
JOIN user_referral_bindings urb
    ON urb.referred_user_id = i.blogger_id
JOIN contact_pricing cp
    ON cp.country_code = COALESCE(
        advertiser.country, 'ru'
    )
    AND cp.bloggers_count = o.bloggers_needed
WHERE o.status = 'closed'
  AND i.status = 'ok'
  AND o.bloggers_needed > 0
  AND EXISTS (
      SELECT 1 FROM payments p
      WHERE p.order_id = o.order_id AND p.status = 'paid'
  )
ON CONFLICT (order_id, referrer_user_id, income_type)
    DO NOTHING
"""


def upgrade() -> None:
    """Backfill income entries for existing closed orders."""
    conn = op.get_bind()
    conn.execute(sa.text(_ADVERTISER_SQL))
    conn.execute(sa.text(_CREATOR_SQL))


def downgrade() -> None:
    """Remove backfilled entries."""
    op.execute("DELETE FROM referral_income_entries")
