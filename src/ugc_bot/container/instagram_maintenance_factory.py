"""An explicit opt-in, with one configured Meta app/business namespace."""

from ugc_bot.application.services.instagram_profile_maintenance import (
    InstagramProfileMaintenance,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.repositories.instagram_maintenance import (
    SqlAlchemyInstagramMaintenanceRepository,
)


def build_profile_maintenance(config: AppConfig | None, repos, transactions):
    if (
        config is None
        or not config.instagram.instagram_profile_maintenance_enabled
    ):
        return None
    if transactions is None:
        raise ValueError("instagram_maintenance_database_required")
    return InstagramProfileMaintenance(
        SqlAlchemyInstagramMaintenanceRepository(
            repos["blogger_repo"], config.instagram.instagram_identity_context
        ),
        transactions,
    )
