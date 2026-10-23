"""Truthful inapplicable fields for fixed management basis (additive DDL)."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.snapshot_grade_schema import (
    CONSTRAINT as GRADE_NAME,
)

GRADE_EXPRESSION = (
    "verified_count IS NOT NULL OR side IN ('client','management')"
)
REFERRAL_NAME = "ck_snapshot_referral_fields_present"
REFERRAL_EXPRESSION = (
    "side = 'management' OR "
    "(registered_at IS NOT NULL AND rate_bps IS NOT NULL)"
)
MANAGEMENT_NAME = "ck_snapshot_management_fields_na"
MANAGEMENT_EXPRESSION = (
    "side <> 'management' OR (registered_at IS NULL AND verified_count IS NULL "
    "AND rate_bps IS NULL AND age_rule = 'management' "
    "AND assignment_id IS NOT NULL)"
)


def add_management_basis_applicability(table: sa.Table) -> None:
    for name in ("registered_at", "rate_bps"):
        table.c[name].nullable = True
    for constraint in tuple(table.constraints):
        if constraint.name == GRADE_NAME:
            table.constraints.remove(constraint)
    for name, expression in (
        (GRADE_NAME, GRADE_EXPRESSION),
        (REFERRAL_NAME, REFERRAL_EXPRESSION),
        (MANAGEMENT_NAME, MANAGEMENT_EXPRESSION),
    ):
        table.append_constraint(sa.CheckConstraint(expression, name=name))
