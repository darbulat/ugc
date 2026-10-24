"""Portable social link columns with PostgreSQL ownership constraints."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ugc_bot.infrastructure.db.base import Base


class SocialAccountModel(Base):
    __tablename__ = "creator_social_accounts"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id", "platform", name="uq_creator_social_platform"
        ),
        sa.CheckConstraint(
            "platform IN ('instagram', 'tiktok', 'youtube', 'telegram', 'vk')",
            name="ck_creator_social_platform",
        ),
        sa.CheckConstraint(
            "work_format IN ('ugc_only', 'ads_in_account')",
            name="ck_creator_social_work_format",
        ),
        sa.CheckConstraint(
            "NOT verified OR (platform = 'instagram' "
            "AND external_id IS NOT NULL "
            "AND length(trim(external_id)) > 0)",
            name="ck_creator_social_verified_identity",
        ),
        sa.CheckConstraint(
            "external_id IS NULL OR (platform = 'instagram' AND verified)",
            name="ck_creator_social_external_identity",
        ),
        sa.CheckConstraint(
            "(NOT verified AND verified_at IS NULL "
            "AND verification_observed_at IS NULL "
            "AND verification_source IS NULL) "
            "OR (verified AND verification_observed_at IS NOT NULL "
            "AND verification_source IS NOT NULL "
            "AND length(trim(verification_source)) > 0 "
            "AND (verified_at IS NULL "
            "OR verified_at <= verification_observed_at))",
            name="ck_creator_social_verification_provenance",
        ),
        sa.CheckConstraint(
            "(followers_count IS NULL AND metrics_source IS NULL "
            "AND metrics_fetched_at IS NULL) OR "
            "(followers_count IS NOT NULL AND followers_count >= 0 "
            "AND metrics_source IS NOT NULL "
            "AND length(trim(metrics_source)) > 0 "
            "AND metrics_fetched_at IS NOT NULL)",
            name="ck_creator_social_observed_metrics",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    url: Mapped[str] = mapped_column(sa.Text, nullable=False)
    handle: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    external_id: Mapped[str | None] = mapped_column(sa.String(100))
    work_format: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    followers_count: Mapped[int | None] = mapped_column(sa.BigInteger)
    metrics_source: Mapped[str | None] = mapped_column(sa.String(100))
    metrics_fetched_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    verification_observed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    verification_source: Mapped[str | None] = mapped_column(sa.String(100))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


sa.Index(
    "uq_creator_social_verified_instagram_identity",
    SocialAccountModel.external_id,
    unique=True,
    postgresql_where=sa.text("platform = 'instagram' AND verified"),
    sqlite_where=sa.text("platform = 'instagram' AND verified"),
)
