"""Private, read-only queue for a manager assigned to the order."""

import asyncio
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ugc_bot.infrastructure.db.repositories.order_position_queue import (
    STAGES,
    is_order_manager,
    queue_rows,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class QueueRequest(SignedMiniAppRequest):
    stage: Literal["all", "waiting", "manual", "received"] = "all"


def _read(engine, order_id, actor, stage):
    with Session(engine) as db:
        if db.get_bind().dialect.name != "postgresql":
            raise LookupError
        if not is_order_manager(db, actor, order_id):
            raise PermissionError
        rows = queue_rows(
            db, datetime.now(timezone.utc), order_id, stage=stage, limit=200
        )
        return [
            {
                "ordinal": row["ordinal"],
                "stage": row["stage"],
                "label": STAGES[row["stage"]],
                "needs_review": row["needs_review"],
                "preview": row["preview"],
            }
            for row in rows
        ]


def create_manager_position_queue_router(resolve):
    router = APIRouter()
    headers = {"Cache-Control": "no-store"}

    @router.post("/manager/orders/{order_id}/position-queue")
    async def manager_position_queue(
        request: Request, response: Response, order_id: UUID, body: QueueRequest
    ):
        response.headers.update(headers)
        if body.platform != "telegram":
            raise HTTPException(404, headers=headers)
        principal = await resolve(request, body.init_data, platform="telegram")
        container = request.app.state.dispatcher["container"]
        try:
            rows = await asyncio.to_thread(
                _read,
                container.get_admin_engine(),
                order_id,
                principal.user_id,
                body.stage,
            )
        except PermissionError:
            raise HTTPException(
                404, "Заказ недоступен.", headers=headers
            ) from None
        except LookupError:
            raise HTTPException(
                503, "Очередь недоступна.", headers=headers
            ) from None
        return {"positions": rows}

    return router
