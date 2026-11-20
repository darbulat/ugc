"""Separate cached metrics and durable, daily request budget."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from ugc_bot.infrastructure.db.base import Base


def discovery_tables(metadata: sa.MetaData) -> tuple[sa.Table, sa.Table]:
    def instant(name: str, **kw) -> sa.Column:
        return sa.Column(name, sa.DateTime(timezone=True), **kw)

    profiles = sa.Table(
        "instagram_discovery_profiles",
        metadata,
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column("observed_meta_id", sa.String(100)),
        sa.Column("identity_context", sa.String(200)),
        sa.Column("username", sa.String(30)),
        sa.Column("discovery_object_id", sa.String(100)),
        sa.Column("discovery_context", sa.String(200)),
        sa.Column("followers_count", sa.BigInteger()),
        instant("followers_observed_at"),
        sa.Column("media_count", sa.BigInteger()),
        instant("media_observed_at"),
        sa.Column(
            "details",
            sa.JSON().with_variant(JSONB, "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        instant("observed_at"),
        sa.Column("attempt_meta_id", sa.String(100), nullable=False),
        sa.Column("attempt_profile_url", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        instant("attempted_at", nullable=False),
        instant("next_attempt_at", nullable=False, index=True),
        sa.Column("last_outcome", sa.String(40), nullable=False),
        sa.CheckConstraint("followers_count IS NULL OR followers_count >= 0"),
        sa.CheckConstraint("media_count IS NULL OR media_count >= 0"),
        sa.CheckConstraint(
            "(followers_count IS NULL) = (followers_observed_at IS NULL)"
        ),
        sa.CheckConstraint(
            "(media_count IS NULL) = (media_observed_at IS NULL)"
        ),
    )
    control = sa.Table(
        "instagram_discovery_control",
        metadata,
        sa.Column("singleton", sa.Integer(), primary_key=True),
        instant("next_run_at", nullable=False),
        sa.Column("lease_id", sa.Uuid()),
        instant("lease_until"),
        sa.Column("budget_day", sa.Date()),
        sa.Column(
            "requests_used", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("last_outcome", sa.String(40)),
        sa.CheckConstraint("singleton = 1"),
        sa.CheckConstraint("requests_used >= 0 AND requests_used <= 150"),
    )
    return profiles, control


DISCOVERY, DISCOVERY_CONTROL = discovery_tables(Base.metadata)
