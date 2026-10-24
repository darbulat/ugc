"""Production lifecycle commands share SQL transactions with their outbox."""

from datetime import datetime, timezone

import pytest

from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.repositories.collaborations import (
    SqlAlchemyCollaborationRepository,
)


def test_container_wires_real_lifecycle_repository_and_server_clock():
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
    services = container.build_bot_services()
    service = services.get("collaboration_service")
    assert isinstance(service, CollaborationService)
    assert isinstance(service.repository, SqlAlchemyCollaborationRepository)
    assert service.repository is container.build_repos()["collaboration_repo"]
    before = datetime.now(timezone.utc)
    actual = service.clock.now()
    assert actual.tzinfo is not None
    assert before <= actual <= datetime.now(timezone.utc)
    assert config.financial.core_enabled is False


def test_container_sweep_shares_sql_repo_and_transactions():
    config = AppConfig.model_validate(
        {"BOT_TOKEN": "test-token", "DATABASE_URL": "sqlite:///:memory:"}
    )
    container = Container(config)
    sweep = container.build_collaboration_sweep()
    assert (
        sweep.lifecycle.repository
        is container.build_repos()["collaboration_repo"]
    )
    assert sweep.transactions is container.transaction_manager


def test_sweep_factory_requires_database():
    config = AppConfig.model_validate(
        {"BOT_TOKEN": "test-token", "DATABASE_URL": ""}
    )
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Container(config).build_collaboration_sweep()
