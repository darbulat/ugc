"""Tests for SupportService."""

import pytest

from ugc_bot.application.services.support_service import SupportService
from ugc_bot.infrastructure.memory_repositories import (
    InMemorySupportMessageRepository,
)


@pytest.fixture
def repo():
    return InMemorySupportMessageRepository()


@pytest.fixture
def service(repo):
    return SupportService(support_message_repo=repo)


@pytest.mark.asyncio
async def test_record_forwarded_message(service, repo):
    msg = await service.record_forwarded_message(
        user_chat_id="chat_100",
        support_chat_message_id=42,
        user_text="Help me!",
    )
    assert msg.user_chat_id == "chat_100"
    assert msg.support_chat_message_id == 42
    assert msg.user_text == "Help me!"
    assert 42 in repo.messages


@pytest.mark.asyncio
async def test_find_user_by_support_reply(service):
    await service.record_forwarded_message(
        user_chat_id="chat_200",
        support_chat_message_id=55,
        user_text="Question",
    )
    result = await service.find_user_by_support_reply(55)
    assert result == "chat_200"


@pytest.mark.asyncio
async def test_find_user_by_support_reply_not_found(service):
    result = await service.find_user_by_support_reply(999)
    assert result is None
