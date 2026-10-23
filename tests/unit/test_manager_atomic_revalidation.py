"""Reassignment after the HTTP read must not authorize any command writes."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from tests.unit.test_miniapp_manager_endpoints import (
    BLOGGER_ID,
    MANAGER_ID,
    ORDER_ID,
    _make_dispatch,
    _pair_request,
)
from ugc_bot.miniapp import api


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["video", "remove", "add", "feedback"])
async def test_reassignment_after_authorization_has_no_writes(operation):
    dispatch = replace(_make_dispatch(), in_offer=operation != "add")
    request, deps = _pair_request(dispatch)
    deps["manager_service"].assign_returning_creator = AsyncMock(
        return_value=dispatch
    )
    authorize = api._authorize_manager_creator

    async def reassign(*args, **kwargs):
        await authorize(*args, **kwargs)
        deps[
            "offer_dispatch_repo"
        ].get_by_order_and_blogger.return_value = replace(
            dispatch, manager_id=uuid4()
        )

    endpoint, body = {
        "video": (
            api.manager_set_ugc_video,
            api.UgcVideoRequest(init_data="x", url="https://example.com/v"),
        ),
        "remove": (api.manager_remove_creator, api.InitDataBody(init_data="x")),
        "add": (api.manager_add_creator, api.InitDataBody(init_data="x")),
        "feedback": (
            api.manager_feedback,
            api.ManagerFeedbackRequest(init_data="x", status="ok"),
        ),
    }[operation]
    with (
        patch.object(
            api, "_ensure_user_and_get_id", AsyncMock(return_value=MANAGER_ID)
        ),
        patch.object(api, "_authorize_manager_creator", reassign),
        pytest.raises(HTTPException) as exc,
    ):
        await endpoint(request, ORDER_ID, BLOGGER_ID, body)
    assert exc.value.status_code == 403
    for name in ("set_in_offer", "set_manager", "set_ugc_video_url"):
        getattr(deps["offer_dispatch_repo"], name).assert_not_awaited()
    for name in (
        "get_or_create",
        "reactivate_or_create_for_contacts_sent",
        "record_advertiser_feedback",
    ):
        getattr(deps["interaction_service"], name).assert_not_awaited()
    deps["messenger_client"].send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_optional_memory_transactions_do_not_duplicate_feedback_effects():
    from unittest.mock import MagicMock

    from ugc_bot.application.services.interaction_service import (
        InteractionService,
    )
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryInteractionRepository,
    )

    request, deps = _pair_request(_make_dispatch())
    deps["manager_service"].transaction_manager = None
    metrics = MagicMock()
    interactions = InteractionService(
        InMemoryInteractionRepository(), metrics_collector=metrics
    )
    deps["interaction_service"] = interactions
    order = deps["order_repo"].get_by_id.return_value
    interaction = await interactions.get_or_create(
        ORDER_ID, BLOGGER_ID, order.advertiser_id
    )
    await interactions.record_blogger_feedback(
        interaction.interaction_id, "✅ Сделка состоялась"
    )
    with patch.object(
        api, "_ensure_user_and_get_id", AsyncMock(return_value=MANAGER_ID)
    ):
        result = await api.manager_feedback(
            request,
            ORDER_ID,
            BLOGGER_ID,
            api.ManagerFeedbackRequest(init_data="x", status="no_deal"),
        )
    assert result["ok"]
    metrics.record_interaction_issue.assert_called_once()
