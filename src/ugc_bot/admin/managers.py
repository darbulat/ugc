"""Application review and registration of existing managers."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import RedirectResponse

from ugc_bot.admin.auth import admin_login_redirect
from ugc_bot.admin.people import telegram_handle
from ugc_bot.domain.manager_application import (
    MANAGER_FIELD_LABELS,
    MANAGER_STATES,
    application_version,
)
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    ManagerOrderModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.manager_applications import (
    record_manager_review,
    review_manager_application,
)


def _manager_rows():
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
    return (
        select(
            UserModel.user_id,
            UserModel.username,
            UserModel.telegram,
            UserModel.status.label("account_status"),
            APPLICATIONS.c.registered_by_admin,
            label.label("state"),
            APPLICATIONS.c.answers,
            APPLICATIONS.c.submitted_at,
            APPLICATIONS.c.reviewed_at,
            APPLICATIONS.c.instagram_verified_at,
            APPLICATIONS.c.decision_note,
            running.label("orders"),
        )
        .outerjoin(APPLICATIONS, APPLICATIONS.c.user_id == UserModel.user_id)
        .where(or_(member, APPLICATIONS.c.state != "draft"))
    )


def _directory(db, query, status, offset):
    stmt = _manager_rows()
    label = stmt.selected_columns.state
    running = stmt.selected_columns.orders
    stmt = stmt.order_by(
        (label == "submitted").desc(),
        APPLICATIONS.c.updated_at.desc().nulls_last(),
        UserModel.user_id,
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


def _review(db, command, identity, note, *, version=None):
    if command != "register":
        review_manager_application(
            db, UUID(identity), command, note, version=version
        )
        return "Изменение сохранено."
    now = datetime.now(timezone.utc)
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
    record_manager_review(db, uid, "approved", command, now)
    return "Менеджер добавлен. Уведомление поставлено в очередь."


def register_managers(  # noqa: C901
    app, auth, engine, templates, require_action_token
):
    def read(query, status, offset):
        with Session(engine) as db:
            return _directory(db, query, status, offset)

    def read_detail(user_id):
        with Session(engine) as db:
            return (
                db.execute(_manager_rows().where(UserModel.user_id == user_id))
                .mappings()
                .one_or_none()
            )

    def write(command, identity, note, version):
        with Session(engine) as db, db.begin():
            if version is None:
                return _review(db, command, identity, note)
            return _review(db, command, identity, note, version=version)

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
                states=MANAGER_STATES,
                message=request.session.pop("managers_message", None),
            ),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/admin/managers/{user_id}")
    async def manager_card(request: Request, user_id: UUID):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        if engine.dialect.name != "postgresql":
            raise HTTPException(503)
        row = await asyncio.to_thread(read_detail, user_id)
        if row is None:
            raise HTTPException(404)
        return templates.TemplateResponse(
            request,
            "manager_card.html",
            dict(
                row=row,
                states=MANAGER_STATES,
                labels=MANAGER_FIELD_LABELS,
                version=application_version(row["submitted_at"]),
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
        if command not in {
            "register",
            "approved",
            "clarify",
            "declined",
            "note",
        }:
            raise HTTPException(422)
        note = str(form.get("note", "")).strip()
        if len(note) > 300:
            raise HTTPException(422)
        identity = str(form.get("identity", ""))
        target = "/admin/managers"
        version_text = str(form.get("version", ""))
        if version_text and (
            not version_text.isdecimal() or len(version_text) > 20
        ):
            raise HTTPException(422)
        try:
            if form.get("from_detail") == "1" and command != "register":
                target += f"/{UUID(identity)}"
            message = await asyncio.to_thread(
                write,
                command,
                identity,
                note,
                int(version_text) if version_text else None,
            )
            if command == "approved":
                message = "Менеджер принят. Уведомление поставлено в очередь."
        except ValueError as exc:
            message = str(exc)
        request.session["managers_message"] = message
        return RedirectResponse(target, status_code=303)
