"""Immutable UUID facts survive canonical account merges."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from ugc_bot.infrastructure.db.base import Base

_metadata = Base.metadata

IDENTITY_OBSERVATIONS = sa.Table(
    "creator_identity_observations",
    _metadata,
    sa.Column(
        "observation_sequence", sa.BigInteger, sa.Identity(), primary_key=True
    ),
    sa.Column("creator_user_id", PG_UUID(as_uuid=True), nullable=False),
    sa.Column("instagram_user_id", sa.Text),
    sa.Column("active", sa.Boolean, nullable=False),
    sa.Column(
        "observed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.Column("fact_at", sa.DateTime(timezone=True)),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("business_key", sa.Text, nullable=False, unique=True),
    sa.CheckConstraint(
        "NOT active OR (instagram_user_id IS NOT NULL AND "
        "length(trim(instagram_user_id)) > 0)",
        name="ck_identity_observation_stable_id",
    ),
    sa.CheckConstraint(
        "fact_at IS NULL OR fact_at <= observed_at",
        name="ck_identity_observation_fact_time",
    ),
    sa.CheckConstraint(
        "source IN "
        "('canonical_profile_cutover','canonical_profile_observed','instagram_webhook','manual_code')",
        name="ck_identity_observation_source",
    ),
)
sa.Index(
    "ix_creator_identity_asof",
    IDENTITY_OBSERVATIONS.c.creator_user_id,
    IDENTITY_OBSERVATIONS.c.observed_at,
    IDENTITY_OBSERVATIONS.c.observation_sequence,
)

BINDING_OBSERVATIONS = sa.Table(
    "creator_direct_binding_observations",
    _metadata,
    sa.Column(
        "observation_sequence", sa.BigInteger, sa.Identity(), primary_key=True
    ),
    sa.Column("referrer_user_id", PG_UUID(as_uuid=True), nullable=False),
    sa.Column("referred_user_id", PG_UUID(as_uuid=True), nullable=False),
    sa.Column("active", sa.Boolean, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column(
        "observed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("clock_timestamp()"),
    ),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("business_key", sa.Text, nullable=False, unique=True),
    sa.CheckConstraint(
        "source IN ('direct_binding_cutover','direct_binding_observed')",
        name="ck_binding_observation_source",
    ),
)
sa.Index(
    "ix_creator_binding_asof",
    BINDING_OBSERVATIONS.c.referred_user_id,
    BINDING_OBSERVATIONS.c.observed_at,
    BINDING_OBSERVATIONS.c.observation_sequence,
)

IDENTITY_COVERAGE = sa.Table(
    "creator_identity_coverage",
    _metadata,
    sa.Column("coverage_key", sa.String(10), primary_key=True),
    sa.Column("covered_from", sa.DateTime(timezone=True), nullable=False),
    sa.Column("source", sa.Text, nullable=False),
    sa.Column("profile_seed_count", sa.Integer, nullable=False),
    sa.Column("binding_seed_count", sa.Integer, nullable=False),
    sa.Column("profile_seed_hash", sa.String(32), nullable=False),
    sa.Column("binding_seed_hash", sa.String(32), nullable=False),
    sa.CheckConstraint(
        "coverage_key = 'v1' AND source = 'canonical_cutover'",
        name="ck_identity_coverage_source",
    ),
    sa.CheckConstraint(
        "profile_seed_count >= 0 AND binding_seed_count >= 0",
        name="ck_identity_coverage_counts",
    ),
)

TABLES = (IDENTITY_OBSERVATIONS, BINDING_OBSERVATIONS, IDENTITY_COVERAGE)
