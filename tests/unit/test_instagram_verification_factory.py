"""Verification facts share one SQL transaction in every Redis configuration."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from ugc_bot.application.legacy_link_ports import LegacySqlParticipant
from ugc_bot.container.repository_factory import build_repos
from ugc_bot.container.service_factory import (
    build_instagram_verification_service,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyInstagramVerificationRepository,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.mark.parametrize(
    "redis_url", [None, "", "redis://synthetic-verification.invalid/0"]
)
def test_verification_factory_keeps_all_facts_in_one_sql_boundary(
    redis_url: str | None,
) -> None:
    # No engine, URL connection, lifespan or repository I/O is constructed.
    sessions = async_sessionmaker()
    transactions = SessionTransactionManager(sessions)
    repos = build_repos(sessions, redis_url=redis_url)
    service = build_instagram_verification_service(repos, None, transactions)

    assert isinstance(
        repos["instagram_repo"], SqlAlchemyInstagramVerificationRepository
    )
    for name in (
        "user_repo",
        "blogger_repo",
        "instagram_repo",
        "social_account_repo",
    ):
        repository = repos[name]
        assert isinstance(repository, LegacySqlParticipant)
        assert repository.session_factory is sessions

    assert service.transaction_manager is transactions
    assert service.user_repo is repos["user_repo"]
    assert service.blogger_repo is repos["blogger_repo"]
    assert service.verification_repo is repos["instagram_repo"]
    assert service.social_repo is repos["social_account_repo"]
    assert service.user_role_service is not None
    assert service.user_role_service.transaction_manager is transactions
    assert service.user_role_service.user_repo is repos["user_repo"]
    assert (
        service.user_role_service.blogger_profile_repo is repos["blogger_repo"]
    )
