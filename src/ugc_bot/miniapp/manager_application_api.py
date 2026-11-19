"""Native manager onboarding backed by the existing durable application."""

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field
from sqlalchemy.exc import IntegrityError

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.domain.manager_application import (
    FIELD_CHOICES,
    FIELDS,
    INTRO,
    MANAGER_FIELD_LABELS,
    WRITTEN_FIELDS,
    application_fields,
    missing_application_fields,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class ApplicationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except HTTPException as exc:
                response = JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code
                )
            except RequestValidationError:
                response = JSONResponse(
                    {"detail": "Проверьте данные анкеты."}, status_code=422
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


class ApplicationValue(SignedMiniAppRequest):
    value: str = Field(min_length=1, max_length=1800, strict=True)


class ApplicationAnswer(ApplicationValue):
    field: str = Field(min_length=1, max_length=40, strict=True)


async def _city(request, value):
    service = request.app.state.dispatcher.get("blogger_registration_service")
    if len(value) > FIELDS["location"][1] or not any(
        char.isalpha() for char in value
    ):
        raise HTTPException(422, "Введите название города.")
    location = await service.resolve_city_identity(value) if service else None
    if not location or not location[2]:
        raise HTTPException(
            422, "Город не найден. Уточните название и область."
        )
    return location


async def _view(request, service, row):
    answers = row["answers"]
    fields = application_fields(answers)
    missing = missing_application_fields(answers)
    target = request.app.state.config.instagram.admin_instagram_username
    target = (target or "").strip().lstrip("@")
    target = target if re.fullmatch(r"[A-Za-z0-9_.]{1,30}", target) else ""
    verified = row["instagram_verified_at"] is not None
    code = None
    if row["state"] == "submitted" and not verified and target:
        code = await service.instagram_challenge(row["user_id"])
    return {
        "state": row["state"],
        "intro": INTRO,
        "answers": answers,
        "next_field": missing[0] if missing else None,
        "fields": [
            {
                "name": field,
                "label": MANAGER_FIELD_LABELS[field],
                "prompt": FIELDS[field][0].replace(
                    "Поделитесь своим номером телефона для анкеты менеджера.",
                    "Укажите номер телефона в формате +79991234567.",
                ),
                "max_length": FIELDS[field][1],
                "min_length": 20 if field in WRITTEN_FIELDS else 1,
                "choices": FIELD_CHOICES.get(field, ()),
            }
            for field in fields
        ],
        "instagram_verified": verified,
        "instagram_code": code,
        "instagram_direct_url": f"https://ig.me/m/{target}" if target else None,
    }


async def _context(request, body, resolve_principal):
    if request.query_params:
        raise HTTPException(422, "Проверьте данные анкеты.")
    if body.platform != "telegram":
        raise HTTPException(403, "Анкета доступна в Telegram Mini App.")
    actor = await resolve_principal(
        request, body.init_data, platform=body.platform
    )
    if (
        not isinstance(actor, AuthenticatedMessengerPrincipal)
        or actor.platform != "telegram"
    ):
        raise HTTPException(401, "financial_session_invalid")
    service = request.app.state.dispatcher.get("manager_applications")
    if service is None:
        raise HTTPException(503, "Анкета временно недоступна.")
    return actor.user_id, service


def create_manager_application_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/manager/application", route_class=ApplicationRoute
    )

    @router.post("/view")
    async def view(request: Request, body: SignedMiniAppRequest):
        user_id, service = await _context(request, body, resolve_principal)
        return await _view(request, service, await service.open(user_id))

    @router.post("/city")
    async def city(request: Request, body: ApplicationValue):
        await _context(request, body, resolve_principal)
        city, region, country = await _city(request, body.value.strip())
        return {"city": city, "region": region, "country": country}

    @router.post("/answer")
    async def answer(request: Request, body: ApplicationAnswer):
        user_id, service = await _context(request, body, resolve_principal)
        row = await service.open(user_id)
        if body.field not in application_fields(row["answers"]):
            raise HTTPException(422, "Этот вопрос не относится к анкете.")
        value = body.value.strip()
        location_context = None
        if body.field == "location":
            value, region, country = await _city(request, value)
            location_context = (region, country)
        try:
            row = await service.answer(
                user_id, body.field, value, location_context=location_context
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        except IntegrityError as exc:
            diag = getattr(exc.orig, "diag", None)
            if (
                body.field == "instagram"
                and getattr(diag, "constraint_name", None)
                == "manager_applications_instagram_user_id_key"
            ):
                raise HTTPException(
                    422, "Этот Instagram уже привязан к другой анкете."
                ) from None
            raise
        return await _view(request, service, row)

    return router
