"""Social editor and Instagram proof use the production SQL dependency graph."""

from ugc_bot.application.services.social_account_service import (
    SocialAccountService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.infrastructure.db.repositories.social import (
    SqlAlchemySocialAccountRepository,
)


def test_container_shares_sql_social_repo_and_transaction_manager():
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
    services = container.build_bot_services()
    social = services.get("social_account_service")
    assert isinstance(social, SocialAccountService)
    assert isinstance(social.account_repo, SqlAlchemySocialAccountRepository)
    assert social.account_repo is repos["social_account_repo"]
    assert social.editor_repository is social.account_repo
    assert social.transaction_manager is container.transaction_manager
    assert (
        services["instagram_verification_service"].social_repo
        is social.account_repo
    )
    assert (
        container.build_instagram_verification_service().social_repo
        is social.account_repo
    )
