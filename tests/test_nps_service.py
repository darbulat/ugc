"""Tests for NPS service."""

import pytest
from uuid import UUID

from ugc_bot.application.services.nps_service import NpsService
from ugc_bot.infrastructure.memory_repositories import InMemoryNpsRepository


@pytest.mark.asyncio
async def test_nps_service_save_without_transaction() -> None:
    """Save NPS when transaction_manager is None."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=None)
    interaction_id = UUID("00000000-0000-0000-0000-000000000001")

    await service.save(interaction_id, 5)

    assert repo.scores.get(interaction_id) == [5]


@pytest.mark.asyncio
async def test_nps_service_save_with_transaction(fake_tm) -> None:
    """Save NPS when transaction_manager is provided."""

    repo = InMemoryNpsRepository()
    service = NpsService(nps_repo=repo, transaction_manager=fake_tm)
    interaction_id = UUID("00000000-0000-0000-0000-000000000002")

    await service.save(interaction_id, 4)

    assert repo.scores.get(interaction_id) == [4]
