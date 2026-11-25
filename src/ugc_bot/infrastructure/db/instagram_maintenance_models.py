"""Additive availability evidence and a separate non-financial notice queue."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def maintenance_tables(metadata: sa.MetaData) -> tuple[sa.Table, ...]:
    def uid(name: str, target: str, **kw) -> sa.Column:
        return sa.Column(name, sa.Uuid(), sa.ForeignKey(target), **kw)

    def instant(name: str, **kw) -> sa.Column:
        return sa.Column(name, sa.DateTime(timezone=True), **kw)

    health = sa.Table(
        "instagram_profile_health",
        metadata,
        uid("user_id", "users.user_id", primary_key=True),
        sa.Column("meta_id", sa.String(100), nullable=False),
        sa.Column("id_kind", sa.String(30), nullable=False),
        sa.Column("identity_context", sa.String(200), nullable=False),
        sa.Column("handle", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        instant("last_failure_at"),
        instant("last_success_at"),
        instant("identity_since"),
        instant("metrics_observed_at"),
        instant("checked_at", nullable=False),
        sa.Column("episode", sa.Uuid(), nullable=False),
        sa.CheckConstraint("status IN ('healthy', 'suspect', 'review')"),
        sa.CheckConstraint("failure_count >= 0"),
        sa.CheckConstraint(
            "id_kind IN ('legacy_meta_id', 'instagram_scoped_id')"
        ),
        sa.CheckConstraint("length(trim(identity_context)) > 0"),
    )
    history = sa.Table(
        "instagram_profile_observations",
        metadata,
        sa.Column("observation_id", sa.Uuid(), primary_key=True),
        uid("user_id", "users.user_id", nullable=False, index=True),
        sa.Column("meta_id", sa.String(100), nullable=False),
        sa.Column("id_kind", sa.String(30), nullable=False),
        sa.Column("identity_context", sa.String(200), nullable=False),
        sa.Column("old_handle", sa.String(30), nullable=False),
        sa.Column("new_handle", sa.String(30), nullable=False),
        sa.Column("outcome", sa.String(30), nullable=False),
        instant("observed_at", nullable=False),
        sa.CheckConstraint(
            "outcome IN ('available', '100/33', 'not_found', 'verified')"
        ),
    )
    jobs = sa.Table(
        "instagram_profile_notices",
        metadata,
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        uid("creator_id", "users.user_id", nullable=False),
        uid("recipient_id", "users.user_id", nullable=False),
        uid("order_id", "orders.order_id"),
        sa.Column("purpose", sa.String(30), nullable=False),
        sa.Column("episode", sa.Uuid(), nullable=False),
        sa.Column("meta_id", sa.String(100), nullable=False),
        sa.Column("handle", sa.String(30), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("lease", sa.Uuid()),
        instant("lease_until"),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        instant("not_before", nullable=False),
        instant("created_at", nullable=False),
        instant("finished_at"),
        sa.Column("provider_reference", sa.String(200)),
        sa.Column("reason", sa.String(100)),
        sa.CheckConstraint(
            "state IN ('ready', 'sending', 'sent', 'failed', "
            "'unknown', 'obsolete')"
        ),
        sa.CheckConstraint(
            "(purpose = 'owner_refresh' AND recipient_id = creator_id "
            "AND order_id IS NULL) OR (purpose = 'customer_link' "
            "AND recipient_id <> creator_id AND order_id IS NOT NULL)"
        ),
        sa.CheckConstraint("attempt_count >= 0"),
        sa.Index("ix_instagram_profile_notices_due", "state", "not_before"),
    )
    return health, history, jobs


HEALTH, OBSERVATIONS, NOTICES = maintenance_tables(Base.metadata)
OFFER_CHECKS = sa.Table(
    "instagram_offer_checks",
    Base.metadata,
    sa.Column(
        "user_id",
        sa.Uuid(),
        sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("meta_id", sa.String(100), nullable=False),
    sa.Column("retry_at", sa.DateTime(timezone=True), nullable=False),
)


def instagram_available(profile):
    """An old failure for a different identity cannot suppress a new owner."""
    return ~sa.exists().where(
        HEALTH.c.user_id == profile.c.user_id,
        HEALTH.c.meta_id == profile.c.instagram_user_id,
        HEALTH.c.status == "review",
    )
