"""Payment snapshot producers use the historical verification reader."""

from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.repositories.identity_history import (
    SqlAlchemyCreatorIdentityHistoryRepository,
)


def test_container_wires_sql_history_reader_without_inventing_counts():
    config = AppConfig.model_validate(
        {
            "BOT_TOKEN": "test-token",
            "DATABASE_URL": "sqlite:///:memory:",
            "KAFKA_ENABLED": False,
            "USE_REDIS_STORAGE": False,
            "REDIS_URL": "",
        }
    )
    container = Container(config)
    repos = container.build_repos()
    service = container.build_bot_services().get(
        "creator_identity_history_service"
    )
    assert isinstance(service, CreatorIdentityHistoryService)
    assert isinstance(
        service.repository, SqlAlchemyCreatorIdentityHistoryRepository
    )
    assert service.repository is repos["creator_identity_history_repo"]
