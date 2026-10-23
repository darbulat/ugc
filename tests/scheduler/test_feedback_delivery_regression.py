from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ugc_bot.config import FeedbackConfig
from ugc_bot.domain.entities import User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.feedback_scheduler import _send_feedback_requests_with_preloaded


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results,advanced", [([False, False], False), ([False, True], True)]
)
async def test_failed_send_does_not_advance_schedule(
    monkeypatch, results, advanced
):
    send = AsyncMock(side_effect=results)
    monkeypatch.setattr("ugc_bot.feedback_scheduler.send_with_retry", send)
    user = User(
        user_id=uuid4(),
        telegram_id="test",
        max_id="test-max",
        max_chat_id="test-max-chat",
        messenger_type=MessengerType.TELEGRAM,
        username="test",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    from types import SimpleNamespace

    interaction = SimpleNamespace(
        interaction_id=uuid4(),
        from_advertiser=None,
        from_blogger="✅ Всё прошло успешно",
        blogger_id=uuid4(),
    )
    service = AsyncMock()
    await _send_feedback_requests_with_preloaded(
        {"telegram": AsyncMock(), "max": AsyncMock()},
        interaction,
        service,
        AsyncMock(),
        blogger=None,
        advertiser=user,
        blogger_profile=None,
        order=None,
        feedback_config=FeedbackConfig(),
        locale="ru",
    )
    assert service.schedule_next_reminder.await_count == int(advanced)
