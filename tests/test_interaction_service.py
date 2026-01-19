"""Tests for interaction service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryInteractionRepository


def test_get_or_create_interaction() -> None:
    """Create interaction when missing."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    interaction = service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000902"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000903"),
    )

    assert interaction.status == InteractionStatus.NO_DEAL
    assert repo.get_by_id(interaction.interaction_id) is not None


def test_get_or_create_returns_existing() -> None:
    """Return existing interaction when available."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    existing = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000901"),
        order_id=UUID("00000000-0000-0000-0000-000000000902"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000903"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000904"),
        status=InteractionStatus.NO_DEAL,
        from_advertiser=None,
        from_blogger=None,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(existing)

    result = service.get_or_create(
        order_id=existing.order_id,
        blogger_id=existing.blogger_id,
        advertiser_id=existing.advertiser_id,
    )
    assert result.interaction_id == existing.interaction_id


def test_record_advertiser_feedback() -> None:
    """Update interaction with advertiser feedback."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000911"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000912"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000913"),
    )

    updated = service.record_advertiser_feedback(
        interaction.interaction_id, InteractionStatus.OK
    )
    assert updated.from_advertiser == InteractionStatus.OK.value
    assert updated.status == InteractionStatus.OK


def test_record_blogger_feedback_issue() -> None:
    """Issue from blogger should set ISSUE status."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000921"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000922"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000923"),
    )
    updated = service.record_blogger_feedback(
        interaction.interaction_id, InteractionStatus.ISSUE
    )
    assert updated.from_blogger == InteractionStatus.ISSUE.value
    assert updated.status == InteractionStatus.ISSUE


def test_record_advertiser_feedback_no_deal_aggregate() -> None:
    """Aggregate NO_DEAL when both sides choose it."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000931"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000932"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000933"),
    )
    repo.save(
        Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=interaction.status,
            from_advertiser=None,
            from_blogger=InteractionStatus.NO_DEAL.value,
            created_at=interaction.created_at,
        )
    )
    updated = service.record_advertiser_feedback(
        interaction.interaction_id, InteractionStatus.NO_DEAL
    )
    assert updated.status == InteractionStatus.NO_DEAL


def test_record_feedback_missing_interaction() -> None:
    """Raise when interaction does not exist."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    with pytest.raises(ValueError):
        service.record_advertiser_feedback(
            UUID("00000000-0000-0000-0000-000000000940"),
            InteractionStatus.OK,
        )


def test_aggregate_defaults_to_no_deal() -> None:
    """Default aggregation when no input is provided."""

    assert (
        InteractionService._aggregate(None, None)  # type: ignore[arg-type]
        == InteractionStatus.NO_DEAL
    )
