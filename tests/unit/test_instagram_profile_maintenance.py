"""Daytime boundaries, safe retries and global Meta failure protection."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.application.errors import InstagramProfileUnavailableError
from ugc_bot.application.instagram_maintenance_ports import ProfileNotice
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
    ReceiptCard,
)
from ugc_bot.application.services.instagram_profile_maintenance import (
    InstagramProfileNoticeDelivery,
)
from ugc_bot.application.services.instagram_stats_update_service import (
    InstagramStatsUpdateService,
)
from ugc_bot.domain.instagram_maintenance import (
    MOSCOW,
    next_failure_count,
    next_profile_notice_at,
)


def at(hour, minute=0):
    return datetime(2026, 11, 19, hour, minute, tzinfo=MOSCOW)


@pytest.mark.parametrize(
    "hour,minute,day,next_hour",
    [
        (7, 59, 19, 8),
        (8, 0, 19, 8),
        (20, 59, 19, 20),
        (21, 0, 20, 8),
        (23, 59, 20, 8),
        (0, 0, 19, 8),
    ],
)
def test_moscow_window_includes_opening_excludes_closing(
    hour, minute, day, next_hour
):
    source = at(hour, minute).astimezone(timezone.utc)
    result = next_profile_notice_at(source).astimezone(MOSCOW)
    assert (result.day, result.hour) == (day, next_hour)
    if 8 <= hour < 21:
        assert result == source
    else:
        assert result.minute == 0


def test_naive_clock_rejected_and_failures_must_be_separated():
    with pytest.raises(ValueError, match="aware"):
        next_profile_notice_at(datetime(2026, 11, 19, 8))
    assert next_failure_count(0, None, at(8)) == 1
    assert next_failure_count(1, at(8), at(13, 59)) == 1
    assert next_failure_count(1, at(8), at(14)) == 2


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


def delivery(clock, *, failure=None):
    notice = ProfileNotice(
        uuid4(), uuid4(), "telegram", "123", "chat_id", "test", ReceiptCard()
    )
    repo = SimpleNamespace(
        claim=AsyncMock(side_effect=[notice, None]), finish=AsyncMock()
    )
    transport = SimpleNamespace(
        send=AsyncMock(
            return_value=DeliveryReceipt("telegram", "456"),
            side_effect=failure,
        )
    )
    worker = InstagramProfileNoticeDelivery(
        repo, Transactions(), transport, clock
    )
    return worker, repo, transport


@pytest.mark.asyncio
async def test_closed_window_never_even_claims_a_job():
    worker, repo, transport = delivery(SimpleNamespace(now=lambda: at(21)))
    assert await worker.run_once() == 0
    repo.claim.assert_not_called()
    transport.send.assert_not_called()


@pytest.mark.asyncio
async def test_window_checked_again_after_claim():
    times = iter([at(20, 59), at(21), at(21), at(21)])
    worker, repo, transport = delivery(SimpleNamespace(now=lambda: next(times)))
    assert await worker.run_once() == 0
    transport.send.assert_not_called()
    assert repo.finish.call_args.args[1] == "ready"
    assert repo.finish.call_args.kwargs["retry_at"] == at(8) + timedelta(days=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,state",
    [
        (None, "sent"),
        (DeliveryFailure("blocked", uncertain=False), "failed"),
        (DeliveryFailure("timeout", uncertain=True), "unknown"),
        (RuntimeError("connection_lost"), "unknown"),
        (
            DeliveryFailure("429", uncertain=False, retry_after_seconds=120),
            "ready",
        ),
    ],
)
async def test_receipts_uncertainty_and_daytime_retry(failure, state):
    worker, repo, transport = delivery(
        SimpleNamespace(now=lambda: at(20, 59)), failure=failure
    )
    assert await worker.run_once() == (1 if failure is None else 0)
    transport.send.assert_awaited_once()
    assert repo.finish.call_args.args[1] == state
    if state == "ready":
        assert repo.finish.call_args.kwargs["retry_at"] == at(8) + timedelta(
            days=1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("has_success", [False, True])
async def test_all_profile_failures_do_not_start_mass_owner_requests(
    has_success,
):
    bad = SimpleNamespace(instagram_user_id="bad", user_id=uuid4())
    good = SimpleNamespace(instagram_user_id="good", user_id=uuid4())
    repo = SimpleNamespace(
        list_confirmed_with_instagram_id=AsyncMock(
            return_value=[bad, good] if has_success else [bad]
        )
    )
    api = SimpleNamespace(
        get_profile_by_id=AsyncMock(
            side_effect=[
                InstagramProfileUnavailableError("100/33"),
                SimpleNamespace(username="good"),
            ]
        )
    )
    maintenance = SimpleNamespace(observe=AsyncMock(return_value=True))
    worker = InstagramStatsUpdateService(
        repo, api, delay_seconds=0, profile_maintenance=maintenance
    )
    assert await worker.run_once() == (int(has_success), 1)
    if has_success:
        assert maintenance.observe.await_count == 2
        assert maintenance.observe.call_args.kwargs["error"] == "100/33"
    else:
        maintenance.observe.assert_not_called()


@pytest.mark.asyncio
async def test_failed_observation_rolls_back_without_aborting_other_profiles(
    caplog,
):
    profiles = [
        SimpleNamespace(instagram_user_id=str(i), user_id=uuid4())
        for i in range(2)
    ]
    repo = SimpleNamespace(
        list_confirmed_with_instagram_id=AsyncMock(return_value=profiles),
        save=AsyncMock(),
    )
    api = SimpleNamespace(
        get_profile_by_id=AsyncMock(
            return_value=SimpleNamespace(username="available")
        )
    )
    maintenance = SimpleNamespace(
        observe=AsyncMock(
            side_effect=[
                RuntimeError("sensitive_internal_details"),
                True,
            ]
        )
    )
    worker = InstagramStatsUpdateService(
        repo, api, delay_seconds=0, profile_maintenance=maintenance
    )
    assert await worker.run_once() == (1, 1)
    assert api.get_profile_by_id.await_count == 2
    assert maintenance.observe.await_count == 2
    repo.save.assert_not_called()  # Do not fall back to a stale snapshot write.
    assert "Instagram observation rolled back" in caplog.text
    assert "sensitive_internal_details" not in caplog.text
