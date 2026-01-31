"""Tests for FsmDraftService."""

from uuid import uuid4

import pytest

from ugc_bot.application.services.fsm_draft_service import FsmDraftService
from ugc_bot.domain.entities import FsmDraft


class FakeDraftRepo:
    """Fake draft repo that records calls and returns configured draft."""

    def __init__(self, draft: FsmDraft | None = None) -> None:
        self.save_calls: list = []
        self.get_calls: list = []
        self.delete_calls: list = []
        self._draft = draft

    async def save(
        self, user_id, flow_type: str, state_key: str, data: dict, session=None
    ) -> None:
        self.save_calls.append((user_id, flow_type, state_key, data))

    async def get(self, user_id, flow_type: str, session=None) -> FsmDraft | None:
        self.get_calls.append((user_id, flow_type))
        return self._draft

    async def delete(self, user_id, flow_type: str, session=None) -> None:
        self.delete_calls.append((user_id, flow_type))


@pytest.mark.asyncio
async def test_fsm_draft_service_save_draft() -> None:
    """save_draft delegates to repo."""
    repo = FakeDraftRepo()
    service = FsmDraftService(draft_repo=repo, transaction_manager=None)
    user_id = uuid4()
    data = {"user_id": user_id, "nickname": "test"}

    await service.save_draft(
        user_id=user_id,
        flow_type="blogger_registration",
        state_key="BloggerRegistrationStates:name",
        data=data,
    )

    assert len(repo.save_calls) == 1
    assert repo.save_calls[0][0] == user_id
    assert repo.save_calls[0][1] == "blogger_registration"
    assert repo.save_calls[0][2] == "BloggerRegistrationStates:name"
    assert repo.save_calls[0][3]["nickname"] == "test"


@pytest.mark.asyncio
async def test_fsm_draft_service_get_draft_returns_none() -> None:
    """get_draft returns None when repo returns None."""
    repo = FakeDraftRepo()
    service = FsmDraftService(draft_repo=repo, transaction_manager=None)
    user_id = uuid4()

    result = await service.get_draft(user_id=user_id, flow_type="order_creation")

    assert result is None
    assert repo.get_calls == [(user_id, "order_creation")]


@pytest.mark.asyncio
async def test_fsm_draft_service_get_draft_returns_draft() -> None:
    """get_draft returns draft when repo has one."""
    from datetime import datetime, timezone

    user_id = uuid4()
    draft = FsmDraft(
        user_id=user_id,
        flow_type="order_creation",
        state_key="OrderCreationStates:price",
        data={"user_id": user_id, "product_link": "https://x.com"},
        updated_at=datetime.now(timezone.utc),
    )
    repo = FakeDraftRepo(draft=draft)
    service = FsmDraftService(draft_repo=repo, transaction_manager=None)

    result = await service.get_draft(user_id=user_id, flow_type="order_creation")

    assert result is not None
    assert result.state_key == "OrderCreationStates:price"
    assert result.data["product_link"] == "https://x.com"


@pytest.mark.asyncio
async def test_fsm_draft_service_delete_draft() -> None:
    """delete_draft delegates to repo."""
    repo = FakeDraftRepo()
    service = FsmDraftService(draft_repo=repo, transaction_manager=None)
    user_id = uuid4()

    await service.delete_draft(user_id=user_id, flow_type="edit_profile")

    assert len(repo.delete_calls) == 1
    assert repo.delete_calls[0] == (user_id, "edit_profile")
