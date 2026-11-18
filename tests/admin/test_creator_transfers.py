"""The manual send requires an admin session and the existing CSRF token."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from ugc_bot.admin import creator_transfers as module
from ugc_bot.admin.app import (
    _admin_action_token,
    _build_templates,
    _require_action_token,
)
from ugc_bot.admin.order_creators import creator_workspace
from ugc_bot.config import AppConfig


def test_buttons_show_delivery_state_and_post_is_authorized(monkeypatch):
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="synthetic-secret")
    send = AsyncMock(return_value="sent")

    @asynccontextmanager
    async def context():
        yield object()

    monkeypatch.setattr(
        module, "Bot", lambda **kw: SimpleNamespace(context=context)
    )
    monkeypatch.setattr(
        module,
        "CreatorTransferService",
        lambda *args: SimpleNamespace(send=send),
    )

    async def authenticate(request):
        return request.cookies.get("authorized") == "yes"

    config = AppConfig()
    config.financial.core_enabled = True
    config.order.customer_workflows_enabled = True
    module.register_creator_transfers(
        app,
        SimpleNamespace(authenticate=authenticate),
        _require_action_token,
        config,
        object(),
    )
    templates = _build_templates(app, ZoneInfo("Europe/Moscow"))

    @app.get("/admin/users/{user_id}", name="admin_user_card")
    async def user_card(user_id: UUID):
        return {}

    @app.get("/admin/orders/{order_id}", name="admin_order_detail")
    async def order_card(request: Request, order_id: UUID):
        return {
            "csrf": _admin_action_token(request),
            "result": request.session.get("creator_transfer_result"),
        }

    @app.get("/preview/{order_id}")
    async def preview(request: Request, order_id: UUID):
        candidates = [
            dict(
                creator_id=uuid4(),
                name="<Автор>",
                source="Резерв",
                price=None,
                state=state,
            )
            for state in (None, "sent", "failed", "unknown")
        ]
        transfers = dict(
            count=15,
            needed=10,
            candidates=candidates,
            history=[],
            can_send=True,
        )
        return templates.TemplateResponse(
            request,
            "order_creators.html",
            dict(
                order_id=order_id,
                activity=None,
                workspace=creator_workspace([], transfers=transfers),
            ),
        )

    oid, cid = uuid4(), uuid4()
    path = f"/admin/orders/{oid}/creators/{cid}/send-to-customer"
    with TestClient(app) as client:
        assert client.post(path, follow_redirects=False).status_code == 307
        send.assert_not_awaited()
        client.cookies.set("authorized", "yes")
        token = client.get(f"/admin/orders/{oid}").json()["csrf"]
        assert client.post(path, follow_redirects=False).status_code == 403
        send.assert_not_awaited()
        html = client.get(f"/preview/{oid}").text
        assert 'data-transferred-count="15"' in html and "&lt;Автор&gt;" in html
        assert html.count("data-creator-transfer-form") == 2
        config.financial.core_enabled = False
        disabled = client.post(path, data={"csrf_token": token})
        assert disabled.status_code == 503
        send.assert_not_awaited()
        config.financial.core_enabled = True
        result = client.post(
            path, data={"csrf_token": token}, follow_redirects=False
        )
        assert result.status_code == 303
        send.assert_awaited_once_with(
            oid, cid, operator=f"admin:{config.admin.admin_username}"
        )
        message = client.get(result.headers["location"]).json()["result"]
        assert message == {
            "order_id": str(oid),
            "message": module.STATES["sent"],
        }
        send.side_effect = ValueError("transfer_creator_unavailable")
        rejected = client.post(path, data={"csrf_token": token})
        assert rejected.status_code == 200
        assert (
            rejected.json()["result"]["message"]
            == module.ERRORS["transfer_creator_unavailable"]
        )
