"""Additive ledger metadata extension shared with its explicit migration."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

RATE_CHECK = (
    "(rate_source = 'standard' AND override_id IS NULL) OR "
    "(rate_source = 'override' AND override_id IS NOT NULL "
    "AND side <> 'management')"
)


def extend_ledger_metadata(metadata: sa.MetaData) -> None:
    rates = metadata.tables["rate_snapshots"]
    if "rate_source" in rates.c:
        return
    rates.append_column(
        sa.Column(
            "rate_source",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'standard'"),
        )
    )
    rates.append_column(
        sa.Column(
            "override_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "financial_rate_overrides.override_id",
                name="fk_snapshot_rate_override",
            ),
            nullable=True,
        )
    )
    rates.append_constraint(
        sa.CheckConstraint(RATE_CHECK, name="ck_snapshot_rate_provenance")
    )
    obligations = metadata.tables["financial_obligations"]
    for constraint in tuple(obligations.constraints):
        if constraint.name == "uq_obligation_economic_basis":
            obligations.constraints.remove(constraint)
    sa.Index(
        "uq_obligation_client_basis",
        obligations.c.paid_item_id,
        obligations.c.recipient_id,
        obligations.c.kind,
        unique=True,
        postgresql_where=sa.text("kind = 'client_referral'"),
        sqlite_where=sa.text("kind = 'client_referral'"),
    )
    sa.Index(
        "uq_obligation_assignment_basis",
        obligations.c.paid_item_id,
        obligations.c.assignment_id,
        obligations.c.recipient_id,
        obligations.c.kind,
        unique=True,
        postgresql_where=sa.text("kind IN ('creator_referral','management')"),
        sqlite_where=sa.text("kind IN ('creator_referral','management')"),
    )
    obligations.append_constraint(
        sa.UniqueConstraint(
            "id",
            "assignment_id",
            "paid_item_id",
            name="uq_obligation_work_scope",
        )
    )
    obligations.append_constraint(
        sa.UniqueConstraint(
            "id",
            "paid_item_id",
            "kind",
            "recipient_id",
            "currency",
            name="uq_obligation_active_scope",
        )
    )


ACTIVE_CANDIDATES = """
SELECT o.id AS obligation_id, o.paid_item_id, o.kind, o.recipient_id, o.currency
FROM financial_obligations o LEFT JOIN financial_movements m
 ON m.obligation_id=o.id
WHERE o.kind IN ('creator_referral','management')
GROUP BY o.id
HAVING COALESCE(sum(CASE WHEN m.movement_type IN ('reversal','debt')
 THEN m.amount_minor ELSE 0 END),0) < o.amount_minor
 OR COALESCE(sum(CASE WHEN m.bucket_to='paid'
 THEN m.amount_minor ELSE 0 END),0)>0
"""
