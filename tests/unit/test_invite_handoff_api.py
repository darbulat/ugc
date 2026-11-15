"""Mini App contact actions use private, order-scoped replies."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ugc_bot.miniapp.invite_handoff_api import create_invite_handoff_router


def test_contact_cannot_be_opened_or_acknowledged_from_another_order():
    order, invitation = uuid4(), uuid4()
    service = SimpleNamespace(
        reported_contact=AsyncMock(return_value=order),
        reported_contact_text=AsyncMock(return_value="@private_creator"),
        acknowledge_staff_contact=AsyncMock(),
        client_sharing=AsyncMock(return_value={"enabled": True}),
    )
    principal = object()

    async def resolve(request, init_data, *, platform):
        if init_data != "owner":
            raise HTTPException(401, "financial_session_invalid")
        assert platform == "telegram"
        return principal

    app = FastAPI()
    app.state.dispatcher = {"creator_invite_service": service}
    app.state.config = SimpleNamespace(bot=SimpleNamespace(bot_username="bot"))
    app.include_router(create_invite_handoff_router(resolve))
    with TestClient(app) as client:

        def invoke(action, order_id=order, actor="owner", **options):
            response = client.post(
                f"/financial/orders/{order_id}/invite-handoff",
                json={"init_data": actor, "action": action, **options},
            )
            assert response.headers["cache-control"] == "no-store"
            return response

        selector = {"invitation": str(invitation)}
        assert invoke("open", actor="wrong", **selector).status_code == 401
        assert invoke("open", uuid4(), **selector).status_code == 404
        assert invoke("ack", uuid4(), **selector).status_code == 404
        assert invoke("open", platform="max", **selector).status_code == 404
        assert invoke("ack").status_code == 422
        service.reported_contact_text.assert_not_awaited()
        service.acknowledge_staff_contact.assert_not_awaited()
        assert invoke("open", **selector).json() == {
            "contact": "@private_creator"
        }
        assert invoke("ack", **selector).json() == {"acknowledged": True}
        assert invoke("share").json() == {
            "enabled": True,
            "open_url": f"https://t.me/bot?start=ir_{order.hex}",
        }
        service.acknowledge_staff_contact.assert_awaited_once_with(
            principal, invitation
        )
        service.client_sharing.assert_awaited_once_with(principal, order, True)
