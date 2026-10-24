"""Canonical creator social links; reject ambiguous historic identities."""

from typing import cast

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.social_models import SocialAccountModel

revision = "creator_social_v1"
down_revision = "management_reward_std"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Keep preflight and index creation under the same writer barrier.
    connection.execute(
        sa.text("LOCK TABLE blogger_profiles IN ACCESS EXCLUSIVE MODE")
    )
    duplicate = connection.execute(
        sa.text(
            "SELECT trim(instagram_user_id) FROM blogger_profiles "
            "WHERE confirmed AND trim(instagram_user_id) <> '' "
            "GROUP BY trim(instagram_user_id) HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Resolve duplicate verified Instagram identities before migration; "
            "existing profiles have not been changed"
        )
    op.create_index(
        "uq_blogger_verified_instagram_identity",
        "blogger_profiles",
        [sa.text("trim(instagram_user_id)")],
        unique=True,
        postgresql_where=sa.text("confirmed AND trim(instagram_user_id) <> ''"),
    )
    # This table has no geometry. Emit its DDL directly so unrelated spatial
    # plugin callbacks cannot mutate the shared ORM metadata during migration.
    table = cast(sa.Table, SocialAccountModel.__table__)
    connection.execute(sa.schema.CreateTable(table))
    for index in sorted(table.indexes, key=lambda index: index.name or ""):
        connection.execute(sa.schema.CreateIndex(index))
    # Observe the current state without inventing the original proof date.
    # Profiles without stable IDs remain readable through the profile service.
    connection.execute(
        sa.text(
            """
            INSERT INTO creator_social_accounts (
                account_id, user_id, platform, url, handle, verified,
                external_id, work_format, followers_count, metrics_source,
                metrics_fetched_at,
                created_at, updated_at, verified_at, verification_observed_at,
                verification_source
            )
            SELECT uuid_generate_v5(user_id, 'instagram'), user_id, 'instagram',
                instagram_url, COALESCE(instagram_username, ''), true,
                trim(instagram_user_id), work_format::text,
                CASE WHEN instagram_stats_fetched_at IS NOT NULL
                     THEN instagram_followers_count END,
                CASE WHEN instagram_stats_fetched_at IS NOT NULL
                          AND instagram_followers_count IS NOT NULL
                     THEN 'legacy_profile' END,
                CASE WHEN instagram_followers_count IS NOT NULL
                     THEN instagram_stats_fetched_at END,
                created_at, updated_at, NULL, transaction_timestamp(),
                'legacy_profile_cutover'
            FROM blogger_profiles
            WHERE confirmed AND trim(instagram_user_id) <> ''
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text("LOCK TABLE creator_social_accounts IN ACCESS EXCLUSIVE MODE")
    )
    if connection.execute(
        sa.text("SELECT 1 FROM creator_social_accounts LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard existing creator social accounts")
    connection.execute(
        sa.schema.DropTable(cast(sa.Table, SocialAccountModel.__table__))
    )
    op.drop_index(
        "uq_blogger_verified_instagram_identity", table_name="blogger_profiles"
    )
