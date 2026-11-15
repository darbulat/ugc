"""Order-scoped access to manual creator contacts for Telegram managers."""

import asyncio
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from ugc_bot.application.services.invite_handoff_notices import dispatch_invite
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import VISITS
from ugc_bot.infrastructure.db.models import OrderItemModel, UserModel
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    available_positions,
    create_invite,
    creator_availability,
    order_for_invite,
    team,
)


class InviteRequest(BaseModel):
    init_data: str
    item_id: UUID | None = None
    operation: Literal["lookup", "create", "send"] | None = None
    instagram: str = Field(default="", max_length=250)
    telegram: str = Field(default="", max_length=100)
    name: str = Field(default="", max_length=80)
    consent_source: str = Field(default="", max_length=30)


def manager_invite_data(engine, actor, order_id, body, bot):
    with Session(engine) as db, db.begin():
        order = order_for_invite(db, order_id)
        if (
            order is None
            or not db.execute(
                team(order).where(UserModel.user_id == actor)
            ).first()
        ):
            raise PermissionError
        link, identity = None, None
        availability = (
            creator_availability(db, body.instagram, body.telegram)
            if body.operation == "lookup"
            else None
        )
        if body.operation in {"create", "send"} or (
            body.operation is None and body.item_id is not None
        ):
            identity = create_invite(
                db,
                order_id,
                body.item_id,
                actor,
                body.instagram,
                datetime.now(timezone.utc),
                telegram=body.telegram,
                actor_id=actor,
                consent_source=body.consent_source,
                creator_name=body.name.strip(),
                direct=body.operation == "send",
            )
            link = f"https://t.me/{bot}?start=oi_{identity.hex}"
        positions = db.execute(
            available_positions(order_id, datetime.now(timezone.utc))
            .with_only_columns(
                OrderItemModel.paid_item_id,
                OrderItemModel.ordinal,
            )
            .order_by(OrderItemModel.ordinal)
        ).all()
        invites = (
            db.execute(
                select(
                    INVITES.c.id,
                    INVITES.c.instagram,
                    INVITES.c.telegram,
                    INVITES.c.reported_at,
                    INVITES.c.consented_at,
                    INVITES.c.expires_at,
                    exists()
                    .where(VISITS.c.invite_id == INVITES.c.id)
                    .label("opened"),
                    OrderItemModel.ordinal,
                )
                .join(
                    OrderItemModel,
                    OrderItemModel.paid_item_id == INVITES.c.item_id,
                )
                .where(
                    INVITES.c.order_id == order_id,
                    INVITES.c.manager_id == actor,
                )
                .order_by(INVITES.c.expires_at.desc())
                .limit(50)
            )
            .mappings()
            .all()
        )
        return {
            "positions": [
                {"id": row.paid_item_id, "ordinal": row.ordinal}
                for row in positions
            ],
            "link": link,
            "availability": availability,
            "identity": identity if body.operation == "send" else None,
            "invites": [dict(row) for row in invites],
        }


def register_manager_invites(router, authenticate):
    @router.post("/manager/orders/{order_id}/creator-invites")
    async def manager_invites(
        order_id: UUID,
        body: InviteRequest,
        request: Request,
        response: Response,
    ):
        response.headers["Cache-Control"] = "no-store"
        actor = await authenticate(request, body.init_data, platform="telegram")
        config = request.app.state.config
        bot = config.bot.bot_username.strip().lstrip("@")
        if (
            not config.db.database_url.startswith("postgresql")
            or not config.financial.core_enabled
            or not config.order.customer_workflows_enabled
            or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", bot)
        ):
            raise HTTPException(503, "Приглашения пока недоступны.")
        if body.consent_source not in {"", "instagram", "telegram", "other"}:
            raise HTTPException(422, "Укажите источник согласия.")
        container = request.app.state.dispatcher["container"]
        service = request.app.state.dispatcher.get("creator_invite_service")
        if body.operation == "send" and service is None:
            raise HTTPException(503, "Отправка в бот сейчас недоступна.")
        try:
            result = await asyncio.to_thread(
                manager_invite_data,
                container.get_admin_engine(),
                actor,
                order_id,
                body,
                bot,
            )
            if body.operation == "send" and (
                identity := result.pop("identity")
            ):
                result["notice_state"] = await dispatch_invite(
                    config, service, identity
                )
                if result["notice_state"] == "sent":
                    result["link"] = None
            return result
        except PermissionError as exc:
            raise HTTPException(403, "Заказ недоступен.") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
