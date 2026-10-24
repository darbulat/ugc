"""Immutable readable payout documents, bindings and explicit acceptances."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.payout_contract_schema import (
    contract_tables,
    install_contract_guards,
)

revision = "financial_payout_contracts_v1"
down_revision = "campaign_digest_v1"
branch_labels = None
depends_on = None


def upgrade():
    metadata = sa.MetaData()
    metadata.reflect(
        op.get_bind(),
        only=[
            "users",
            "financial_payout_requirements",
            "financial_payout_requisites",
        ],
    )
    tables = tuple(contract_tables(metadata).values())
    for table in tables:
        table.create(op.get_bind())
    install_contract_guards(op.get_bind(), tables)


def downgrade():
    names = (
        "financial_payout_terms_documents",
        "financial_payout_requirement_contracts",
        "financial_payout_requisites_acceptances",
    )
    db = op.get_bind()
    for name in names:
        db.execute(sa.text(f"LOCK TABLE {name} IN ACCESS EXCLUSIVE MODE"))
    if any(
        db.scalar(sa.text(f"SELECT EXISTS(SELECT 1 FROM {name})"))
        for name in names
    ):
        raise RuntimeError("Cannot discard immutable payout contracts")
    for name in reversed(names):
        op.drop_table(name)
    db.execute(sa.text("DROP FUNCTION payout_contract_deny_mutation()"))
