"""Unsafe feedback must fail closed before the other party replies."""

from uuid import uuid4

import pytest

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.enums import InteractionStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_party", ["advertiser", "blogger"])
async def test_conflicting_feedback_opens_issue(first_party: str) -> None:
    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(uuid4(), uuid4(), uuid4())
    first = getattr(service, f"record_{first_party}_feedback")
    other_party = "blogger" if first_party == "advertiser" else "advertiser"
    second = getattr(service, f"record_{other_party}_feedback")
    await first(interaction.interaction_id, "✅ Сделка состоялась")
    updated = await second(interaction.interaction_id, "❌ Не договорились")
    assert updated.status == InteractionStatus.ISSUE
    assert updated.next_check_at is None
    stored = await repo.get_by_id(interaction.interaction_id)
    assert stored is not None
    assert stored.status == InteractionStatus.ISSUE


@pytest.mark.asyncio
@pytest.mark.parametrize("party", ["advertiser", "blogger"])
async def test_issue_is_immediate_without_other_party(party: str) -> None:
    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(uuid4(), uuid4(), uuid4())
    record = getattr(service, f"record_{party}_feedback")
    updated = await record(interaction.interaction_id, "⚠️ Проблема")
    assert updated.status == InteractionStatus.ISSUE
    assert updated.next_check_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply", ["✅ Сделка состоялась", "⏳ Еще не связался"]
)
async def test_feedback_cannot_self_resolve_existing_issue(reply: str) -> None:
    repo = InMemoryInteractionRepository()
    service = InteractionService(interaction_repo=repo)
    interaction = await service.get_or_create(uuid4(), uuid4(), uuid4())
    await service.record_advertiser_feedback(
        interaction.interaction_id, "⚠️ Проблема"
    )
    await service.record_blogger_feedback(
        interaction.interaction_id, "✅ Сделка состоялась"
    )
    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, reply
    )
    assert updated.status == InteractionStatus.ISSUE
    assert updated.next_check_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting_party", ["advertiser", "blogger"])
async def test_postponed_reply_is_not_a_final_success(waiting_party):
    from unittest.mock import AsyncMock

    repo = InMemoryInteractionRepository()
    from types import SimpleNamespace

    from ugc_bot.domain.enums import OrderStatus

    recorder, orders, users = AsyncMock(), AsyncMock(), AsyncMock()
    orders.get_by_id.return_value = SimpleNamespace(
        status=OrderStatus.CLOSED, advertiser_id=uuid4()
    )
    users.get_by_id.return_value = SimpleNamespace(country="ru")
    service = InteractionService(
        repo,
        order_repo=orders,
        user_repo=users,
        referral_income_service=recorder,
    )
    interaction = await service.get_or_create(uuid4(), uuid4(), uuid4())
    waiting = getattr(service, f"record_{waiting_party}_feedback")
    other = "blogger" if waiting_party == "advertiser" else "advertiser"
    success = getattr(service, f"record_{other}_feedback")
    await waiting(interaction.interaction_id, "⏳ Ещё не связался")
    updated = await success(interaction.interaction_id, "✅ Всё прошло успешно")
    assert updated.status == InteractionStatus.PENDING
    assert updated.next_check_at is not None
    recorder.record_creator_referral_income.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["cancel", "reactivate", "schedule"])
async def test_ordinary_lifecycle_cannot_erase_or_reschedule_issue(operation):
    from datetime import datetime, timedelta, timezone

    repo = InMemoryInteractionRepository()
    service = InteractionService(repo)
    interaction = await service.get_or_create(uuid4(), uuid4(), uuid4())
    disputed = await service.record_advertiser_feedback(
        interaction.interaction_id, "⚠️ Проблема"
    )
    if operation == "cancel":
        await service.cancel_interaction(
            interaction.order_id,
            interaction.blogger_id,
            interaction.advertiser_id,
        )
    elif operation == "reactivate":
        await service.reactivate_or_create_for_contacts_sent(
            interaction.order_id,
            interaction.blogger_id,
            interaction.advertiser_id,
        )
    else:
        await service.schedule_next_reminder(
            interaction.interaction_id,
            datetime.now(timezone.utc) + timedelta(days=1),
        )
    stored = await repo.get_by_id(interaction.interaction_id)
    assert stored.status == InteractionStatus.ISSUE
    assert stored.from_advertiser == disputed.from_advertiser
    assert stored.next_check_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "клиент написал ✅",
        "ещё не связался ⏳",
        "сделка состоялась?",
        "мошенничество обсуждалось",
    ],
)
async def test_no_deal_reason_cannot_override_canonical_outcome(reason):
    from ugc_bot.application.feedback_utils import needs_feedback_reminder

    repo = InMemoryInteractionRepository()
    service = InteractionService(repo)
    interaction = await service.get_or_create(uuid4(), uuid4(), uuid4())
    await service.record_blogger_feedback(
        interaction.interaction_id, "✅ Всё хорошо"
    )
    feedback = f"❌ Не договорились: {reason}"
    assert service._parse_feedback(feedback) == InteractionStatus.NO_DEAL
    assert needs_feedback_reminder(feedback) is False
    updated = await service.record_advertiser_feedback(
        interaction.interaction_id, feedback
    )
    assert updated.status == InteractionStatus.ISSUE
