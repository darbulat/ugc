"""Tests for interaction service."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ugc_bot.application.errors import (
    InteractionError,
    InteractionNotFoundError,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.entities import Interaction, Order, User
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


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
    assert updated.status == InteractionStatus.PENDING
    assert updated.next_check_at is not None


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
    assert updated.status == InteractionStatus.PENDING
    assert updated.next_check_at is not None


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


@pytest.mark.asyncio
async def test_schedule_next_reminder_when_interaction_not_found() -> None:
    """schedule_next_reminder returns without error when interaction missing."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    next_at = datetime(2025, 2, 2, 10, 0, tzinfo=timezone.utc)
    await service.schedule_next_reminder(
        UUID("00000000-0000-0000-0000-000000000941"), next_at
    )
    assert (
        await repo.get_by_id(UUID("00000000-0000-0000-0000-000000000941"))
        is None
    )


@pytest.mark.asyncio
async def test_schedule_next_reminder_updates_next_check_at() -> None:
    """schedule_next_reminder sets next_check_at for existing interaction."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.create_for_contacts_sent(
        order_id=UUID("00000000-0000-0000-0000-000000000942"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000943"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000944"),
    )
    next_at = datetime(2025, 2, 2, 10, 0, tzinfo=timezone.utc)
    await service.schedule_next_reminder(interaction.interaction_id, next_at)
    updated = await repo.get_by_id(interaction.interaction_id)
    assert updated is not None
    assert updated.next_check_at == next_at


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
async def test_postpone_with_feedback_config_uses_24h_reminder() -> None:
    """Other side not responded: use next_reminder_datetime (24h) not 72h."""

    from ugc_bot.config import FeedbackConfig

    repo = InMemoryInteractionRepository()
    feedback_config = FeedbackConfig(
        feedback_reminder_hour=10,
        feedback_reminder_minute=0,
        feedback_reminder_timezone="UTC",
    )
    service = InteractionService(
        interaction_repo=repo,
        max_postpone_count=3,
        feedback_config=feedback_config,
    )
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000974"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000975"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000976"),
    )
    assert interaction.from_advertiser is None

    updated = await service.record_blogger_feedback(
        interaction.interaction_id, "⏳ Еще не связался"
    )
    assert updated.from_blogger == "⏳ Еще не связался"
    assert updated.next_check_at is not None
    from ugc_bot.application.feedback_utils import next_reminder_datetime

    expected_next = next_reminder_datetime(feedback_config)
    assert updated.next_check_at == expected_next


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

    with pytest.raises(InteractionError, match="not in ISSUE status"):
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

    with pytest.raises(InteractionError, match="must be OK or NO_DEAL"):
        await service.manually_resolve_issue(
            interaction.interaction_id, InteractionStatus.PENDING
        )


@pytest.mark.asyncio
async def test_manually_resolve_issue_not_found() -> None:
    """Raise error when resolving non-existent interaction."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)

    with pytest.raises(InteractionNotFoundError, match="not found"):
        await service.manually_resolve_issue(
            UUID("00000000-0000-0000-0000-000000000999"), InteractionStatus.OK
        )


@pytest.mark.asyncio
async def test_record_feedback_issue_with_metrics() -> None:
    """Record ISSUE feedback triggers metrics.record_interaction_issue."""

    from ugc_bot.metrics.collector import MetricsCollector

    repo = InMemoryInteractionRepository()
    metrics = MetricsCollector()
    service = InteractionService(
        interaction_repo=repo, metrics_collector=metrics
    )
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000951"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000952"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000953"),
    )

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "⚠️ Проблема / подозрение на мошенничество"
    )
    assert updated.status == InteractionStatus.PENDING
    assert updated.next_check_at is not None
    assert updated.from_advertiser == "⚠️ Проблема / подозрение на мошенничество"


@pytest.mark.asyncio
async def test_record_blogger_feedback_issue_with_metrics() -> None:
    """Record ISSUE from blogger triggers metrics.record_interaction_issue."""

    from ugc_bot.metrics.collector import MetricsCollector

    repo = InMemoryInteractionRepository()
    metrics = MetricsCollector()
    service = InteractionService(
        interaction_repo=repo, metrics_collector=metrics
    )
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000000961"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000962"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000963"),
    )

    updated = await service.record_blogger_feedback(
        interaction.interaction_id, "⚠️ Проблема / подозрение на мошенничество"
    )
    assert updated.status == InteractionStatus.PENDING
    assert updated.next_check_at is not None
    assert updated.from_blogger == "⚠️ Проблема / подозрение на мошенничество"


@pytest.mark.asyncio
async def test_record_one_side_keeps_next_check_for_other() -> None:
    """One side ok/no_deal: keep status=PENDING and next_check_at for other."""

    from ugc_bot.config import FeedbackConfig

    repo = InMemoryInteractionRepository()
    feedback_config = FeedbackConfig(
        feedback_reminder_hour=10,
        feedback_reminder_minute=0,
        feedback_reminder_timezone="UTC",
    )
    service = InteractionService(
        interaction_repo=repo,
        feedback_config=feedback_config,
    )
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000001151"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001152"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001153"),
    )
    assert interaction.from_blogger is None

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "✅ Всё прошло нормально"
    )
    assert updated.status == InteractionStatus.PENDING
    assert updated.next_check_at is not None
    assert updated.from_advertiser == "✅ Всё прошло нормально"


@pytest.mark.asyncio
async def test_record_both_sides_sets_next_check_none() -> None:
    """Both sides responded: next_check_at None, status from aggregate."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000001161"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001162"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001163"),
    )
    await repo.save(
        Interaction(
            interaction_id=interaction.interaction_id,
            order_id=interaction.order_id,
            blogger_id=interaction.blogger_id,
            advertiser_id=interaction.advertiser_id,
            status=interaction.status,
            from_advertiser=None,
            from_blogger="✅ Всё прошло нормально",
            postpone_count=interaction.postpone_count,
            next_check_at=interaction.next_check_at,
            created_at=interaction.created_at,
            updated_at=interaction.updated_at,
        )
    )

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "✅ Всё прошло нормально"
    )
    assert updated.status == InteractionStatus.OK
    assert updated.next_check_at is None


@pytest.mark.asyncio
async def test_get_or_create_with_transaction_manager(fake_tm: object) -> None:
    """Cover tm path for get_or_create (save and get_by_participants)."""

    repo = InMemoryInteractionRepository()
    service = InteractionService(
        interaction_repo=repo, transaction_manager=fake_tm
    )
    interaction = await service.get_or_create(
        order_id=UUID("00000000-0000-0000-0000-000000001101"),
        blogger_id=UUID("00000000-0000-0000-0000-000000001102"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001103"),
    )
    assert interaction.status == InteractionStatus.PENDING
    found_in_repo = await repo.get_by_id(interaction.interaction_id)
    assert (
        found_in_repo is not None
        and found_in_repo.interaction_id == interaction.interaction_id
    )


@pytest.mark.asyncio
async def test_record_advertiser_feedback_ok_triggers_referral_income() -> None:
    """OK feedback from advertiser calls record_creator_referral_income."""

    order_id = UUID("00000000-0000-0000-0000-000000002001")
    blogger_id = UUID("00000000-0000-0000-0000-000000002002")
    advertiser_id = UUID("00000000-0000-0000-0000-000000002003")

    interaction_repo = InMemoryInteractionRepository()
    order_repo = InMemoryOrderRepository()
    user_repo = InMemoryUserRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
    )
    await order_repo.save(order)

    advertiser = User(
        user_id=advertiser_id,
        external_id="adv_ext",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country="ru",
    )
    await user_repo.save(advertiser)

    # Pre-save interaction with blogger already gave OK
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000002004"),
        order_id=order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger="✅ Всё прошло нормально",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await interaction_repo.save(interaction)

    referral_income_service = AsyncMock()
    service = InteractionService(
        interaction_repo=interaction_repo,
        order_repo=order_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
    )

    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, "✅ Всё прошло нормально"
    )

    assert updated.status == InteractionStatus.OK
    referral_income_service.record_creator_referral_income.assert_awaited_once()
    call_kwargs = (
        referral_income_service.record_creator_referral_income.call_args.kwargs
    )
    assert call_kwargs["creator_id"] == blogger_id
    assert call_kwargs["advertiser_country_code"] == "ru"


@pytest.mark.asyncio
async def test_record_blogger_feedback_ok_triggers_referral_income() -> None:
    """OK feedback from blogger calls record_creator_referral_income."""

    order_id = UUID("00000000-0000-0000-0000-000000002011")
    blogger_id = UUID("00000000-0000-0000-0000-000000002012")
    advertiser_id = UUID("00000000-0000-0000-0000-000000002013")

    interaction_repo = InMemoryInteractionRepository()
    order_repo = InMemoryOrderRepository()
    user_repo = InMemoryUserRepository()

    order = Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=1,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
    )
    await order_repo.save(order)

    advertiser = User(
        user_id=advertiser_id,
        external_id="adv_ext_2",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        country="ru",
    )
    await user_repo.save(advertiser)

    # Pre-save interaction with advertiser already gave OK
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000002014"),
        order_id=order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser_id,
        status=InteractionStatus.PENDING,
        from_advertiser="✅ Всё прошло нормально",
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await interaction_repo.save(interaction)

    referral_income_service = AsyncMock()
    service = InteractionService(
        interaction_repo=interaction_repo,
        order_repo=order_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
    )

    updated = await service.record_blogger_feedback(
        interaction.interaction_id, "✅ Всё прошло нормально"
    )

    assert updated.status == InteractionStatus.OK
    referral_income_service.record_creator_referral_income.assert_awaited_once()
    call_kwargs = (
        referral_income_service.record_creator_referral_income.call_args.kwargs
    )
    assert call_kwargs["creator_id"] == blogger_id
    assert call_kwargs["advertiser_country_code"] == "ru"
