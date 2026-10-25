"""Append-only operational decisions, separate from original unpaid leads."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

JSON_TYPE = sa.JSON().with_variant(JSONB(), "postgresql")


def review_table(metadata):
    return sa.Table(
        "accompaniment_lead_reviews",
        metadata,
        sa.Column("review_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("accompaniment_leads.lead_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("manager_ids", JSON_TYPE, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_key", sa.String(256), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", JSON_TYPE, nullable=False),
        sa.CheckConstraint(
            "version=1 AND state IN ('accepted','rejected')",
            name="ck_lead_review_terminal",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 4000",
            name="ck_lead_review_reason",
        ),
    )


def binding_table(metadata):
    return sa.Table(
        "referral_binding_corrections",
        metadata,
        sa.Column("correction_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("referred_id", UUID(as_uuid=True), nullable=False),
        sa.Column("previous_referrer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("referrer_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("operation_key", sa.String(256), nullable=False, unique=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", JSON_TYPE, nullable=False),
        sa.CheckConstraint(
            "referred_id<>referrer_id AND previous_referrer_id<>referrer_id",
            name="ck_referral_correction_distinct",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 4000",
            name="ck_referral_correction_reason",
        ),
    )


def install_immutability(connection, table):
    connection.exec_driver_sql("""
        CREATE OR REPLACE FUNCTION partner_admin_deny_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'partner admin decisions are immutable';
        END $$
    """)
    connection.exec_driver_sql(
        "CREATE TRIGGER partner_admin_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION partner_admin_deny_mutation()"
    )


def migration_metadata():
    metadata = sa.MetaData()
    for name, key in (
        ("users", "user_id"),
        ("orders", "order_id"),
        ("accompaniment_leads", "lead_id"),
    ):
        sa.Table(name, metadata, sa.Column(key, UUID, primary_key=True))
    return metadata
