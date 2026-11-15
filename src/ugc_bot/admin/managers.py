"""Application review and registration of existing managers."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ugc_bot.admin.auth import admin_login_redirect
from ugc_bot.admin.people import telegram_handle
from ugc_bot.domain.manager_application import FIELDS
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    ManagerOrderModel,
    OrderModel,
    UserModel,
)


def _directory(db, query, status, offset):  # noqa: PLR0913
    member = exists().where(ManagerOrderModel.user_id == UserModel.user_id)
    running = (
        select(func.count())
        .select_from(ManagerOrderModel)
        .join(OrderModel, OrderModel.order_id == ManagerOrderModel.order_id)
        .where(
            ManagerOrderModel.user_id == UserModel.user_id,
            OrderModel.status == "active",
        )
        .correlate(UserModel)
        .scalar_subquery()
    )
    label = func.coalesce(APPLICATIONS.c.state, "existing")
    stmt = (
        select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            UserModel.status.label("account_status"),
            APPLICATIONS.c.registered_by_admin,
            label.label("state"),
            APPLICATIONS.c.answers,
            APPLICATIONS.c.instagram_verified_at,
            APPLICATIONS.c.decision_note,
            running.label("orders"),
        )
        .outerjoin(APPLICATIONS, APPLICATIONS.c.user_id == UserModel.user_id)
        .where(or_(member, APPLICATIONS.c.state != "draft"))
        .order_by(
            (label == "submitted").desc(),
            APPLICATIONS.c.updated_at.desc().nulls_last(),
            UserModel.user_id,
        )
    )
    if query:
        pattern = (
            "%"
            + query.removeprefix("@").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        stmt = stmt.where(
            or_(
                UserModel.username.ilike(pattern, escape="\\"),
                APPLICATIONS.c.answers["name"]
                .as_string()
                .ilike(pattern, escape="\\"),
                UserModel.telegram.ilike(pattern, escape="\\"),
                APPLICATIONS.c.answers["location"]
                .as_string()
                .ilike(pattern, escape="\\"),
                APPLICATIONS.c.answers["location_country"]
                .as_string()
                .ilike(pattern, escape="\\"),
            )
        )
    if status == "busy":
        stmt = stmt.where(running > 0)
    elif status == "available":
        stmt = stmt.where(
            running == 0,
            label.in_(("existing", "approved")),
            UserModel.status == "active",
        )
    elif status:
        stmt = stmt.where(label == status)
    return db.execute(stmt.offset(offset).limit(31)).mappings().all()


def _review(db, command, identity, note):
    now = datetime.now(timezone.utc)
    if command == "register":
        handle = telegram_handle(identity)
        if handle is None:
            raise ValueError("Укажите Telegram-ник.")
        users = db.scalars(
            select(UserModel.user_id)
            .where(
                func.lower(UserModel.telegram) == handle.lower(),
                UserModel.status == "active",
                UserModel.telegram_id.is_not(None),
            )
            .limit(2)
        ).all()
        if len(users) != 1:
            raise ValueError(
                "Нужен один активный Telegram-аккаунт, который уже открыл бота."
            )
        uid = users[0]
        created = db.scalar(
            insert(APPLICATIONS)
            .values(
                user_id=uid,
                state="approved",
                answers={},
                updated_at=now,
                reviewed_at=now,
                registered_by_admin=True,
            )
            .on_conflict_do_update(
                index_elements=[APPLICATIONS.c.user_id],
                where=APPLICATIONS.c.state == "draft",
                set_=dict(
                    state="approved",
                    updated_at=now,
                    reviewed_at=now,
                    registered_by_admin=True,
                    challenge=None,
                    challenge_until=None,
                ),
            )
            .returning(APPLICATIONS.c.user_id)
        )
        if created is None:
            raise ValueError(
                "Для этого аккаунта уже есть запись. Откройте её в списке."
            )
        state = "approved"
    else:
        uid = UUID(identity)
        row = (
            db.execute(
                select(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == uid)
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["state"] != "submitted":
            raise ValueError("Заявка уже обработана.")
        if command == "approved" and not row["instagram_verified_at"]:
            raise ValueError("Кандидату нужно подтвердить Instagram.")
        if command == "clarify" and not note:
            raise ValueError("Напишите, что нужно уточнить.")
        state = command
        db.execute(
            update(APPLICATIONS)
            .where(APPLICATIONS.c.user_id == uid)
            .values(
                state=state,
                reviewed_at=now,
                updated_at=now,
                decision_note=note or None,
            )
        )
    db.add(
        AuditLogModel(
            entity_type="manager_application",
            entity_id=uid,
            action="update",
            new_values={"state": state, "source": command},
            changed_at=now,
        )
    )
    return "Изменение сохранено."


def register_managers(  # noqa: C901
    app, auth, engine, templates, require_action_token
):
    def read(query, status, offset):
        with Session(engine) as db:
            return _directory(db, query, status, offset)

    def write(command, identity, note):
        with Session(engine) as db, db.begin():
            return _review(db, command, identity, note)

    @app.get("/admin/managers")
    async def managers(
        request: Request, q: str = "", status: str = "", page: int = 1
    ):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        if engine.dialect.name != "postgresql":
            raise HTTPException(503)
        page = max(1, min(page, 1000))
        rows = await asyncio.to_thread(
            read, q.strip()[:100], status, (page - 1) * 30
        )
        return templates.TemplateResponse(
            request,
            "managers.html",
            dict(
                rows=rows[:30],
                q=q,
                status=status,
                page=page,
                has_more=len(rows) > 30,
                fields=FIELDS,
                message=request.session.pop("managers_message", None),
            ),
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/admin/managers")
    async def manager_decision(request: Request):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        if engine.dialect.name != "postgresql":
            raise HTTPException(503)
        await require_action_token(request)
        form = await request.form()
        command = str(form.get("command", ""))
        if command not in {"register", "approved", "clarify", "declined"}:
            raise HTTPException(422)
        note = str(form.get("note", "")).strip()
        if len(note) > 300:
            raise HTTPException(422)
        try:
            message = await asyncio.to_thread(
                write, command, str(form.get("identity", "")), note
            )
        except ValueError as exc:
            message = str(exc)
        request.session["managers_message"] = message
        return RedirectResponse("/admin/managers", status_code=303)
