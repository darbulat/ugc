"""Frozen readable payout contracts companion; no mutation of P01 DDL."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION payout_contract_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'payout_contract_immutable' USING ERRCODE='23514';
END $$;
"""


def contract_tables(metadata):
    def uid(name, target=None, **kw):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *([sa.ForeignKey(target)] if target else []),
            **kw,
        )

    documents = sa.Table(
        "financial_payout_terms_documents",
        metadata,
        uid("document_id", primary_key=True),
        sa.Column("content_text", sa.Text, nullable=False),
        sa.Column("source_locale", sa.String(35), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        uid("publisher_id", "users.user_id", nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("document_id", "sha256"),
        sa.CheckConstraint(
            "length(trim(content_text))>0 AND "
            "octet_length(content_text)<=1000000 AND "
            "length(trim(source_locale))>0 AND length(sha256)=64"
        ),
    )
    bindings = sa.Table(
        "financial_payout_requirement_contracts",
        metadata,
        uid(
            "requirements_id",
            "financial_payout_requirements.requirements_id",
            primary_key=True,
        ),
        uid("document_id", nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "field_definitions",
            sa.JSON().with_variant(JSONB, "postgresql"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ("document_id", "sha256"),
            (
                "financial_payout_terms_documents.document_id",
                "financial_payout_terms_documents.sha256",
            ),
        ),
        sa.UniqueConstraint("requirements_id", "document_id", "sha256"),
    )
    acceptances = sa.Table(
        "financial_payout_requisites_acceptances",
        metadata,
        uid("requisites_id", primary_key=True),
        uid("recipient_id", nullable=False),
        uid("requirements_id", nullable=False),
        uid("document_id", nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("accepted", sa.Boolean, nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ("requisites_id", "recipient_id", "requirements_id"),
            (
                "financial_payout_requisites.requisites_id",
                "financial_payout_requisites.recipient_id",
                "financial_payout_requisites.requirements_id",
            ),
        ),
        sa.ForeignKeyConstraint(
            ("requirements_id", "document_id", "sha256"),
            (
                "financial_payout_requirement_contracts.requirements_id",
                "financial_payout_requirement_contracts.document_id",
                "financial_payout_requirement_contracts.sha256",
            ),
        ),
        sa.CheckConstraint("accepted IS TRUE"),
    )
    return {
        "documents": documents,
        "bindings": bindings,
        "acceptances": acceptances,
    }


def install_contract_guards(connection, tables):
    connection.execute(sa.text(IMMUTABILITY_SQL))
    for table in tables:
        connection.execute(
            sa.text(
                "CREATE TRIGGER payout_contract_immutable BEFORE UPDATE "
                f"OR DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION payout_contract_deny_mutation()"
            )
        )
