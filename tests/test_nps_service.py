"""Tests for NPS service."""

from uuid import UUID

import pytest

from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.infrastructure.memory_repositories import InMemoryNpsRepository


@pytest.mark.asyncio
async def test_nps_service_save_without_transaction() -> None:
    """Save NPS when transaction_manager is None."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=None)
    user_id = UUID("00000000-0000-0000-0000-000000000001")

    await service.save(user_id, 5)

    assert repo.scores.get(user_id) == [(5, None)]


@pytest.mark.asyncio
async def test_nps_service_save_with_comment() -> None:
    """Save NPS with comment."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=None)
    user_id = UUID("00000000-0000-0000-0000-000000000002")

    await service.save(user_id, 4, comment="Great platform!")

    assert repo.scores.get(user_id) == [(4, "Great platform!")]


@pytest.mark.asyncio
async def test_nps_service_save_with_transaction(fake_tm) -> None:
    """Save NPS when transaction_manager is provided."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=fake_tm)
    user_id = UUID("00000000-0000-0000-0000-000000000003")

    await service.save(user_id, 4)

    assert repo.scores.get(user_id) == [(4, None)]


@pytest.mark.asyncio
async def test_nps_service_save_with_session() -> None:
    """Save NPS when session is explicitly provided."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=None)
    user_id = UUID("00000000-0000-0000-0000-000000000007")
    fake_session = object()

    await service.save(user_id, 5, session=fake_session)

    assert repo.scores.get(user_id) == [(5, None)]


@pytest.mark.asyncio
async def test_nps_service_exists_for_user() -> None:
    """exists_for_user returns True when user has NPS, False otherwise."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=None)
    user_id = UUID("00000000-0000-0000-0000-000000000004")
    other_id = UUID("00000000-0000-0000-0000-000000000005")

    assert await service.exists_for_user(user_id) is False
    assert await service.exists_for_user(other_id) is False

    await service.save(user_id, 3)

    assert await service.exists_for_user(user_id) is True
    assert await service.exists_for_user(other_id) is False


@pytest.mark.asyncio
async def test_nps_service_exists_for_user_with_transaction(fake_tm) -> None:
    """exists_for_user with transaction_manager uses transaction."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=fake_tm)
    user_id = UUID("00000000-0000-0000-0000-000000000006")

    assert await service.exists_for_user(user_id) is False

    await service.save(user_id, 5)

    assert await service.exists_for_user(user_id) is True


@pytest.mark.asyncio
async def test_nps_service_exists_for_user_with_session() -> None:
    """exists_for_user with session uses session."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=None)
    user_id = UUID("00000000-0000-0000-0000-000000000008")
    fake_session = object()

    assert await service.exists_for_user(user_id, session=fake_session) is False

    await service.save(user_id, 5, session=fake_session)

    assert await service.exists_for_user(user_id, session=fake_session) is True
