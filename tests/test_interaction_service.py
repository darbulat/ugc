"""Tests for interaction service."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.entities import Interaction
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.memory_repositories import InMemoryInteractionRepository


@pytest.mark.asyncio
async def test_get_or_create_interaction() -> None:
    """Create interaction when missing."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000901"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000902"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000903"),
    )

    assert interaction.status == InteractionStatus.PENDING
    found = await repo.get_by_id(interaction.interaction_id)
    assert found is not None


@pytest.mark.asyncio
async def test_get_or_create_returns_existing() -> None:
    """Return existing interaction when available."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    existing = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000901"),
        order_id=UUID("00000000-0000-0000-0000-000000000902"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000903"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000904"),
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(existing)

    result = await service.get_or_create(
        order_id=existing.order_id,
        blogger_id=existing.blogger_id,
        advertiser_id=existing.advertiser_id,
    )
    assert result.interaction_id == existing.interaction_id


@pytest.mark.asyncio
async def test_record_advertiser_feedback() -> None:
    """Update interaction with advertiser feedback."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000911"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000912"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000913"),
    )

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "✅ Сделка состоялась"
    )
    assert updated.from_advertiser == "✅ Сделка состоялась"
    assert updated.status == InteractionStatus.OK


@pytest.mark.asyncio
async def test_record_blogger_feedback_issue() -> None:
    """Issue from blogger should set ISSUE status."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000921"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000922"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000923"),
    )
    updated = await service.record_blogger_feedback(
        interaction.interaction_id, "⚠️ Проблема / подозрение на мошенничество"
    )
    assert updated.from_blogger == "⚠️ Проблема / подозрение на мошенничество"
    assert updated.status == InteractionStatus.ISSUE


@pytest.mark.asyncio
async def test_record_advertiser_feedback_no_deal_aggregate() -> None:
    """Aggregate NO_DEAL when both sides choose it."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000931"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000932"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000933"),
    )
    await repo.save(
        Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=interaction.status,
            from_advertiser=None,
            from_blogger="❌ Не договорились",
            postpone_count=interaction.postpone_count,
            next_check_at=interaction.next_check_at,
            created_at=interaction.created_at,
            updated_at=interaction.updated_at,
        )
    )
    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "❌ Не договорились"
    )
    assert updated.status == InteractionStatus.NO_DEAL


@pytest.mark.asyncio
async def test_record_feedback_missing_interaction() -> None:
    """Raise when interaction does not exist."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    with pytest.raises(ValueError):
        await service.record_advertiser_feedback(
            UUID("00000000-0000-0000-0000-000000000940"),
            "✅ Сделка состоялась",
        )


def test_aggregate_defaults_to_pending() -> None:
    """Default aggregation when no input is provided."""

    assert (
        InteractionService._aggregate(None, None)  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )


@pytest.mark.asyncio
async def test_record_advertiser_feedback_pending() -> None:
    """Postpone interaction when advertiser chooses PENDING."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo, max_postpone_count=3)
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000951"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000952"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000953"),
    )

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "⏳ Еще не связался"
    )
    assert updated.from_advertiser == "⏳ Еще не связался"
    assert updated.status == InteractionStatus.PENDING
    assert updated.postpone_count == 1
    assert updated.next_check_at is not None


@pytest.mark.asyncio
async def test_record_advertiser_feedback_max_postpone() -> None:
    """Auto-resolve to NO_DEAL when max postpone count reached."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo, max_postpone_count=3)
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000961"),
        order_id=UUID("00000000-0000-0000-0000-000000000962"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000963"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000964"),
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=3,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "⏳ Еще не связался"
    )
    assert updated.status == InteractionStatus.NO_DEAL


@pytest.mark.asyncio
async def test_record_blogger_feedback_pending() -> None:
    """Postpone interaction when blogger chooses PENDING."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo, max_postpone_count=3)
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000971"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000972"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000973"),
    )

    updated = await service.record_blogger_feedback(
        interaction.interaction_id, "⏳ Еще не связался"
    )
    assert updated.from_blogger == "⏳ Еще не связался"
    assert updated.status == InteractionStatus.PENDING
    assert updated.postpone_count == 1
    assert updated.next_check_at is not None


@pytest.mark.asyncio
async def test_record_blogger_feedback_max_postpone() -> None:
    """Auto-resolve to NO_DEAL when max postpone count reached."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo, max_postpone_count=3)
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000981"),
        order_id=UUID("00000000-0000-0000-0000-000000000982"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000983"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000984"),
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=3,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    updated = await service.record_blogger_feedback(
        interaction.interaction_id, "⏳ Еще не связался"
    )
    assert updated.status == InteractionStatus.NO_DEAL


@pytest.mark.asyncio
async def test_postpone_interaction_max_reached() -> None:
    """Auto-resolve to NO_DEAL when postponing after max count."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo, max_postpone_count=3)
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000991"),
        order_id=UUID("00000000-0000-0000-0000-000000000992"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000993"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000994"),
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=3,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    updated = await service._postpone_interaction(
        interaction, "advertiser", "⏳ Еще не связался"
    )
    assert updated.status == InteractionStatus.NO_DEAL
    assert updated.next_check_at is None
    assert updated.postpone_count == 4


def test_parse_feedback_pending() -> None:
    """Parse feedback text for PENDING status."""

    assert (
        InteractionService._parse_feedback("⏳ Еще не связался")  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )
    assert (
        InteractionService._parse_feedback("еще не связался")  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )


def test_aggregate_pending_from_advertiser() -> None:
    """Aggregate PENDING when advertiser chooses it."""

    assert (
        InteractionService._aggregate("⏳ Еще не связался", None)  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )


def test_aggregate_pending_from_blogger() -> None:
    """Aggregate PENDING when blogger chooses it."""

    assert (
        InteractionService._aggregate(None, "⏳ Еще не связался")  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )


def test_aggregate_one_no_deal_waiting() -> None:
    """Wait for other side when only one responds with NO_DEAL."""

    assert (
        InteractionService._aggregate("❌ Не договорились", None)  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )
    assert (
        InteractionService._aggregate(None, "❌ Не договорились")  # type: ignore[arg-type]
        == InteractionStatus.PENDING
    )


def test_aggregate_fallback_no_deal() -> None:
    """Fallback to NO_DEAL for unrecognized feedback."""

    assert (
        InteractionService._aggregate("unknown", "unknown")  # type: ignore[arg-type]
        == InteractionStatus.NO_DEAL
    )


@pytest.mark.asyncio
async def test_manually_resolve_issue() -> None:
    """Manually resolve ISSUE interaction with final status."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000001001"),
        order_id=UUID("00000000-0000-0000-0000-000000001002"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001003"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001004"),
        status=InteractionStatus.ISSUE,
        from_advertiser="⚠️ Проблема",
        from_blogger="⚠️ Проблема",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    resolved = await service.manually_resolve_issue(
        interaction.interaction_id, InteractionStatus.OK
    )

    assert resolved.status == InteractionStatus.OK
    assert resolved.next_check_at is None
    assert resolved.interaction_id == interaction.interaction_id


@pytest.mark.asyncio
async def test_manually_resolve_issue_no_deal() -> None:
    """Manually resolve ISSUE interaction to NO_DEAL."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000001011"),
        order_id=UUID("00000000-0000-0000-0000-000000001012"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001013"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001014"),
        status=InteractionStatus.ISSUE,
        from_advertiser="⚠️ Проблема",
        from_blogger="⚠️ Проблема",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    resolved = await service.manually_resolve_issue(
        interaction.interaction_id, InteractionStatus.NO_DEAL
    )

    assert resolved.status == InteractionStatus.NO_DEAL
    assert resolved.next_check_at is None


@pytest.mark.asyncio
async def test_manually_resolve_issue_not_issue_status() -> None:
    """Raise error when resolving non-ISSUE interaction."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000001021"),
        order_id=UUID("00000000-0000-0000-0000-000000001022"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001023"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001024"),
        status=InteractionStatus.OK,
        from_advertiser="✅ Сделка состоялась",
        from_blogger="✅ Сделка состоялась",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    with pytest.raises(ValueError, match="not in ISSUE status"):
        await service.manually_resolve_issue(
            interaction.interaction_id, InteractionStatus.NO_DEAL
        )


@pytest.mark.asyncio
async def test_manually_resolve_issue_invalid_status() -> None:
    """Raise error when resolving with invalid final status."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000001031"),
        order_id=UUID("00000000-0000-0000-0000-000000001032"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001033"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001034"),
        status=InteractionStatus.ISSUE,
        from_advertiser="⚠️ Проблема",
        from_blogger="⚠️ Проблема",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction)

    with pytest.raises(ValueError, match="must be OK or NO_DEAL"):
        await service.manually_resolve_issue(
            interaction.interaction_id, InteractionStatus.PENDING
        )


@pytest.mark.asyncio
async def test_manually_resolve_issue_not_found() -> None:
    """Raise error when resolving non-existent interaction."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    with pytest.raises(ValueError, match="not found"):
        await service.manually_resolve_issue(
            UUID("00000000-0000-0000-0000-000000000999"), InteractionStatus.OK
        )
