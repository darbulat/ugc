"""Store an explicit dispatch city separately from the intake receipt."""

from alembic import op

from ugc_bot.infrastructure.db.order_intake_models import (
    ORDER_DISPATCH_CITY_OVERRIDES,
)

revision = "0129_dispatch_city_override"
down_revision = "0128_selection_per_item"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ORDER_DISPATCH_CITY_OVERRIDES.create(op.get_bind())


def downgrade() -> None:
    ORDER_DISPATCH_CITY_OVERRIDES.drop(op.get_bind())
