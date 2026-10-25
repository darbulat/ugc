"""Append-only campaign lifecycle, quota, delivery and response records."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def runtime_tables(metadata):
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")

    def ident(name, **kwargs):
        return sa.Column(name, UUID(as_uuid=True), **kwargs)

    def document():
        return sa.Column("document", json_type, nullable=False)

    def recorded():
        return sa.Column(
            "recorded_at", sa.DateTime(timezone=True), nullable=False
        )

    commands = sa.Table(
        "campaign_runtime_commands",
        metadata,
        ident("actor_id", primary_key=True),
        sa.Column("operation_key", sa.String(256), primary_key=True),
        document(),
        recorded(),
        sa.CheckConstraint(
            "length(trim(operation_key))>0",
            name="ck_campaign_runtime_command_key",
        ),
    )
    states = sa.Table(
        "campaign_runtime_states",
        metadata,
        ident("campaign_id", primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        ident("owner_id", nullable=False, index=True),
        sa.Column("state", sa.String(24), nullable=False),
        document(),
        recorded(),
        sa.CheckConstraint(
            "version > 0", name="ck_campaign_runtime_state_version"
        ),
    )
    submissions = sa.Table(
        "campaign_runtime_submissions",
        metadata,
        ident("submission_id", primary_key=True),
        ident("campaign_id", nullable=False, index=True),
        ident("owner_id", nullable=False),
        document(),
        recorded(),
    )
    decisions = sa.Table(
        "campaign_runtime_decisions",
        metadata,
        ident("review_id", primary_key=True),
        ident("submission_id", nullable=False, unique=True),
        document(),
        recorded(),
        sa.ForeignKeyConstraint(
            ("submission_id",), ("campaign_runtime_submissions.submission_id",)
        ),
    )
    jobs = sa.Table(
        "campaign_runtime_jobs",
        metadata,
        ident("job_id", primary_key=True),
        ident("campaign_id", nullable=False, index=True),
        ident("submission_id", nullable=False),
        ident("review_id", nullable=False),
        ident("source_id", nullable=False),
        ident("recipient_id", nullable=False),
        document(),
        recorded(),
        sa.UniqueConstraint(
            "submission_id", "source_id", name="uq_campaign_runtime_source_job"
        ),
        sa.ForeignKeyConstraint(
            ("submission_id",), ("campaign_runtime_submissions.submission_id",)
        ),
        sa.ForeignKeyConstraint(
            ("review_id",), ("campaign_runtime_decisions.review_id",)
        ),
    )
    capacity = sa.Table(
        "campaign_runtime_capacity",
        metadata,
        sa.Column(
            "sequence",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
            autoincrement=True,
        ),
        ident("event_id", nullable=False, unique=True),
        sa.Column("kind", sa.String(24), nullable=False),
        document(),
        recorded(),
    )
    attempts = sa.Table(
        "campaign_runtime_attempts",
        metadata,
        ident("attempt_id", primary_key=True),
        ident("job_id", nullable=False, unique=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        document(),
        recorded(),
        sa.ForeignKeyConstraint(("job_id",), ("campaign_runtime_jobs.job_id",)),
    )
    outcomes = sa.Table(
        "campaign_runtime_outcomes",
        metadata,
        ident("outcome_id", primary_key=True),
        ident("job_id", nullable=False, unique=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("provider_reference", sa.String(256), unique=True),
        sa.Column("reason", sa.String(100)),
        recorded(),
        sa.ForeignKeyConstraint(("job_id",), ("campaign_runtime_jobs.job_id",)),
        sa.CheckConstraint(
            "state IN ('accepted','failed','unknown','skipped')",
            name="ck_campaign_runtime_outcome_state",
        ),
    )
    responses = sa.Table(
        "campaign_runtime_responses",
        metadata,
        ident("recipient_id", primary_key=True),
        sa.Column("operation_key", sa.String(256), primary_key=True),
        ident("campaign_id", nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("choice", sa.String(24), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        recorded(),
        sa.UniqueConstraint(
            "campaign_id",
            "recipient_id",
            "version",
            name="uq_campaign_response_version",
        ),
        sa.CheckConstraint(
            "choice IN ('interested','declined','withdrawn') AND version>0",
            name="ck_campaign_response_choice",
        ),
    )
    observations = sa.Table(
        "campaign_runtime_transport_observations",
        metadata,
        ident("observation_id", primary_key=True),
        ident("attempt_id", nullable=False),
        ident("job_id", nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("provider_reference", sa.String(256)),
        sa.Column("reason", sa.String(100)),
        recorded(),
        sa.ForeignKeyConstraint(
            ("attempt_id",), ("campaign_runtime_attempts.attempt_id",)
        ),
        sa.ForeignKeyConstraint(("job_id",), ("campaign_runtime_jobs.job_id",)),
    )
    return (
        commands,
        states,
        submissions,
        decisions,
        jobs,
        capacity,
        attempts,
        outcomes,
        responses,
        observations,
    )


def immutability_sql(tables):
    return """CREATE OR REPLACE FUNCTION campaign_runtime_deny_mutation()
RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'campaign_runtime_immutable' USING ERRCODE='23514'; END $$;
""" + "\n".join(
        "CREATE TRIGGER campaign_runtime_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION campaign_runtime_deny_mutation();"
        for table in tables
    )
