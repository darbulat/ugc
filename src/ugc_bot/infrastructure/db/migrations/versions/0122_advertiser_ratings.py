"""Keep each rater's history while admitting an advertiser's final rating."""

import sqlalchemy as sa
from alembic import op

revision = "0122_advertiser_ratings"
down_revision = "0121_customer_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "uq_blogger_order_rating", "blogger_ratings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_blogger_order_rater_rating",
        "blogger_ratings",
        ["blogger_id", "order_id", "rater_id"],
    )


def downgrade():
    duplicates = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM (SELECT blogger_id, order_id "
            "FROM blogger_ratings GROUP BY blogger_id, order_id "
            "HAVING count(*)>1) duplicates"
        )
    )
    if duplicates:
        raise RuntimeError("multiple_rating_history_exists")
    op.drop_constraint(
        "uq_blogger_order_rater_rating", "blogger_ratings", type_="unique"
    )
    op.create_unique_constraint(
        "uq_blogger_order_rating", "blogger_ratings", ["blogger_id", "order_id"]
    )
