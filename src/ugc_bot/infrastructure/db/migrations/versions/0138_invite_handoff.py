"""Persist invitation progress and the first acknowledged order contact."""

from alembic import op

from ugc_bot.infrastructure.db import creator_invite_models  # noqa: F401
from ugc_bot.infrastructure.db.invite_handoff_schema import (
    FIRST,
    NATIVE,
    TABLES,
    install_invite_handoff_guards,
    rewrite_correction_guard,
)
from ugc_bot.infrastructure.db.selection_maturity_schema import (
    PER_ITEM_SELECTION_SOURCE_GUARD,
)

revision = "0138_invite_handoff"
down_revision = "0137_social_prompt_preference"
branch_labels = None
depends_on = None


def upgrade():
    for table in TABLES:
        table.create(op.get_bind())
    install_invite_handoff_guards(op.execute)


def downgrade():
    used = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table.name})" for table in TABLES
    )
    op.execute(
        f"DO $$ BEGIN IF {used} "
        "THEN RAISE EXCEPTION 'invite_handoff_history_exists'; END IF; END $$"
    )
    rewrite_correction_guard(op.execute, FIRST, NATIVE)
    op.execute(PER_ITEM_SELECTION_SOURCE_GUARD)
    op.execute("DROP VIEW order_first_selection_contacts")
    for table in reversed(TABLES):
        table.drop(op.get_bind())
    op.execute("DROP FUNCTION order_invite_staff_delivery_check()")
