"""Additive CLIENT grade applicability, separate from frozen ledger DDL."""

import sqlalchemy as sa

CONSTRAINT = "ck_snapshot_grade_applicable"
EXPRESSION = "verified_count IS NOT NULL OR side = 'client'"


def add_client_grade_applicability(table: sa.Table) -> None:
    """CLIENT has no creator grade; retain existing measured counts."""
    table.c.verified_count.nullable = True
    table.append_constraint(sa.CheckConstraint(EXPRESSION, name=CONSTRAINT))
