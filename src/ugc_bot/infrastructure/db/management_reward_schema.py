"""Accepted standard v1 manager reward; customer service price is separate."""

import sqlalchemy as sa

CONSTRAINT = "ck_management_reward_standard"
# This is versioned-schema v1, not a future mutable pricing configuration.
EXPRESSION = (
    "kind <> 'management' OR (base_minor = 60000 AND amount_minor = 60000)"
)


def add_management_reward_standard(table: sa.Table) -> None:
    table.append_constraint(sa.CheckConstraint(EXPRESSION, name=CONSTRAINT))
