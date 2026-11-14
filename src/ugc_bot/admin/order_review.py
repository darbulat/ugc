"""Admin pages for reviewing paid positions and assigning their staff owner."""

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from starlette.requests import Request

from ugc_bot.admin.auth import admin_login_redirect
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.db.repositories.order_review import (
    list_positions,
    referral_entries,
    review_details,
    set_position_manager,
)

REASONS = {
    "no_answer": "Креатор не отвечает",
    "refused": "Креатор отказался",
    "not_done": "Работа не выполнена",
    "other": "Проблема по отметке заказчика",
    "delivery_unconfirmed": "Ответ креатора не удалось запросить",
    "replacement_reserve_empty": "В резерве нет подходящей замены",
    "replacement_reserve_limit_reached": "Лимит автоматических замен исчерпан",
    "replacement_requires_financial_review": "Нужна проверка условий замены",
}

MONEY_STATES = {
    "pending": "Ожидает основания",
    "hold": "На удержании",
    "available": "Доступно к выводу",
    "reserved": "В заявке на вывод",
    "paid": "Выплачено",
    "cancelled": "Отменено",
    "blocked": "Заблокировано",
    "debt": "Задолженность",
}


def _reason(row, at):
    if row["work_state"] == "disputed":
        return "Спор по работе"
    if row["report_state"] == "review":
        return REASONS.get(row["review_reason"], "Проверить отметку заказчика")
    if row["report_state"] in ("queued", "waiting"):
        return "Ждём ответа креатора"
    if row["contact_at"] is None:
        if row["creator_id"] is None:
            return "Нужно подобрать креатора"
        return "Нужно подтвердить передачу контакта"
    if row["work_due_at"] and row["work_due_at"] <= at:
        return "Истёк срок выполнения или подтверждения работы"
    return "Проверить доставку контакта"


def _load_review(engine, order_id, manager_id, unassigned, page, *, at):
    per_page = 50
    with Session(engine) as db:
        if db.get_bind().dialect.name != "postgresql":
            return [], False
        rows = list_positions(
            db,
            at,
            order_id,
            manager_id,
            unassigned,
            (page - 1) * per_page,
            per_page + 1,
        )
        groups = {}
        for row in rows[:per_page]:
            groups.setdefault(row["order_id"], []).append(
                dict(row, reason=_reason(row, at))
            )
        entries = defaultdict(list)
        for entry in referral_entries(
            db,
            [row["paid_item_id"] for rows in groups.values() for row in rows],
        ):
            entries[entry["paid_item_id"]].append(entry)
        orders = []
        for oid, positions in groups.items():
            options, used, cap, reserve = review_details(
                db, oid, positions[0]["advertiser_id"]
            )
            names = {
                mgr["user_id"]: (
                    mgr["username"] or mgr["telegram"] or str(mgr["user_id"])
                )
                for mgr in options
            }
            for row in positions:
                item_id = row["paid_item_id"]
                row.update(
                    manager=names.get(row["manager_id"], "Без ответственного"),
                    entries=entries[item_id],
                    overdue=row["deadline"] <= at and row["contact_at"] is None,
                )
            orders.append(
                dict(
                    id=oid,
                    number=public_order_number(oid),
                    title=positions[0]["offer_text"],
                    positions=positions,
                    managers=names,
                    used=used,
                    cap=cap,
                    reserve=reserve,
                    left=max(0, cap - used),
                )
            )
    return orders, len(rows) > per_page


def register_order_review(app, auth, engine, templates, require_action_token):
    @app.get("/admin/order-review", response_class=HTMLResponse)
    async def admin_order_review(
        request: Request,
        order_id: UUID | None = None,
        manager_id: UUID | None = None,
        unassigned: bool = False,
        page: int = 1,
    ):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        if not 1 <= page <= 1000:
            raise HTTPException(400, "Некорректная страница.")
        orders, has_more = await asyncio.to_thread(
            _load_review,
            engine,
            order_id,
            manager_id,
            unassigned,
            page,
            at=datetime.now(timezone.utc),
        )
        return templates.TemplateResponse(
            request,
            "order_review.html",
            {
                "orders": orders,
                "order_id": order_id,
                "manager_id": manager_id,
                "unassigned": unassigned,
                "page": page,
                "has_more": has_more,
                "message": request.session.pop("order_review_message", None),
                "money_states": MONEY_STATES,
            },
        )

    @app.post("/admin/order-review/{order_id}/{item_id}/assign")
    async def assign_review_manager(
        request: Request, order_id: UUID, item_id: UUID
    ):
        if not await auth.authenticate(request):
            raise HTTPException(403, "Требуется вход в админку.")
        await require_action_token(request)
        form = await request.form()
        try:
            manager = (
                UUID(str(form["manager_id"]))
                if form.get("manager_id")
                else None
            )
            expected = (
                UUID(str(form["expected"])) if form.get("expected") else None
            )
        except ValueError as exc:
            raise HTTPException(400, "Некорректное назначение.") from exc

        def assign():
            with Session(engine) as db, db.begin():
                return set_position_manager(
                    db,
                    order_id,
                    item_id,
                    manager,
                    expected,
                    datetime.now(timezone.utc),
                )

        request.session["order_review_message"] = await asyncio.to_thread(
            assign
        )
        url = request.url_for("admin_order_review").include_query_params(
            order_id=order_id
        )
        return RedirectResponse(url, status_code=303)
