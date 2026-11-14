"""SQLAdmin application setup."""

import asyncio
import dataclasses
import logging
from collections.abc import Sequence
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from pathlib import Path
from secrets import compare_digest, token_urlsafe
from typing import Any, Optional, TypeVar, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile
from fastapi import Depends, FastAPI, HTTPException
from sqladmin import Admin, BaseView, ModelView, action, expose
from sqladmin.authentication import login_required
from sqlalchemy import exists, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from starlette.datastructures import URL
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates
from wtforms import SelectField  # type: ignore[import-untyped]

from ugc_bot.admin.auth import (
    AdminAuth,
    admin_login_redirect,
    safe_admin_return_to,
)
from ugc_bot.admin.complaints import (
    COMPLAINT_STATUS_LABELS,
    OPEN_COMPLAINT_STATUSES,
    complaint_context,
    dismiss_open_complaint,
    search_complaints,
)
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
    PeriodKey,
    dashboard_period_window,
    paid_in_period,
)
from ugc_bot.admin.order_editor import (
    ORDER_EDITOR_HINTS,
    ORDER_EDITOR_LIMITS,
    ORDER_EDITOR_SECTIONS,
    changed_text_errors,
)
from ugc_bot.admin.order_worklist import (
    ORDER_STATUS_LABELS,
    UNPAID_GROUP,
    aging_unpaid_condition,
    change_order_worklist,
    search_orders,
    worklist_conditions,
    worklist_row_details,
)
from ugc_bot.admin.people import instagram_link, telegram_handle
from ugc_bot.application.errors import OrderGeographyUnavailableError
from ugc_bot.application.geography import (
    get_geometry_queries_from_spec,
    parse_geography,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.geocoder import (
    wkt_multipoint_from_lat_lon,
)
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.outbox_publisher import OutboxPublisher
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.domain.enums import (
    AuditAction,
    ComplaintStatus,
    InteractionStatus,
    OrderStatus,
    PaymentStatus,
    PayoutRequestStatus,
    RaterRole,
    UserStatus,
)
from ugc_bot.infrastructure.db.checkout_models import AUTHORIZATIONS, INBOX
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerProfileModel,
    BloggerRatingModel,
    BotTextModel,
    ComplaintModel,
    ContactPricingModel,
    CountryModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    LanguageModel,
    NpsResponseModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    PayoutRequestModel,
    ReferralIncomeEntryModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.unpaid_reminders import (
    reminder_statuses,
)
from ugc_bot.infrastructure.redis_cache import (
    AdminCache,
    deserialize_admin_payload,
    serialize_admin_payload,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


_admin_container: Container | None = None


def _get_admin_container() -> Container | None:
    """Return container set at app creation."""
    return _admin_container


def _get_services(
    container: Container,
) -> tuple[UserRoleService, ComplaintService, InteractionService]:
    """Get services for admin actions."""
    return container.build_admin_services()


def _get_order_moderation_deps(
    container: Container,
) -> tuple[ContentModerationService, OutboxPublisher, OrderRepository]:
    """Get ContentModerationService, OutboxPublisher, OrderRepository."""
    content_moderation = ContentModerationService()
    outbox_publisher = container.build_outbox_publisher()
    order_repo = container.build_repos()["order_repo"]
    return (content_moderation, outbox_publisher, order_repo)


async def _update_order_location_geometry_after_geography_change(
    order_id: UUID, geography_raw: Any
) -> None:
    """Resolve location_geometry from new geography and save order.

    When admin updates order geography, we need to recompute location_geometry
    via geocoder so that offer dispatch uses the correct geometry filter.
    """
    container = _get_admin_container()
    if not container:
        return
    geography_clean = (geography_raw or "").strip() or None
    new_geometry: str | None = None
    if geography_clean:
        geocoder = container.build_geocoder()
        spec = parse_geography(geography_clean)
        if spec is not None:
            queries = get_geometry_queries_from_spec(spec)
            if queries:
                new_geometry = await geocoder.get_multipolygon_wkt_for_queries(
                    queries
                )
    _, _, order_repo = _get_order_moderation_deps(container)
    tm = container.transaction_manager
    if not tm:
        return
    try:
        async with tm.transaction() as session:
            order = await order_repo.get_by_id_for_update(
                order_id, session=session
            )
            if order is None:
                return
            if (order.geography or "").strip() != (geography_raw or "").strip():
                return
            updated = dataclasses.replace(order, location_geometry=new_geometry)
            await order_repo.save(updated, session=session)
        logger.info(
            "Updated order location_geometry after geography change in admin",
            extra={"order_id": str(order_id)},
        )
    except Exception:
        logger.exception(
            "Failed to update order location_geometry after geography change",
            extra={"order_id": str(order_id)},
        )


async def _publish_order_activation(order_id: UUID) -> None:
    """Publish order activation event via outbox."""
    try:
        container = _get_admin_container()
        if not container:
            return
        _, outbox_publisher, order_repo = _get_order_moderation_deps(container)
        tm = container.transaction_manager
        if tm:
            async with tm.transaction() as session:
                order = await order_repo.get_by_id(order_id, session=session)
                if order:
                    await outbox_publisher.publish_order_activation(
                        order, session=session
                    )
    except Exception:
        logger.exception(
            "Failed to publish order activation after admin approval",
            extra={"order_id": str(order_id)},
        )


async def _resolve_order_location_geometry(geography_raw: Any) -> str | None:
    """Resolve edited geography before locking the order for activation."""
    spec = parse_geography((geography_raw or "").strip() or None)
    queries = get_geometry_queries_from_spec(spec) if spec else []
    if not queries:
        return None
    container = _get_admin_container()
    if container is None:
        raise ValueError("order_geography_update_failed")
    geometry = (
        await container.build_geocoder().get_multipolygon_wkt_for_queries(
            queries
        )
    )
    if not geometry:
        raise ValueError("order_geography_update_failed")
    return geometry


async def _checked_activation_geography(
    order, container, geography_update, exact_city, session
):
    if geography_update is None:
        return order
    geography, geometry = geography_update
    if (order.geography or "").strip() != (geography or "").strip():
        raise ValueError("order_geography_changed")
    if order.financial_version is not None:
        intake = container.build_repos().get("order_intake_repo")
        if intake is None:
            raise ValueError("order_geography_update_failed")
        stored_city = await intake.exact_city_for_order(
            order.order_id, session=session, for_update=True
        )
        if stored_city != exact_city or (
            stored_city is not None
            and stored_city != (order.geography or "").strip()
        ):
            raise ValueError("order_geography_changed")
    return dataclasses.replace(order, location_geometry=geometry)


_ACTIVATABLE_ORDER_STATUSES = frozenset(
    (OrderStatus.NEW, OrderStatus.PENDING_MODERATION)
)


async def _guard_complimentary_activation(order, payment, session) -> None:
    """A provider authorization can still turn into a real charge."""
    if (
        order.financial_version is None
        and payment is not None
        and payment.status == PaymentStatus.PENDING
    ):
        raise ValueError("Оплата уже обрабатывается. Дождитесь её результата.")
    payment_in_flight = await session.scalar(
        select(
            exists().where(AUTHORIZATIONS.c.order_id == order.order_id)
            | exists().where(INBOX.c.order_id == order.order_id)
        )
    )
    if payment_in_flight:
        raise ValueError("Оплата уже обрабатывается. Дождитесь её результата.")


async def _activate_order(
    order_id: UUID,
    *,
    geography_update: tuple[str | None, str | None] | None = None,
    exact_city: str | None = None,
) -> None:
    """Save administrative approval and queue the offers atomically."""
    container = _get_admin_container()
    if container is None or container.transaction_manager is None:
        raise ValueError("order_activation_unavailable")
    content_moderation, outbox, orders = _get_order_moderation_deps(container)
    payments = container.build_repos().get("payment_repo")
    if payments is None:
        raise ValueError("order_payment_unavailable")
    async with container.transaction_manager.transaction() as session:
        order = await orders.get_by_id_for_update(order_id, session=session)
        if order is None:
            raise ValueError("order_not_found")
        if order.status == OrderStatus.ACTIVE:
            return
        if order.status not in _ACTIVATABLE_ORDER_STATUSES:
            raise ValueError("order_activation_requires_new_or_pending")
        order = await _checked_activation_geography(
            order, container, geography_update, exact_city, session
        )
        payment = await payments.get_by_order(order_id, session=session)
        complimentary = payment is None or payment.status != PaymentStatus.PAID
        if complimentary:
            await _guard_complimentary_activation(order, payment, session)
        if content_moderation.order_contains_banned_content(
            product_link=order.product_link,
            offer_text=order.offer_text,
            barter_description=order.barter_description,
            content_usage=order.content_usage,
            geography=order.geography,
        ):
            raise ValueError("Запрещённый контент. Отредактируйте заявку.")
        activated = dataclasses.replace(
            order,
            status=OrderStatus.ACTIVE,
            complimentary=complimentary,
            dispatch_stopped=False,
        )
        await orders.save(activated, session=session)
        await outbox.publish_order_activation(activated, session=session)
        if complimentary:
            session.add(
                AuditLogModel(
                    entity_type="order",
                    entity_id=order_id,
                    action=AuditAction.UPDATE,
                    old_values={"status": order.status.value},
                    new_values={
                        "status": OrderStatus.ACTIVE.value,
                        "complimentary": True,
                    },
                )
            )


async def _finish_order_geography_and_activation(
    order_id: UUID,
    data: dict,
    *,
    activating: bool,
    saved_geography: str | None,
    financial_version: str | None = None,
    exact_city: str | None = None,
) -> None:
    if activating:
        geography = data.get("geography", saved_geography)
        if financial_version is not None:
            container = _get_admin_container()
            if container is None or container.transaction_manager is None:
                raise ValueError("order_activation_unavailable")
            intake = container.build_repos().get("order_intake_repo")
            if intake is None:
                raise ValueError("order_geography_update_failed")
            async with container.transaction_manager.transaction() as session:
                exact_city = await intake.exact_city_for_order(
                    order_id, session=session
                )
        geometry = (
            None
            if exact_city
            else await _resolve_order_location_geometry(geography)
        )
        kwargs = (
            {"exact_city": exact_city} if financial_version is not None else {}
        )
        await _activate_order(
            order_id, geography_update=(geography, geometry), **kwargs
        )
    elif "geography" in data:
        if (data.get("geography") or "").strip() == (
            saved_geography or ""
        ).strip():
            return
        if exact_city is not None:
            return
        await _update_order_location_geometry_after_geography_change(
            order_id, data.get("geography")
        )


async def _validate_paid_order_geography_edit(
    order, geography_raw: Any
) -> str | None:
    """Keep exact-city targeting receipts in sync with editable order data."""
    changed = order is not None and (
        (order.geography or "").strip() != (geography_raw or "").strip()
    )
    if order is None or order.financial_version is None or not changed:
        return None
    container = _get_admin_container()
    if container is None or container.transaction_manager is None:
        raise ValueError("order_geography_update_failed")
    intake = container.build_repos().get("order_intake_repo")
    if intake is None:
        raise ValueError("order_geography_update_failed")
    async with container.transaction_manager.transaction() as session:
        exact_city = await intake.exact_city_for_order(
            order.order_id, session=session, for_update=True
        )
    if exact_city is not None and (geography_raw or "").strip() != exact_city:
        raise ValueError(
            "Нельзя изменить город оплаченного заказа с точным подбором. "
            "Создайте новый заказ для другого города."
        )
    return exact_city


async def _update_order_managers(order_id: UUID, managers_raw: str) -> None:
    """Parse managers field and update manager-order assignments.

    An empty string removes all manager assignments for the order.
    """
    container = _get_admin_container()
    if not container:
        return
    manager_service = container.build_manager_service()
    usernames = [
        u.strip().lstrip("@") for u in managers_raw.split(",") if u.strip()
    ]
    await manager_service.set_managers_for_order(order_id, usernames)


async def _update_blogger_profile_location_from_nominatim(
    user_id: UUID, city: Optional[str] = None
) -> None:
    """Update blogger profile location_geometry, region, country via geocoder.

    When admin updates blogger profile city, we geocode and save coordinates,
    region and country to the profile.
    """
    container = _get_admin_container()
    if not container:
        return
    repos = container.build_repos()
    blogger_repo = repos.get("blogger_repo")
    tm = container.transaction_manager
    if not blogger_repo or not tm:
        return
    try:
        async with tm.transaction() as session:
            profile = await blogger_repo.get_by_user_id(
                user_id, session=session
            )
            if profile is None:
                return
            city_for_query = (city or "").strip() or (
                profile.city or ""
            ).strip()
            if not city_for_query:
                return
            geocoder = container.build_geocoder()
            details = await geocoder.geocode_with_details(
                city_for_query,
                region=profile.region,
                country=profile.country or None,
            )
            if details is None:
                return
            lat, lon, _, _, region_nom, country_nom = details
            new_geometry = wkt_multipoint_from_lat_lon(lat, lon)
            new_region = (
                region_nom if region_nom is not None else profile.region
            )
            new_country = (
                country_nom
                if country_nom is not None
                else (profile.country or "")
            )
            updated = dataclasses.replace(
                profile,
                location_geometry=new_geometry,
                region=new_region,
                country=new_country,
            )
            await blogger_repo.save(updated, session=session)
        logger.info(
            "Updated blogger profile location from Nominatim after city change",
            extra={"user_id": str(user_id)},
        )
    except Exception:
        logger.exception(
            "Failed to update blogger profile location from Nominatim",
            extra={"user_id": str(user_id)},
        )


T = TypeVar("T")
_DASHBOARD_PERIODS = ("today", "yesterday", "7d", "30d", "all")
_PERIOD_LABELS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "7d": "7 дней",
    "30d": "30 дней",
    "all": "Все",
}
_STATUS_LABELS = {
    "active": "Активен",
    "completed": "Завершён",
    "archive": "Архив",
    "complaint": "Жалоба",
}
_USER_STATUS_LABELS = {
    "active": "Активен",
    "limited": "Ограничен",
}
_DELAY_REASON_LABELS = {
    "active_overdue": "Долгий подбор",
    "no_responses": "Нет откликов",
    "low_picked": "Мало подобрано",
    "dispatch_paused": "Рассылка на паузе",
    "waiting_moderation": "Ожидает модерации",
    "waiting_payment": "Ожидает оплаты",
}

_ORDER_LIST_PATH = "/admin/order-model/list"
_COMPLAINT_LIST_PATH = "/admin/complaint-model/list"
_ORDER_RETURN_PATHS = {
    _ORDER_LIST_PATH,
    _COMPLAINT_LIST_PATH,
    "/admin/orders",
    "/admin/dashboard",
}


def _admin_action_token(request: Request) -> str:
    if "order_worklist_csrf" not in request.session:
        request.session["order_worklist_csrf"] = token_urlsafe()
    return request.session["order_worklist_csrf"]


async def _require_action_token(request: Request) -> None:
    submitted = (await request.form()).get("csrf_token")
    expected = request.session.get("order_worklist_csrf", "")
    if (
        not expected
        or not isinstance(submitted, str)
        or not compare_digest(expected.encode(), submitted.encode())
    ):
        raise HTTPException(status_code=403, detail="Обновите страницу.")


def _complaint_return_url(request: Request) -> str:
    target = safe_admin_return_to(request.query_params.get("return_to"))
    if target and URL(target).path == _COMPLAINT_LIST_PATH:
        return target
    return _COMPLAINT_LIST_PATH


def _order_return_url(request: Request) -> str:
    target = safe_admin_return_to(request.query_params.get("return_to"))
    if target and URL(target).path in _ORDER_RETURN_PATHS:
        return target
    return _ORDER_LIST_PATH


def _customer_order_url(request: Request) -> URL | None:
    order_id = request.query_params.get("from_order")
    if not order_id:
        return None
    try:
        return request.url_for(
            "admin_order_detail", order_id=UUID(order_id)
        ).include_query_params(return_to=_order_return_url(request))
    except ValueError:
        return None


def _normalize_period(period: str) -> PeriodKey:
    """Return supported dashboard period."""
    normalized = period if period in _DASHBOARD_PERIODS else "today"
    return cast(PeriodKey, normalized)


def _build_dashboard_service(
    config: AppConfig, container: Container
) -> AdminDashboardService:
    """Build AdminDashboardService from config and container."""
    thresholds = DelayThresholds(
        active_days=config.admin.admin_delay_active_days,
        no_responses_hours=config.admin.admin_no_responses_hours,
        low_picked_hours=config.admin.admin_low_picked_hours,
        archive_days=config.admin.admin_archive_days,
    )
    referral_income_service: ReferralIncomeService | None = None
    if container.session_factory and container.transaction_manager:
        referral_income_service = container.build_referral_income_service()
    offer_dispatch_service = (
        container.build_offer_dispatch_service()
        if container.session_factory
        else None
    )
    return AdminDashboardService(
        session_factory=container.session_factory,
        timezone_name=config.admin.admin_dashboard_timezone,
        thresholds=thresholds,
        referral_income_service=referral_income_service,
        offer_dispatch_service=offer_dispatch_service,
    )


_ADMIN_STATIC = Path(__file__).parent / "static"
_ADMIN_ASSET_VERSIONS = {
    asset.name: sha256(asset.read_bytes()).hexdigest()[:12]
    for asset in _ADMIN_STATIC.iterdir()
    if asset.suffix in {".css", ".js"}
}


def _admin_asset(request: Request, name: str) -> URL:
    return request.url_for("admin_mvp_static", path=name).include_query_params(
        v=_ADMIN_ASSET_VERSIONS[name]
    )


def _admin_date(value: datetime | str | None, zone: ZoneInfo) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value
        value = parsed
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone).strftime("%d.%m.%Y, %H:%M")


def _build_templates(app: FastAPI, zone: ZoneInfo) -> Jinja2Templates:
    """Attach static assets and return templates instance."""
    templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )
    templates.env.globals["order_return_url"] = _order_return_url
    templates.env.globals["admin_asset"] = _admin_asset
    templates.env.globals["admin_action_token"] = _admin_action_token
    templates.env.filters["instagram_link"] = instagram_link
    templates.env.filters["telegram_handle"] = telegram_handle
    templates.env.filters["admin_date"] = lambda value: _admin_date(value, zone)
    app.mount(
        "/admin/mvp-static",
        StaticFiles(directory=str(_ADMIN_STATIC)),
        name="admin_mvp_static",
    )
    return templates


def _dashboard_cache_ttl(period: str) -> int:
    """TTL in seconds for dashboard/charts by period."""
    if period in ("today", "yesterday"):
        return 90
    if period == "all":
        return 600
    return 300


async def _get_cached_or_fetch(
    cache: AdminCache | None,
    cache_key: str | None,
    ttl: int,
    fetch_coro,
) -> dict[str, Any]:
    """Return cached payload or await fetch_coro(); then cache."""
    if cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    result = await fetch_coro()
    if cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(result),
            ttl,
        )
    return result


async def _get_dashboard_payload_cached(
    dashboard_service: AdminDashboardService,
    period_key: PeriodKey,
    cache: AdminCache | None,
    use_cache: bool,
    cache_key: str | None,
    referrers_page: int = 1,
    referrers_per_page: int = 25,
    referrers_sort: str | None = None,
    referrers_order: str | None = None,
    referrers_filter: str | None = None,
    include_timings: bool = False,
) -> dict[str, Any]:
    """Load dashboard from cache or dashboard_service; set cache when used."""
    if cache and use_cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    payload = await dashboard_service.get_dashboard(
        period_key,
        referrers_page=referrers_page,
        referrers_per_page=referrers_per_page,
        referrers_sort=referrers_sort,
        referrers_order=referrers_order or "desc",
        referrers_filter=referrers_filter,
        include_timings=include_timings,
    )
    if cache and use_cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(payload),
            _dashboard_cache_ttl(period_key),
        )
    return payload


def _dashboard_cache_key(
    period_key: str,
    referrers_filter: str,
    referrers_page: int,
    referrers_per_page: int,
    referrers_sort: str,
    referrers_order: str,
) -> str:
    """Build cache key for dashboard/referrers payload."""
    return (
        f"dashboard:v5:{period_key}:{referrers_filter or 'all'}:"
        f"{referrers_page}:{referrers_per_page}:"
        f"{referrers_sort or ''}:{referrers_order}"
    )


async def _render_dashboard_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    period: str,
    referrers_page: int,
    referrers_per_page: int,
    referrers_sort: str,
    referrers_order: str,
    referrers_filter: str,
    timings: str,
):
    """Render dashboard HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    period_key = _normalize_period(period)
    include_timings = (
        timings.lower() in ("1", "true", "yes") if timings else False
    )
    use_cache = bool(cache and not include_timings)
    cache_key = (
        _dashboard_cache_key(
            period_key,
            referrers_filter,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
        )
        if use_cache
        else None
    )
    payload = await _get_dashboard_payload_cached(
        dashboard_service,
        period_key,
        cache,
        use_cache,
        cache_key,
        referrers_page=referrers_page,
        referrers_per_page=referrers_per_page,
        referrers_sort=referrers_sort or None,
        referrers_order=referrers_order or "desc",
        referrers_filter=referrers_filter or None,
        include_timings=include_timings,
    )
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "payload": payload,
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "status_labels": _STATUS_LABELS,
            "delay_reason_labels": _DELAY_REASON_LABELS,
            "referrers_sort": referrers_sort,
            "referrers_order": referrers_order,
            "referrers_filter": referrers_filter,
        },
    )


async def _render_referrers_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    period: str,
    referrers_page: int,
    referrers_per_page: int,
    referrers_sort: str,
    referrers_order: str,
    referrers_filter: str,
    timings: str,
):
    """Render referrers HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    period_key = _normalize_period(period)
    include_timings = (
        timings.lower() in ("1", "true", "yes") if timings else False
    )
    use_cache = bool(cache and not include_timings)
    cache_key = (
        _dashboard_cache_key(
            period_key,
            referrers_filter,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
        )
        if use_cache
        else None
    )
    payload = await _get_dashboard_payload_cached(
        dashboard_service,
        period_key,
        cache,
        use_cache,
        cache_key,
        referrers_page=referrers_page,
        referrers_per_page=referrers_per_page,
        referrers_sort=referrers_sort or None,
        referrers_order=referrers_order or "desc",
        referrers_filter=referrers_filter or None,
        include_timings=include_timings,
    )
    return templates.TemplateResponse(
        request,
        "referrers.html",
        {
            "payload": payload,
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "referrers_sort": referrers_sort,
            "referrers_order": referrers_order,
            "referrers_filter": referrers_filter,
        },
    )


async def _render_creators_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
    period: str,
    only_new: bool,
    with_complaints: bool,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
    city: str,
    status: str,
    followers_min: int | None,
):
    """Render creators list HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    period_key = _normalize_period(period)
    cache_params = (
        period_key,
        only_new,
        with_complaints,
        page,
        per_page,
        q,
        sort,
        order,
        city,
        status,
        followers_min,
    )
    cache_key = f"creator-directory:{cache_params!r}" if cache else None

    async def _fetch():
        return await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
            city=city,
            status=status,
            followers_min=followers_min,
            include_ratings=True,
        )

    result = await _get_cached_or_fetch(
        cache, cache_key, list_cache_ttl, _fetch
    )
    creators_by_city = await dashboard_service.get_creators_by_city()
    cities = {
        row["city"].strip().lower()
        for row in creators_by_city
        if row["city"] and row["city"].strip()
    }
    if city:
        cities.add(city)
    return templates.TemplateResponse(
        request,
        "creators.html",
        {
            "creators": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "period": period_key if only_new else "all",
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "user_status_labels": _USER_STATUS_LABELS,
            "only_new": only_new,
            "with_complaints": with_complaints,
            "search_query": q,
            "sort": sort,
            "order": order,
            "cities": sorted(cities),
            "city": city,
            "status": status,
            "followers_min": followers_min,
        },
    )


async def _render_advertisers_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
    period: str,
    activity: str,
    with_complaints: bool,
):
    """Render advertisers list HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    period_key = _normalize_period(period)
    cache_params = (
        page,
        per_page,
        q,
        sort,
        order,
        period_key,
        activity,
        with_complaints,
    )
    cache_key = f"advertiser-directory:{cache_params!r}" if cache else None

    async def _fetch():
        return await dashboard_service.list_advertisers(
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
            period=period_key,
            activity=activity,
            with_complaints=with_complaints,
        )

    result = await _get_cached_or_fetch(
        cache, cache_key, list_cache_ttl, _fetch
    )
    return templates.TemplateResponse(
        request,
        "advertisers.html",
        {
            "advertisers": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "search_query": q,
            "sort": sort,
            "order": order,
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "activity": activity,
            "with_complaints": with_complaints,
        },
    )


async def _render_orders_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
    period: str,
    status: str | None,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    search: str | None = None,
):
    """Render orders list HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    period_key = _normalize_period(period)
    search_term = search.strip() if search else ""
    cache_key = (
        f"orders:v3:{period_key}:{status or ''}"
        f":{page}:{per_page}:{sort}:{order}"
        f":{search_term}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_orders(
            period=period_key,
            status_filter=status,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
            search=search_term or None,
        )

    result = await _get_cached_or_fetch(
        cache, cache_key, list_cache_ttl, _fetch
    )
    return templates.TemplateResponse(
        request,
        "orders.html",
        {
            "orders": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "period": period_key,
            "periods": _DASHBOARD_PERIODS,
            "period_labels": _PERIOD_LABELS,
            "status_filter": status,
            "status_labels": _STATUS_LABELS,
            "sort": sort,
            "order": order,
            "search_query": search_term,
        },
    )


async def _render_order_detail_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    order_id: UUID,
):
    """Render order detail HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    order = await dashboard_service.get_order_card(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return templates.TemplateResponse(
        request,
        "order_detail.html",
        {
            "order": order,
            "status_labels": ORDER_STATUS_LABELS,
        },
    )


async def _render_user_card_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    user_id: UUID,
):
    """Render user card HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    pages = {}
    for section in ("feedback", "complaints", "ratings", "nps", "orders"):
        raw = request.query_params.get(f"{section}_page", "")
        if raw.isascii() and raw.isdigit() and len(raw) <= 6:
            pages[section] = max(1, int(raw))
    user_card = await dashboard_service.get_user_card(user_id, pages)
    if user_card is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    order_url = _customer_order_url(request)
    directory_url = safe_admin_return_to(request.query_params.get("return_to"))
    if not directory_url or URL(directory_url).path not in {
        "/admin/users/creators",
        "/admin/users/advertisers",
        "/admin/search",
    }:
        directory_url = (
            "/admin/users/advertisers"
            if user_card.get("advertiser_profile")
            else "/admin/users/creators"
            if user_card.get("blogger_profile")
            else "/admin/search"
        )
    return templates.TemplateResponse(
        request,
        "user_card.html",
        {
            "user": user_card,
            "user_status_labels": _USER_STATUS_LABELS,
            "order_url": order_url,
            "directory_url": directory_url,
            "order_status_labels": ORDER_STATUS_LABELS,
            "complaint_status_labels": COMPLAINT_STATUS_LABELS,
            "rater_roles": {
                RaterRole.ADVERTISER: "Заказчик",
                RaterRole.MANAGER: "Менеджер",
                RaterRole.ADMIN: "Администратор",
            },
        },
    )


async def _api_dashboard_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    period: str,
    timings: str,
) -> dict[str, Any]:
    """Dashboard payload as JSON."""
    period_key = _normalize_period(period)
    include_timings = (
        timings.lower() in ("1", "true", "yes") if timings else False
    )
    cache_key = (
        f"dashboard_api:v5:{period_key}"
        if cache and not include_timings
        else None
    )
    if cache and not include_timings and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    payload = await dashboard_service.get_dashboard(
        period_key, include_timings=include_timings
    )
    if cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(payload),
            _dashboard_cache_ttl(period_key),
        )
    return payload


async def _api_charts_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    period: str,
) -> dict[str, Any]:
    """Charts payload as JSON."""
    period_key = _normalize_period(period)
    if cache:
        cache_key = f"charts:v4:{period_key}"
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    payload = await dashboard_service.get_dashboard_charts(period_key)
    if cache:
        await cache.set(
            cache_key,
            serialize_admin_payload(payload),
            _dashboard_cache_ttl(period_key),
        )
    return payload


async def _api_creators_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    period: str,
    only_new: bool,
    with_complaints: bool,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
) -> dict[str, Any]:
    """Creators list as JSON."""
    period_key = _normalize_period(period)
    cache_key = (
        f"creators:{period_key}:{only_new}:{with_complaints}:"
        f"{page}:{per_page}:{q or ''}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )

    return await _get_cached_or_fetch(cache, cache_key, list_ttl, _fetch)


async def _api_advertisers_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    page: int,
    per_page: int,
    q: str,
    sort: str,
    order: str,
) -> dict[str, Any]:
    """Advertisers list as JSON."""
    cache_key = (
        f"advertisers:v2:{page}:{per_page}:{q or ''}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_advertisers(
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )

    return await _get_cached_or_fetch(cache, cache_key, list_ttl, _fetch)


async def _api_orders_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    period: str,
    status: str | None,
    page: int,
    per_page: int,
    sort: str,
    order: str,
) -> dict[str, Any]:
    """Orders list as JSON."""
    period_key = _normalize_period(period)
    cache_key = (
        f"orders:v3:{period_key}:{status or ''}"
        f":{page}:{per_page}:{sort}:{order}"
        if cache
        else None
    )

    async def _fetch():
        return await dashboard_service.list_orders(
            period=period_key,
            status_filter=status,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
        )

    return await _get_cached_or_fetch(cache, cache_key, list_ttl, _fetch)


async def _render_search_page(
    request: Request,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_ttl: int,
    q: str,
):
    """Search users HTML page."""
    if not await auth.authenticate(request):
        return admin_login_redirect(request)
    cache_key = f"search:{q or ''}:50" if cache else None

    async def _fetch():
        return await dashboard_service.search_users(q, limit=50)

    if cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            data = cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
            users = data.get("users", [])
        else:
            users = await _fetch()
            await cache.set(
                cache_key,
                serialize_admin_payload({"query": q, "users": users}),
                list_ttl,
            )
    else:
        users = await _fetch()
    return templates.TemplateResponse(
        request,
        "search.html",
        {"query": q, "users": users},
    )


async def _api_search_json(
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_ttl: int,
    q: str,
) -> dict[str, Any]:
    """Search results as JSON."""
    cache_key = f"search:{q or ''}:20" if cache else None
    if cache and cache_key:
        raw = await cache.get(cache_key)
        if raw is not None:
            return cast(
                dict[str, Any],
                deserialize_admin_payload(raw),
            )
    users = await dashboard_service.search_users(q, limit=20)
    result = {"query": q, "users": users}
    if cache and cache_key:
        await cache.set(
            cache_key,
            serialize_admin_payload(result),
            list_ttl,
        )
    return result


def _make_require_admin(auth: AdminAuth):
    """Dependency: raise 401 if not authenticated."""

    async def _require_admin(request: Request) -> None:
        if not await auth.authenticate(request):
            raise HTTPException(status_code=401, detail="Не авторизован")

    return _require_admin


def _register_dashboard_html_routes(
    app: FastAPI,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None,
    list_cache_ttl: int,
) -> None:
    """Register dashboard/referrers/list/detail/search HTML routes."""

    @app.get("/admin/dashboard", response_class=HTMLResponse)
    async def admin_dashboard(
        request: Request,
        period: str = "today",
        referrers_page: int = 1,
        referrers_per_page: int = 25,
        referrers_sort: str = "",
        referrers_order: str = "desc",
        referrers_filter: str = "all",
        timings: str = "",
    ):
        return await _render_dashboard_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            period,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
            referrers_filter,
            timings,
        )

    @app.get("/admin/referrers", response_class=HTMLResponse)
    async def admin_referrers(
        request: Request,
        period: str = "today",
        referrers_page: int = 1,
        referrers_per_page: int = 25,
        referrers_sort: str = "",
        referrers_order: str = "desc",
        referrers_filter: str = "all",
        timings: str = "",
    ):
        return await _render_referrers_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            period,
            referrers_page,
            referrers_per_page,
            referrers_sort,
            referrers_order,
            referrers_filter,
            timings,
        )

    @app.get("/admin/users/creators", response_class=HTMLResponse)
    async def admin_creators(
        request: Request,
        period: str = "all",
        only_new: bool | None = None,
        with_complaints: bool = False,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
        city: str = "",
        status: str = "",
        followers_min: str = "",
    ):
        return await _render_creators_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            period,
            (period != "all") if only_new is None else only_new,
            with_complaints,
            page,
            per_page,
            q,
            sort,
            order,
            city.strip().lower(),
            status,
            int(followers_min)
            if followers_min.isascii()
            and followers_min.isdigit()
            and len(followers_min) <= 12
            else None,
        )

    @app.get("/admin/users/advertisers", response_class=HTMLResponse)
    async def admin_advertisers(
        request: Request,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
        period: str = "all",
        activity: str = "",
        with_complaints: bool = False,
    ):
        return await _render_advertisers_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            page,
            per_page,
            q,
            sort,
            order,
            period,
            activity,
            with_complaints,
        )

    @app.get("/admin/orders", response_class=HTMLResponse)
    async def admin_orders(
        request: Request,
        period: str = "today",
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        order: str = "desc",
        search: str | None = None,
    ):
        return await _render_orders_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            period,
            status,
            page,
            per_page,
            sort,
            order,
            search,
        )

    @app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
    async def admin_order_detail(request: Request, order_id: UUID):
        return await _render_order_detail_page(
            request,
            auth,
            dashboard_service,
            templates,
            order_id,
        )

    @app.get("/admin/users/{user_id}", response_class=HTMLResponse)
    async def admin_user_card(request: Request, user_id: UUID):
        return await _render_user_card_page(
            request,
            auth,
            dashboard_service,
            templates,
            user_id,
        )

    @app.get("/admin/search", response_class=HTMLResponse)
    async def admin_search(request: Request, q: str = ""):
        return await _render_search_page(
            request,
            auth,
            dashboard_service,
            templates,
            cache,
            list_cache_ttl,
            q,
        )


_FLOWCHART_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "product_flowchart.html"
)


def _register_flowchart_route(app: FastAPI, auth: AdminAuth) -> None:
    @app.get("/admin/flowchart", response_class=HTMLResponse)
    async def admin_flowchart(request: Request):
        if not await auth.authenticate(request):
            return admin_login_redirect(request)
        if not _FLOWCHART_PATH.exists():
            raise HTTPException(
                status_code=404,
                detail=(
                    "Flowchart not found. Run:"
                    " python scripts/generate_product_flowchart.py"
                ),
            )
        return HTMLResponse(content=_FLOWCHART_PATH.read_text())


def _register_dashboard_api_routes(
    app: FastAPI,
    require_admin,
    dashboard_service: AdminDashboardService,
    cache: AdminCache | None,
    list_cache_ttl: int,
) -> None:
    """Register dashboard/list/order/search API JSON routes."""

    @app.get("/admin/api/dashboard", dependencies=[Depends(require_admin)])
    async def dashboard_api(period: str = "today", timings: str = "") -> dict:
        return await _api_dashboard_json(
            dashboard_service, cache, period, timings
        )

    @app.get(
        "/admin/api/dashboard/charts", dependencies=[Depends(require_admin)]
    )
    async def dashboard_charts_api(period: str = "7d") -> dict:
        return await _api_charts_json(dashboard_service, cache, period)

    @app.get("/admin/api/users/creators", dependencies=[Depends(require_admin)])
    async def creators_api(
        period: str = "today",
        only_new: bool = False,
        with_complaints: bool = False,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        return await _api_creators_json(
            dashboard_service,
            cache,
            list_cache_ttl,
            period,
            only_new,
            with_complaints,
            page,
            per_page,
            q,
            sort,
            order,
        )

    @app.get(
        "/admin/api/users/advertisers", dependencies=[Depends(require_admin)]
    )
    async def advertisers_api(
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        return await _api_advertisers_json(
            dashboard_service,
            cache,
            list_cache_ttl,
            page,
            per_page,
            q,
            sort,
            order,
        )

    @app.get("/admin/api/orders", dependencies=[Depends(require_admin)])
    async def orders_api(
        period: str = "today",
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        return await _api_orders_json(
            dashboard_service,
            cache,
            list_cache_ttl,
            period,
            status,
            page,
            per_page,
            sort,
            order,
        )

    @app.get(
        "/admin/api/orders/{order_id}", dependencies=[Depends(require_admin)]
    )
    async def order_api(order_id: UUID) -> dict:
        order = await dashboard_service.get_order_card(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        return order

    @app.get("/admin/api/search", dependencies=[Depends(require_admin)])
    async def search_api(q: str = "") -> dict:
        return await _api_search_json(
            dashboard_service, cache, list_cache_ttl, q
        )


def _register_dashboard_routes(
    app: FastAPI,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None = None,
) -> None:
    """Register dashboard and list routes on the admin app."""
    _LIST_CACHE_TTL = 90
    require_admin = _make_require_admin(auth)
    _register_dashboard_html_routes(
        app, auth, dashboard_service, templates, cache, _LIST_CACHE_TTL
    )
    _register_flowchart_route(app, auth)
    _register_dashboard_api_routes(
        app, require_admin, dashboard_service, cache, _LIST_CACHE_TTL
    )


async def _get_obj_by_pk(
    view: ModelView,
    model_cls: type[T],
    pk: UUID,
) -> T | None:
    """Get model by pk, supporting both sync and async session makers."""
    if view.is_async:
        async with view.session_maker(expire_on_commit=False) as session:
            return await session.get(model_cls, pk)
    else:

        def _sync_get() -> T | None:
            with view.session_maker(expire_on_commit=False) as session:
                return session.get(model_cls, pk)

        return await asyncio.to_thread(_sync_get)


class UserAdmin(ModelView, model=UserModel):
    """Admin view for users."""

    can_delete = False
    name = "Пользователь"
    name_plural = "Пользователи"
    column_list = [
        UserModel.user_id,
        UserModel.telegram_id,
        UserModel.max_id,
        UserModel.messenger_type,
        UserModel.username,
        UserModel.telegram,
        UserModel.referral_code,
        UserModel.referral_payout_rate,
        UserModel.status,
        UserModel.admin,
        UserModel.issue_count,
        UserModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (UserModel.created_at, True)
    column_labels = {
        UserModel.user_id: "ID пользователя",
        UserModel.telegram_id: "Telegram ID",
        UserModel.max_id: "Max ID",
        UserModel.messenger_type: "Мессенджер",
        UserModel.username: "Имя пользователя",
        UserModel.telegram: "Telegram",
        UserModel.referral_code: "Реферальный код",
        UserModel.referral_payout_rate: "Процент выплаты рефералам",
        UserModel.status: "Статус",
        UserModel.admin: "Администратор",
        UserModel.issue_count: "Кол-во проблем",
        UserModel.created_at: "Дата создания",
    }
    # Side/period/reason overrides are managed in the signed partner cabinet.
    form_columns = [UserModel.admin]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update user model with status change handling."""

        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, UserModel, pk_uuid)
        old_status = obj.status if obj else None

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, UserModel, pk_uuid)
        new_status = obj.status if obj else None

        # If status changed to BLOCKED, log it
        if old_status != new_status and new_status == UserStatus.BLOCKED:
            try:
                container = _get_admin_container()
                if container:
                    user_role_service, _, _ = _get_services(container)
                    user = await user_role_service.get_user_by_id(UUID(pk))
                    if user:
                        logger.warning(
                            "User blocked via admin",
                            extra={
                                "user_id": str(user.user_id),
                                "telegram_id": user.telegram_id,
                                "max_id": user.max_id,
                                "username": user.username,
                                "previous_status": old_status.value
                                if old_status
                                else None,
                                "event_type": "user.blocked.admin",
                            },
                        )
            except Exception:
                logger.exception(
                    "Failed to log user blocked via admin",
                    extra={"pk": pk},
                )

        return result

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(UserModel.status != UserStatus.DELETED)

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(UserModel.status != UserStatus.DELETED)

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(UserModel.status != UserStatus.DELETED)


class BloggerProfileAdmin(ModelView, model=BloggerProfileModel):
    """Admin view for blogger profiles."""

    can_delete = False
    name = "Профиль креатора"
    name_plural = "Профили креаторов"
    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.confirmed,
        BloggerProfileModel.city,
        BloggerProfileModel.phone,
        BloggerProfileModel.country,
        BloggerProfileModel.blogger_gender,
        BloggerProfileModel.audience_gender,
        BloggerProfileModel.audience_age_min,
        BloggerProfileModel.audience_age_max,
        BloggerProfileModel.audience_geo,
        BloggerProfileModel.price,
        BloggerProfileModel.barter,
        BloggerProfileModel.work_format,
        BloggerProfileModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (BloggerProfileModel.updated_at, True)
    column_labels = {
        BloggerProfileModel.user_id: "ID пользователя",
        BloggerProfileModel.instagram_url: "Instagram",
        BloggerProfileModel.confirmed: "Подтверждён",
        BloggerProfileModel.city: "Город",
        BloggerProfileModel.phone: "Телефон",
        BloggerProfileModel.country: "Страна",
        BloggerProfileModel.blogger_gender: "Пол",
        BloggerProfileModel.audience_gender: "Пол аудитории",
        BloggerProfileModel.audience_age_min: "Возраст мин.",
        BloggerProfileModel.audience_age_max: "Возраст макс.",
        BloggerProfileModel.audience_geo: "Гео аудитории",
        BloggerProfileModel.price: "Цена",
        BloggerProfileModel.barter: "Бартер",
        BloggerProfileModel.work_format: "Формат работы",
        BloggerProfileModel.updated_at: "Обновлён",
    }

    async def update_model(self, request: Request, pk: str, data: dict) -> Any:
        """After save, refresh location from Nominatim if city changed."""
        result = await super().update_model(request, pk, data)
        if "city" in data:
            await _update_blogger_profile_location_from_nominatim(
                UUID(pk), data.get("city")
            )
        return result


class AdvertiserProfileAdmin(ModelView, model=AdvertiserProfileModel):
    """Admin view for advertiser profiles."""

    can_delete = False
    name = "Профиль заказчика"
    name_plural = "Профили заказчиков"
    column_list = [
        AdvertiserProfileModel.user_id,
        AdvertiserProfileModel.contact,
        AdvertiserProfileModel.brand,
        AdvertiserProfileModel.city,
        AdvertiserProfileModel.company_activity,
        AdvertiserProfileModel.site_link,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        AdvertiserProfileModel.user_id: "ID пользователя",
        AdvertiserProfileModel.contact: "Контакт",
        AdvertiserProfileModel.brand: "Бренд",
        AdvertiserProfileModel.city: "Город",
        AdvertiserProfileModel.company_activity: "Деятельность компании",
        AdvertiserProfileModel.site_link: "Сайт",
    }


def _truncate_50(value: str | None) -> str:
    """Truncate string to 50 chars with ellipsis if longer."""
    s = value or ""
    return s[:50] + ("…" if len(s) > 50 else "")


async def _handle_order_photo_upload(
    request: Request, auth: AdminAuth, config: AppConfig
) -> JSONResponse:
    """Validate an image and ask Telegram for a reusable photo file_id."""
    if not await auth.authenticate(request):
        return JSONResponse(
            {"error": "Требуется вход в админку"}, status_code=401
        )
    form = await request.form()
    upload = form.get("photo")
    if not isinstance(upload, StarletteUploadFile):
        return JSONResponse({"error": "Выберите PNG или JPG"}, status_code=400)
    content_type = (upload.content_type or "").lower()
    if content_type not in {"image/png", "image/jpeg"}:
        return JSONResponse(
            {"error": "Допустимы только PNG и JPG"}, status_code=400
        )
    image = await upload.read(10 * 1024 * 1024 + 1)
    if len(image) > 10 * 1024 * 1024:
        return JSONResponse(
            {"error": "Максимальный размер — 10 МБ"}, status_code=400
        )
    if not image.startswith(b"\x89PNG\r\n\x1a\n") and not image.startswith(
        b"\xff\xd8\xff"
    ):
        return JSONResponse(
            {"error": "Файл не похож на PNG или JPG"}, status_code=400
        )

    bot = Bot(token=config.bot.bot_token)
    try:
        sent = await bot.send_photo(
            chat_id=int(config.market.support_chat_id),
            photo=BufferedInputFile(
                image, filename=upload.filename or "order-image"
            ),
            caption="Изображение для шаблона заказа (сообщение будет удалено)",
        )
        photo_sizes = sent.photo
        try:
            await bot.delete_message(
                chat_id=sent.chat.id, message_id=sent.message_id
            )
        except Exception:
            logger.warning(
                "Could not remove temporary order photo from support chat"
            )
        if not photo_sizes:
            logger.error(
                "Telegram returned no photo sizes for uploaded order photo"
            )
            return JSONResponse(
                {"error": "Telegram не вернул данные фотографии"},
                status_code=502,
            )
        file_id = photo_sizes[-1].file_id
        return JSONResponse({"file_id": file_id})
    except Exception:
        logger.exception("Failed to upload order photo to Telegram")
        return JSONResponse(
            {
                "error": (
                    "Telegram не принял фото. Проверьте права бота "
                    "в чате поддержки."
                )
            },
            status_code=502,
        )
    finally:
        await bot.session.close()


def _order_duplicate_insert_data(source: OrderModel) -> dict[str, Any]:
    """Build insert payload: copy brief and filters, reset lifecycle fields."""
    skip = frozenset(
        {"order_id", "created_at", "updated_at", "completed_at"},
    )
    mapper = sa_inspect(OrderModel)
    data: dict[str, Any] = {}
    for col in mapper.columns:
        key = col.key
        if key in skip:
            continue
        if key == "status":
            data[key] = OrderStatus.NEW
        elif key in {"complimentary", "dispatch_stopped"}:
            data[key] = False
        elif key == "last_round_robin_index":
            data[key] = 0
        else:
            data[key] = getattr(source, key)
    return data


def _financial_order_admin_data(order, data):
    if order is None or getattr(order, "financial_version", None) is None:
        return data
    # Keep the terms used to calculate and capture payment immutable, while
    # allowing admins to correct the paid order brief and creator filters.
    immutable_fields = {
        "financial_version",
        "order_type",
        "price",
        "bloggers_needed",
    }
    for name in immutable_fields.intersection(data):
        value = data[name]
        current = getattr(order, name, object())
        if current == value or current in (None, "") and value in (None, ""):
            continue
        if name == "price":
            try:
                if Decimal(str(current)) == Decimal(str(value)):
                    continue
            except (ArithmeticError, ValueError):
                pass
        raise ValueError("financial_order_intake_immutable")
    return data


def _validate_activation_submission(submitted: dict) -> None:
    container = _get_admin_container()
    if container is None:
        return
    content_moderation, _, _ = _get_order_moderation_deps(container)
    content = {
        name: submitted.get(name)
        for name in (
            "product_link",
            "offer_text",
            "barter_description",
            "content_usage",
            "geography",
        )
    }
    if content_moderation.order_contains_banned_content(**content):
        matches = content_moderation.get_order_banned_matches(**content)
        raise ValueError(
            f"Запрещённый контент. Найдено: {', '.join(matches)}. "
            "Отредактируйте заявку."
        )


class OrderAdmin(ModelView, model=OrderModel):
    """Admin view for orders with moderation support."""

    can_delete = False
    name = "Заказ"
    name_plural = "Заказы"
    list_template = "order_list.html"
    page_size = 25
    page_size_options = [25, 50, 100]
    unpaid_age_hours = 24
    unpaid_reminders_enabled = False
    worklist_status_labels = ORDER_STATUS_LABELS
    worklist_columns = {
        "geography": "География",
        "price": "Цена",
        "status": "Статус",
        "username": "Заказчик",
        "brand": "Компания / бренд",
        "bloggers_needed": "Нужно блогеров",
        "offer_text": "Оффер",
        "created_at": "Создан",
    }
    column_list = [
        OrderModel.order_id,
        OrderModel.advertiser_id,
        OrderModel.order_type,
        OrderModel.offer_text,
        OrderModel.price,
        OrderModel.min_rating,
        OrderModel.bloggers_needed,
        OrderModel.status,
        OrderModel.geography,
        OrderModel.brief_link,
        OrderModel.created_at,
        OrderModel.completed_at,
    ]
    column_searchable_list = [
        OrderModel.offer_text,
        OrderModel.barter_description,
        OrderModel.product_link,
        OrderModel.geography,
        OrderModel.brief_link,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (OrderModel.created_at, True)
    column_formatters = {
        OrderModel.offer_text: lambda m, _: _truncate_50(  # type: ignore[attr-defined]
            getattr(m, "offer_text", None)
        ),
        OrderModel.barter_description: lambda m, _: _truncate_50(  # type: ignore[attr-defined]
            getattr(m, "barter_description", None)
        ),
    }
    column_labels = {
        OrderModel.order_id: "ID заказа",
        OrderModel.advertiser_id: "ID заказчика",
        OrderModel.product_link: "Ссылка на товар",
        OrderModel.offer_text: "Текст оффера",
        OrderModel.price: "Цена",
        OrderModel.bloggers_needed: "Нужно креаторов",
        OrderModel.content_usage: "Использование контента",
        OrderModel.deadlines: "Сроки",
        OrderModel.geography: "География",
        OrderModel.min_followers: "Мин. подписчиков",
        OrderModel.max_followers: "Макс. подписчиков",
        OrderModel.min_age: "Мин. возраст",
        OrderModel.max_age: "Макс. возраст",
        OrderModel.min_publications: "Мин. публикаций",
        OrderModel.max_publications: "Макс. публикаций",
        OrderModel.min_rating: "Мин. рейтинг",
        OrderModel.required_blogger_gender: "Пол",
        OrderModel.status: "Статус",
        OrderModel.created_at: "Дата создания",
        OrderModel.updated_at: "Дата обновления",
        OrderModel.completed_at: "Дата завершения",
        OrderModel.order_type: "Тип заказа",
        OrderModel.barter_description: "Описание бартера",
        OrderModel.product_photo_file_id: "ID фото товара",
        OrderModel.filter_by_price: "Фильтр по цене",
        OrderModel.price_filter_delta: "Допуск по цене (±)",
        OrderModel.filter_by_placement: "Фильтр по размещению",
        OrderModel.filter_by_barter: "Фильтр по бартеру",
        OrderModel.brief_link: "Ссылка на ТЗ",
    }
    form_columns = [
        OrderModel.order_type,
        OrderModel.product_link,
        OrderModel.offer_text,
        OrderModel.barter_description,
        OrderModel.price,
        OrderModel.bloggers_needed,
        OrderModel.status,
        OrderModel.content_usage,
        OrderModel.deadlines,
        OrderModel.geography,
        OrderModel.min_followers,
        OrderModel.max_followers,
        OrderModel.min_age,
        OrderModel.max_age,
        OrderModel.min_publications,
        OrderModel.max_publications,
        OrderModel.min_rating,
        OrderModel.required_blogger_gender,
        OrderModel.product_photo_file_id,
        OrderModel.filter_by_price,
        OrderModel.price_filter_delta,
        OrderModel.filter_by_placement,
        OrderModel.filter_by_barter,
        OrderModel.brief_link,
    ]
    edit_template = "order_edit.html"

    def _stmt_by_identifier(self, identifier: str):
        # Serialize SQLAdmin writes with deletion and other order transitions.
        return super()._stmt_by_identifier(identifier).with_for_update()

    async def on_model_change(self, data, model, is_created, request):
        if model is None or model.status == OrderStatus.DELETED:
            raise ValueError("Заказ удалён.")
        if data.get("status") == OrderStatus.DELETED:
            raise ValueError("Для удаления используйте кнопку «Удалить заказ».")

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update order with banned content check and activation publishing."""
        pk_uuid = UUID(pk)
        form_data = await request.form()
        managers_raw = str(form_data.get("managers", "") or "")

        obj = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        data = _financial_order_admin_data(obj, data)
        exact_city = None
        if obj is not None and "geography" in data:
            exact_city = await _validate_paid_order_geography_edit(
                obj, data["geography"]
            )
        if (
            obj is not None
            and "geography" in data
            and (
                (data["geography"] or "").strip()
                != (obj.geography or "").strip()
            )
        ):
            # Drop the previous boundaries in the same write as the new label.
            data = {**data, "location_geometry": None}
        submitted = data
        old_status = obj.status if obj else None
        new_status_raw = data.get("status")
        new_status_active = (
            new_status_raw == "active" or new_status_raw == OrderStatus.ACTIVE
        )

        activating = new_status_active and old_status != OrderStatus.ACTIVE
        if activating and old_status not in _ACTIVATABLE_ORDER_STATUSES:
            raise ValueError("order_activation_requires_new_or_pending")
        if (
            obj is not None
            and getattr(obj, "complimentary", False) is True
            and new_status_raw in _ACTIVATABLE_ORDER_STATUSES
        ):
            raise ValueError("Заказ уже запущен без оплаты.")
        if activating:
            _validate_activation_submission(submitted)

        if old_status == OrderStatus.ACTIVE and new_status_raw in {
            OrderStatus.CLOSED,
            OrderStatus.DELETED,
        }:
            data = {**data, "dispatch_stopped": True}
        if new_status_active:
            # Only the locked transition may commit ACTIVE and its event.
            data = {
                key: value for key, value in data.items() if key != "status"
            }
        result = await super().update_model(request, pk, data)
        await _finish_order_geography_and_activation(
            pk_uuid,
            data,
            activating=activating,
            saved_geography=getattr(obj, "geography", None),
            financial_version=getattr(obj, "financial_version", None),
            exact_city=exact_city,
        )

        try:
            await _update_order_managers(pk_uuid, managers_raw)
        except Exception:
            logger.exception(
                "Failed to update order managers",
                extra={"order_id": str(pk_uuid)},
            )

        return result

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        if "export_type" in request.path_params:
            return stmt.where(OrderModel.status != OrderStatus.DELETED)
        return self._filter_worklist(stmt, request)

    def _filter_worklist(self, stmt, request: Request):
        if advertiser_id := self.customer_filter(request):
            stmt = stmt.where(OrderModel.advertiser_id == advertiser_id)
        group = request.query_params.get("group", "work")
        if group == UNPAID_GROUP:
            if getattr(request.state, "unpaid_now", None) is None:
                request.state.unpaid_now = datetime.now(timezone.utc)
            return stmt.where(
                *worklist_conditions("work", ""),
                aging_unpaid_condition(
                    request.state.unpaid_now, self.unpaid_age_hours
                ),
            )
        return stmt.where(
            *worklist_conditions(group, request.query_params.get("status", ""))
        )

    @staticmethod
    def customer_filter(request: Request) -> UUID | None:
        identifier = request.query_params.get("advertiser_id")
        if identifier is None:
            return None
        try:
            return UUID(identifier)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Некорректный ID заказчика."
            ) from exc

    async def customer_context(self, advertiser_id: UUID):
        rows = await self._run_arbitrary_query(
            select(UserModel.username, AdvertiserProfileModel.brand)
            .outerjoin(
                AdvertiserProfileModel,
                AdvertiserProfileModel.user_id == UserModel.user_id,
            )
            .where(UserModel.user_id == advertiser_id)
        )
        return rows[0] if rows else None

    def count_query(self, request: Request):
        stmt = self._filter_worklist(super().count_query(request), request)
        if term := request.query_params.get("search", "").strip():
            stmt = stmt.where(search_orders(term))
        return stmt

    def search_query(self, stmt, term: str):
        return stmt.where(search_orders(term)) if term.strip() else stmt

    async def list(self, request: Request):
        pagination = await super().list(request)
        page_size = pagination.page_size
        last_page = max(1, (pagination.count + page_size - 1) // page_size)
        pagination.page = min(pagination.page, last_page)
        return pagination

    def sort_query(self, stmt, request: Request):
        sort_by = request.query_params.get("sortBy")
        if sort_by in self.worklist_columns and sort_by not in {
            "username",
            "brand",
        }:
            return (
                super().sort_query(stmt, request).order_by(OrderModel.order_id)
            )
        if request.query_params.get("group") == UNPAID_GROUP:
            return stmt.order_by(OrderModel.created_at, OrderModel.order_id)
        return stmt.order_by(OrderModel.created_at.desc(), OrderModel.order_id)

    async def worklist_details(self, rows: Sequence[OrderModel]):
        def load():
            with self.session_maker() as session:
                return worklist_row_details(
                    session, [row.order_id for row in rows]
                )

        return await asyncio.to_thread(load)

    async def unpaid_reminder_statuses(self, rows: Sequence[OrderModel]):
        def load():
            with self.session_maker() as session:
                return reminder_statuses(
                    session, [row.order_id for row in rows]
                )

        return await asyncio.to_thread(load)

    worklist_csrf_token = staticmethod(_admin_action_token)

    def form_edit_query(self, request: Request):
        return (
            super()
            ._stmt_by_identifier(request.path_params["pk"])
            .where(OrderModel.status != OrderStatus.DELETED)
        )

    @action(
        name="duplicate_order",
        label="Дублировать заказ",
        add_in_list=True,
        add_in_detail=True,
    )
    async def duplicate_order_action(
        self, request: Request
    ) -> RedirectResponse:
        """Insert a copy of the selected order and redirect to its edit page."""
        raw = (request.query_params.get("pks") or "").strip()
        pks = [p.strip() for p in raw.split(",") if p.strip()]
        if len(pks) != 1:
            raise HTTPException(
                status_code=400,
                detail="Выберите ровно один заказ для дублирования.",
            )
        try:
            pk_uuid = UUID(pks[0])
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Некорректный идентификатор заказа.",
            ) from exc

        source = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        if source is None or source.status == OrderStatus.DELETED:
            raise HTTPException(status_code=404, detail="Заказ не найден.")

        created = await self.insert_model(
            request, _order_duplicate_insert_data(source)
        )
        return RedirectResponse(
            str(
                request.url_for(
                    "admin:edit",
                    identity=self.identity,
                    pk=str(created.order_id),
                )
            ),
            status_code=302,
        )


class OfferDispatchAdmin(ModelView, model=OfferDispatchModel):
    """Admin view for offer dispatches and responses."""

    can_delete = False
    name = "Оффер (отправка/отклик)"
    name_plural = "Офферы (отправки и отклики)"
    column_list = [
        OfferDispatchModel.order_id,
        OfferDispatchModel.blogger_id,
        OfferDispatchModel.created_at,
        OfferDispatchModel.updated_at,
        OfferDispatchModel.accepted,
        OfferDispatchModel.in_offer,
        OfferDispatchModel.rejection_reason,
        OfferDispatchModel.desired_price,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (OfferDispatchModel.created_at, True)
    column_searchable_list = [OfferDispatchModel.rejection_reason]
    column_labels = {
        OfferDispatchModel.order_id: "ID заказа",
        OfferDispatchModel.blogger_id: "ID креатора",
        OfferDispatchModel.created_at: "Отправлено",
        OfferDispatchModel.updated_at: "Обновлено",
        OfferDispatchModel.accepted: "Принял оффер",
        OfferDispatchModel.in_offer: "В заказе",
        OfferDispatchModel.rejection_reason: "Причина отказа",
        OfferDispatchModel.desired_price: "Желаемая цена",
    }


class BloggerRatingAdmin(ModelView, model=BloggerRatingModel):
    """Admin view for blogger ratings."""

    can_delete = False
    name = "Рейтинг креатора"
    name_plural = "Рейтинги креаторов"
    column_list = [
        BloggerRatingModel.rating_id,
        BloggerRatingModel.blogger_id,
        BloggerRatingModel.order_id,
        BloggerRatingModel.rater_id,
        BloggerRatingModel.rater_role,
        BloggerRatingModel.score,
        BloggerRatingModel.comment,
        BloggerRatingModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (BloggerRatingModel.created_at, True)
    column_searchable_list = [BloggerRatingModel.comment]
    form_columns = [
        BloggerRatingModel.blogger_id,
        BloggerRatingModel.order_id,
        BloggerRatingModel.rater_id,
        BloggerRatingModel.rater_role,
        BloggerRatingModel.score,
        BloggerRatingModel.comment,
    ]
    column_labels = {
        BloggerRatingModel.rating_id: "ID рейтинга",
        BloggerRatingModel.blogger_id: "ID креатора",
        BloggerRatingModel.order_id: "ID заказа",
        BloggerRatingModel.rater_id: "Кто оценил",
        BloggerRatingModel.rater_role: "Роль",
        BloggerRatingModel.score: "Оценка",
        BloggerRatingModel.comment: "Комментарий",
        BloggerRatingModel.created_at: "Создан",
    }


class InteractionAdmin(ModelView, model=InteractionModel):
    """Read-only interactions; use protected financial review commands."""

    can_create = False
    can_edit = False
    can_delete = False
    name = "Взаимодействие"
    name_plural = "Взаимодействия"
    column_list = [
        InteractionModel.interaction_id,
        InteractionModel.order_id,
        InteractionModel.blogger_id,
        InteractionModel.advertiser_id,
        InteractionModel.status,
        InteractionModel.from_advertiser,
        InteractionModel.from_blogger,
        InteractionModel.created_at,
        InteractionModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (InteractionModel.created_at, True)
    column_labels = {
        InteractionModel.interaction_id: "ID взаимодействия",
        InteractionModel.order_id: "ID заказа",
        InteractionModel.blogger_id: "ID креатора",
        InteractionModel.advertiser_id: "ID заказчика",
        InteractionModel.status: "Статус",
        InteractionModel.from_advertiser: "От заказчика",
        InteractionModel.from_blogger: "От креатора",
        InteractionModel.created_at: "Создано",
        InteractionModel.updated_at: "Обновлено",
    }
    form_columns = [
        InteractionModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Reject raw status edits; use audited financial review."""
        raise PermissionError("Use an audited financial case review command")

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(InteractionModel.status != InteractionStatus.DELETED)

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(InteractionModel.status != InteractionStatus.DELETED)

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(InteractionModel.status != InteractionStatus.DELETED)


class InstagramVerificationAdmin(
    ModelView, model=InstagramVerificationCodeModel
):
    """Admin view for Instagram verification codes."""

    can_delete = False
    name = "Код верификации Instagram"
    name_plural = "Коды верификации Instagram"
    column_list = [
        InstagramVerificationCodeModel.code_id,
        InstagramVerificationCodeModel.user_id,
        InstagramVerificationCodeModel.code,
        InstagramVerificationCodeModel.expires_at,
        InstagramVerificationCodeModel.used,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        InstagramVerificationCodeModel.code_id: "ID кода",
        InstagramVerificationCodeModel.user_id: "ID пользователя",
        InstagramVerificationCodeModel.code: "Код",
        InstagramVerificationCodeModel.expires_at: "Истекает",
        InstagramVerificationCodeModel.used: "Использован",
    }


class ComplaintAdmin(ModelView, model=ComplaintModel):
    """Admin view for complaints."""

    can_delete = False
    name = "Жалоба"
    name_plural = "Жалобы"
    list_template = "complaint_list.html"
    details_template = "complaint_detail.html"
    page_size = 25
    status_labels = COMPLAINT_STATUS_LABELS
    open_statuses = OPEN_COMPLAINT_STATUSES
    column_list = [
        ComplaintModel.complaint_id,
        ComplaintModel.reporter_id,
        ComplaintModel.reported_id,
        ComplaintModel.order_id,
        ComplaintModel.reason,
        ComplaintModel.file_ids,
        ComplaintModel.status,
        ComplaintModel.created_at,
        ComplaintModel.reviewed_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (ComplaintModel.created_at, True)
    column_labels = {
        ComplaintModel.complaint_id: "ID жалобы",
        ComplaintModel.reporter_id: "ID заявителя",
        ComplaintModel.reported_id: "ID нарушителя",
        ComplaintModel.order_id: "ID заказа",
        ComplaintModel.reason: "Причина",
        ComplaintModel.file_ids: "ID файлов",
        ComplaintModel.status: "Статус",
        ComplaintModel.created_at: "Создана",
        ComplaintModel.reviewed_at: "Рассмотрена",
    }
    form_columns = [
        ComplaintModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update complaint model with automatic user blocking."""

        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, ComplaintModel, pk_uuid)
        old_status = obj.status if obj else None
        reported_id = obj.reported_id if obj else None

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, ComplaintModel, pk_uuid)
        new_status = obj.status if obj else None

        # If status changed to ACTION_TAKEN, block the reported user
        if (
            old_status != new_status
            and new_status == ComplaintStatus.ACTION_TAKEN
            and reported_id
        ):
            try:
                container = _get_admin_container()
                if container:
                    user_role_service, complaint_service, _ = _get_services(
                        container
                    )
                    # Update complaint status via service (sets reviewed_at)
                    await complaint_service.resolve_complaint_with_action(
                        UUID(pk)
                    )
                    # Block the reported user
                    await user_role_service.update_status(
                        reported_id, UserStatus.BLOCKED
                    )
            except Exception:
                logger.exception(
                    "resolve complaint and block user failed (ACTION_TAKEN)",
                    extra={
                        "complaint_id": pk,
                        "reported_id": str(reported_id),
                    },
                )
        elif (
            old_status != new_status and new_status == ComplaintStatus.DISMISSED
        ):
            try:
                container = _get_admin_container()
                if container:
                    _, complaint_service, _ = _get_services(container)
                    # Update complaint status via service (sets reviewed_at)
                    await complaint_service.dismiss_complaint(UUID(pk))
            except Exception:
                logger.exception(
                    "Failed to run dismiss_complaint after admin set DISMISSED",
                    extra={"complaint_id": pk},
                )

        return result

    def list_query(self, request: Request):
        return (
            super().list_query(request).where(self._status_condition(request))
        )

    def count_query(self, request: Request):
        return (
            super().count_query(request).where(self._status_condition(request))
        )

    @staticmethod
    def _status_condition(request: Request):
        status = request.query_params.get("status", "open")
        if status == "all":
            return ComplaintModel.status != ComplaintStatus.DELETED
        if status == "closed":
            return ComplaintModel.status.in_(
                (ComplaintStatus.DISMISSED, ComplaintStatus.ACTION_TAKEN)
            )
        return ComplaintModel.status.in_(OPEN_COMPLAINT_STATUSES)

    def search_query(self, stmt, term: str):
        return stmt.where(search_complaints(term)) if term.strip() else stmt

    def sort_query(self, stmt, request: Request):
        return (
            super()
            .sort_query(stmt, request)
            .order_by(ComplaintModel.complaint_id)
        )

    async def contexts(self, rows: Sequence[ComplaintModel]):
        if not rows:
            return {}
        result = await self._run_arbitrary_query(
            complaint_context([row.complaint_id for row in rows])
        )
        return {row.complaint_id: row for row in result}

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(ComplaintModel.status != ComplaintStatus.DELETED)


class CountryAdmin(ModelView, model=CountryModel):
    """Admin view for countries."""

    name = "Страна"
    name_plural = "Страны"
    icon = "fa-solid fa-globe"
    form_include_pk = True
    column_list = [
        CountryModel.code,
        CountryModel.name_native,
        CountryModel.currency_code,
        CountryModel.currency_symbol,
        CountryModel.tax_rate,
        CountryModel.enabled,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        CountryModel.code: "Код",
        CountryModel.name_native: "Название",
        CountryModel.currency_code: "Валюта",
        CountryModel.currency_symbol: "Символ валюты",
        CountryModel.tax_rate: "Ставка налога",
        CountryModel.enabled: "Активна",
    }
    form_columns = [
        CountryModel.code,
        CountryModel.name_native,
        CountryModel.currency_code,
        CountryModel.currency_symbol,
        CountryModel.tax_rate,
        CountryModel.enabled,
    ]


class ContactPricingAdmin(ModelView, model=ContactPricingModel):
    """Admin view for contact pricing."""

    can_delete = False
    form_include_pk = True
    name = "Цена контакта"
    name_plural = "Цены контактов"
    column_list = [
        ContactPricingModel.country_code,
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.currency,
        ContactPricingModel.updated_at,
    ]
    column_sortable_list = list(column_list)
    column_labels = {
        ContactPricingModel.country_code: "Страна",
        ContactPricingModel.bloggers_count: "Кол-во креаторов",
        ContactPricingModel.price: "Цена",
        ContactPricingModel.currency: "Валюта",
        ContactPricingModel.updated_at: "Обновлено",
    }
    form_columns = [
        ContactPricingModel.country_code,
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.currency,
    ]


class LanguageAdmin(ModelView, model=LanguageModel):
    """Admin view for languages."""

    name = "Язык"
    name_plural = "Языки"
    icon = "fa-solid fa-language"
    form_include_pk = True
    column_list = [
        LanguageModel.code,
        LanguageModel.name_native,
        LanguageModel.enabled,
    ]
    column_labels = {
        LanguageModel.code: "Код",
        LanguageModel.name_native: "Название",
        LanguageModel.enabled: "Активен",
    }
    form_columns = [
        LanguageModel.code,
        LanguageModel.name_native,
        LanguageModel.enabled,
    ]


class BotTextAdmin(ModelView, model=BotTextModel):
    """Admin view for localized bot texts (key, locale, value)."""

    can_delete = False
    name = "Текст бота"
    name_plural = "Тексты бота"
    column_list = [
        BotTextModel.key,
        BotTextModel.locale,
        BotTextModel.value,
        BotTextModel.updated_at,
    ]
    column_sortable_list = [BotTextModel.key, BotTextModel.locale]
    column_labels = {
        BotTextModel.key: "Ключ",
        BotTextModel.locale: "Локаль",
        BotTextModel.value: "Текст",
        BotTextModel.updated_at: "Обновлено",
    }
    form_columns = [
        BotTextModel.key,
        BotTextModel.locale,
        BotTextModel.value,
    ]


class NpsResponseAdmin(ModelView, model=NpsResponseModel):
    """Admin view for NPS responses (read-only)."""

    name = "NPS ответ"
    name_plural = "NPS ответы"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        NpsResponseModel.id,
        NpsResponseModel.user_id,
        NpsResponseModel.score,
        NpsResponseModel.comment,
        NpsResponseModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (NpsResponseModel.created_at, True)
    column_labels = {
        NpsResponseModel.id: "ID",
        NpsResponseModel.user_id: "ID пользователя",
        NpsResponseModel.score: "Оценка",
        NpsResponseModel.comment: "Комментарий",
        NpsResponseModel.created_at: "Дата",
    }


class PayoutRequestAdmin(ModelView, model=PayoutRequestModel):
    """Read-only legacy payout requests.

    Creation and mark-paid use guarded commands, never generic recipient,
    amount or status forms. Disputed wallets require audited financial review.
    """

    name = "Заявка на вывод"
    name_plural = "Заявки на вывод"
    can_create = False
    # Generic amount/recipient/status editing bypasses the payout safety-stop.
    can_edit = False
    can_delete = False
    column_list = [
        PayoutRequestModel.request_id,
        PayoutRequestModel.user_id,
        PayoutRequestModel.requested_at,
        PayoutRequestModel.status,
        PayoutRequestModel.amount,
        PayoutRequestModel.currency,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (PayoutRequestModel.requested_at, True)
    form_columns = [
        PayoutRequestModel.status,
        PayoutRequestModel.amount,
    ]
    column_labels = {
        PayoutRequestModel.request_id: "ID заявки",
        PayoutRequestModel.user_id: "ID пользователя",
        PayoutRequestModel.requested_at: "Дата запроса",
        PayoutRequestModel.status: "Статус",
        PayoutRequestModel.amount: "Сумма",
        PayoutRequestModel.currency: "Валюта",
    }

    def list_query(self, request: Request):
        stmt = super().list_query(request)
        return stmt.where(
            PayoutRequestModel.status != PayoutRequestStatus.DELETED,
            PayoutRequestModel.payout_protocol.is_(None),
        )

    def count_query(self, request: Request):
        stmt = super().count_query(request)
        return stmt.where(
            PayoutRequestModel.status != PayoutRequestStatus.DELETED,
            PayoutRequestModel.payout_protocol.is_(None),
        )

    def form_edit_query(self, request: Request):
        stmt = super().form_edit_query(request)
        return stmt.where(
            PayoutRequestModel.status != PayoutRequestStatus.DELETED,
            PayoutRequestModel.payout_protocol.is_(None),
        )


class ReferralIncomeEntryAdmin(ModelView, model=ReferralIncomeEntryModel):
    """Read-only admin view for referral income entries."""

    name = "Реферальное начисление"
    name_plural = "Реферальные начисления"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        ReferralIncomeEntryModel.entry_id,
        ReferralIncomeEntryModel.referrer_user_id,
        ReferralIncomeEntryModel.referred_user_id,
        ReferralIncomeEntryModel.order_id,
        ReferralIncomeEntryModel.income_type,
        ReferralIncomeEntryModel.currency,
        ReferralIncomeEntryModel.platform_revenue,
        ReferralIncomeEntryModel.commission_rate,
        ReferralIncomeEntryModel.commission_amount,
        ReferralIncomeEntryModel.created_at,
    ]
    column_sortable_list = list(column_list)
    column_default_sort = (ReferralIncomeEntryModel.created_at, True)
    column_labels = {
        ReferralIncomeEntryModel.entry_id: "ID",
        ReferralIncomeEntryModel.referrer_user_id: "Реферальщик",
        ReferralIncomeEntryModel.referred_user_id: "Реферал",
        ReferralIncomeEntryModel.order_id: "Заказ",
        ReferralIncomeEntryModel.income_type: "Тип",
        ReferralIncomeEntryModel.currency: "Валюта",
        ReferralIncomeEntryModel.platform_revenue: "Доход платформы",
        ReferralIncomeEntryModel.commission_rate: "Ставка",
        ReferralIncomeEntryModel.commission_amount: "Комиссия",
        ReferralIncomeEntryModel.created_at: "Дата",
    }


class PaymentAdmin(ModelView, model=PaymentModel):
    """Admin view for payments."""

    dashboard_timezone = ZoneInfo("Europe/Moscow")

    def list_query(self, request: Request):
        return self._for_paid_period(super().list_query(request), request)

    def count_query(self, request: Request):
        return self._for_paid_period(super().count_query(request), request)

    def _for_paid_period(self, stmt, request: Request):
        if period := request.query_params.get("paid_period"):
            window = dashboard_period_window(
                _normalize_period(period), self.dashboard_timezone
            )
            return stmt.where(
                paid_in_period(window.current_start, window.current_end)
            )
        return stmt

    @staticmethod
    def _v1_order_ids(data: dict, existing: PaymentModel | None) -> list[UUID]:
        from ugc_bot.application.errors import OrderCreationError

        if (
            data.get("financial_version") is not None
            or data.get("captured_minor") is not None
            or (
                existing is not None
                and (
                    existing.financial_version is not None
                    or existing.captured_minor is not None
                )
            )
        ):
            raise OrderCreationError("v1_payment_admin_forbidden")
        targets = [data.get("order_id"), data.get("order")]
        if existing is not None:
            targets.append(existing.order_id)
        return [
            t.order_id if isinstance(t, OrderModel) else UUID(str(t))
            for t in targets
            if t
        ]

    @staticmethod
    def _reject_v1_order(order: OrderModel | None) -> None:
        from ugc_bot.application.errors import OrderCreationError

        if order is not None and order.financial_version is not None:
            raise OrderCreationError("v1_payment_admin_forbidden")

    def _guard_v1_write_sync(self, data: dict, pk: str | None) -> None:
        with self.session_maker() as session:
            existing = session.get(PaymentModel, UUID(str(pk))) if pk else None
            for order_id in self._v1_order_ids(data, existing):
                self._reject_v1_order(session.get(OrderModel, order_id))

    async def _guard_v1_write(self, data: dict, pk: str | None = None) -> None:
        if not self.is_async:
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(self._guard_v1_write_sync, data, pk)
            return
        async with self.session_maker() as session:
            existing = (
                await session.get(PaymentModel, UUID(str(pk))) if pk else None
            )
            for order_id in self._v1_order_ids(data, existing):
                self._reject_v1_order(await session.get(OrderModel, order_id))

    async def insert_model(self, request: Request, data: dict) -> Any:
        await self._guard_v1_write(data)
        return await super().insert_model(request, data)

    async def update_model(self, request: Request, pk: str, data: dict) -> Any:
        await self._guard_v1_write(data, pk)
        return await super().update_model(request, pk, data)

    name = "Платёж"
    name_plural = "Платежи"
    can_create = True
    can_edit = True
    can_delete = False
    column_list = [
        PaymentModel.payment_id,
        PaymentModel.order_id,
        PaymentModel.provider,
        PaymentModel.status,
        PaymentModel.amount,
        PaymentModel.currency,
        PaymentModel.external_id,
        PaymentModel.created_at,
        PaymentModel.paid_at,
    ]
    column_sortable_list = [
        PaymentModel.status,
        PaymentModel.amount,
        PaymentModel.created_at,
        PaymentModel.paid_at,
    ]
    column_default_sort = (PaymentModel.created_at, True)
    form_columns = [
        PaymentModel.order,
        PaymentModel.provider,
        PaymentModel.status,
        PaymentModel.amount,
        PaymentModel.currency,
        PaymentModel.external_id,
        PaymentModel.paid_at,
    ]
    column_labels = {
        PaymentModel.payment_id: "ID платежа",
        PaymentModel.order_id: "ID заказа",
        PaymentModel.order: "Заказ",
        PaymentModel.provider: "Провайдер",
        PaymentModel.status: "Статус",
        PaymentModel.amount: "Сумма",
        PaymentModel.currency: "Валюта",
        PaymentModel.external_id: "Внешний ID",
        PaymentModel.created_at: "Дата создания",
        PaymentModel.paid_at: "Дата оплаты",
    }
    form_overrides = {
        "provider": SelectField,
        "currency": SelectField,
    }
    form_args = {
        "provider": {
            "choices": [
                ("manual", "manual"),
                ("yookassa_telegram", "yookassa_telegram"),
                ("telegram_payments", "telegram_payments"),
            ],
        },
        "currency": {
            "choices": [
                ("RUB", "RUB"),
                ("USD", "USD"),
                ("EUR", "EUR"),
                ("KZT", "KZT"),
                ("UZS", "UZS"),
                ("BYN", "BYN"),
            ],
        },
    }


class AuditLogAdmin(ModelView, model=AuditLogModel):
    """Read-only audit log viewer."""

    name = "Аудит лог"
    name_plural = "Аудит логи"
    icon = "fa-solid fa-clock-rotate-left"
    can_create = False
    can_edit = False
    can_delete = False
    column_list = [
        AuditLogModel.id,
        AuditLogModel.entity_type,
        AuditLogModel.entity_id,
        AuditLogModel.action,
        AuditLogModel.old_values,
        AuditLogModel.new_values,
        AuditLogModel.changed_by,
        AuditLogModel.changed_at,
    ]
    column_sortable_list = [
        AuditLogModel.entity_type,
        AuditLogModel.action,
        AuditLogModel.changed_at,
    ]
    column_default_sort = (AuditLogModel.changed_at, True)
    column_labels = {
        AuditLogModel.id: "ID",
        AuditLogModel.entity_type: "Тип сущности",
        AuditLogModel.entity_id: "ID сущности",
        AuditLogModel.action: "Действие",
        AuditLogModel.old_values: "Старые значения",
        AuditLogModel.new_values: "Новые значения",
        AuditLogModel.changed_by: "Кем изменено",
        AuditLogModel.changed_at: "Когда",
    }
    column_searchable_list = [AuditLogModel.entity_type]


class DashboardLinkView(BaseView):
    """Sidebar link: redirect to dashboard (no intermediate page)."""

    name = "Дашборд"
    icon = "fa-solid fa-chart-line"

    @expose("/dashboard-mvp", methods=["GET"])
    @login_required
    async def dashboard_redirect(self, request: Request):
        """Redirect to dashboard page."""
        return RedirectResponse(url="/admin/dashboard")


async def _inject_order_eligible_bloggers_count(
    context: dict[str, Any],
    model_view: Any,
    model: Any,
) -> None:
    """Set context['eligible_bloggers_count'] for OrderAdmin edit view."""
    if not isinstance(model_view, OrderAdmin):
        return
    try:
        container = _get_admin_container()
        if container and getattr(container, "session_factory", None):
            dispatch_svc = container.build_offer_dispatch_service()
            count = await dispatch_svc.count_eligible_bloggers(model.order_id)
            context["eligible_bloggers_count"] = count
        else:
            context["eligible_bloggers_count"] = None
    except OrderGeographyUnavailableError:
        context["eligible_bloggers_count"] = None
        context["order_geography_unavailable"] = True
    except Exception:
        context["eligible_bloggers_count"] = None


async def _inject_order_quote_details(context, model_view, model) -> None:
    """Saved quote and private preview stay read-only in the edit page."""
    if not isinstance(model_view, OrderAdmin) or model is None:
        return
    context["order_quote_details"] = None
    context["order_image_preview"] = None
    if (model.product_photo_file_id or "").startswith("order-image:"):
        context["order_image_preview"] = f"/admin/order-images/{model.order_id}"
    container = _get_admin_container()
    if container is None:
        return
    service = container.build_order_notice_details_service()
    if service is None:
        return
    details = await service.for_order(model)
    if details:
        context["order_quote_details"] = details | {
            key.removesuffix("_minor") + "_display": format(
                Decimal(details[key]) / 100, ".2f"
            )
            for key in (
                "selection_base_minor",
                "accompaniment_minor",
                "total_minor",
            )
        }


async def _handle_order_image_preview(request, auth, container, order_id):
    """Only authenticated admin sessions may read bound private images."""
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if not await auth.authenticate(request):
        return JSONResponse(
            {"error": "Требуется вход в админку"},
            status_code=401,
            headers=headers,
        )
    service = container.build_order_image_service()
    if service is None:
        return JSONResponse(
            {"error": "Изображение недоступно"},
            status_code=503,
            headers=headers,
        )
    order = await container.build_repos()["order_repo"].get_by_id(order_id)
    if order is None:
        return JSONResponse(
            {"error": "Изображение не найдено"},
            status_code=404,
            headers=headers,
        )
    try:
        content = await service.attached_content(order)
    except (LookupError, ValueError, OSError):
        return JSONResponse(
            {"error": "Изображение не найдено"},
            status_code=404,
            headers=headers,
        )
    return Response(content, media_type="image/jpeg", headers=headers)


async def _inject_order_managers(
    context: dict[str, Any],
    model_view: Any,
    model: Any,
) -> None:
    """Pre-populate managers field with current manager usernames."""
    if not isinstance(model_view, OrderAdmin) or model is None:
        return
    try:
        container = _get_admin_container()
        if container:
            manager_service = container.build_manager_service()
            manager_order_repo = manager_service.manager_order_repo
            user_repo = manager_service.user_repo
            tm = container.transaction_manager
            usernames: list[str] = []
            if tm:
                async with tm.transaction() as session:
                    manager_orders = await manager_order_repo.list_by_order(
                        model.order_id, session=session
                    )
                    for mo in manager_orders:
                        user = await user_repo.get_by_id(
                            mo.user_id, session=session
                        )
                        if user and user.telegram:
                            usernames.append(f"@{user.telegram}")
            context["managers_value"] = ", ".join(usernames)
    except Exception:
        logger.exception("Failed to inject order managers")


class EnumAwareAdmin(Admin):
    """Admin that fixes enum select fields showing first option instead of DB.

    SQLAdmin's conv_enum uses SQLAlchemy Enum.enums which with values_callable
    returns string values (e.g. 'pending_moderation'). The form receives
    Python enum from model (OrderStatus.PENDING_MODERATION). SelectField
    compares these and finds no match, defaulting to first option. We pass
    enum.value in form data so the select shows the correct option.
    """

    def init_templating_engine(self):
        templates = super().init_templating_engine()
        templates.env.globals["order_return_url"] = _order_return_url
        templates.env.globals["admin_asset"] = _admin_asset
        templates.env.globals["admin_action_token"] = _admin_action_token
        templates.env.globals["complaint_return_url"] = _complaint_return_url
        return templates

    @login_required
    async def index(self, request: Request):
        return RedirectResponse("/admin/dashboard", status_code=302)

    def get_save_redirect_url(self, request, form, model_view, obj):
        url = super().get_save_redirect_url(request, form, model_view, obj)
        if not isinstance(model_view, OrderAdmin) or request.method != "POST":
            return url
        if "return_to" not in request.query_params:
            return url
        if form.get("save") == "Save":
            return _order_return_url(request)
        if form.get("save") == "Save and continue editing":
            return URL(str(url)).include_query_params(
                return_to=_order_return_url(request)
            )
        return url

    async def login(self, request: Request):
        """Preserve a validated local destination across SQLAdmin login."""
        supplied: object = request.query_params.get("return_to")
        if request.method == "POST":
            supplied = supplied or (await request.form()).get("return_to")
        if supplied is not None:
            request.session.pop("admin_return_to", None)
            if target := safe_admin_return_to(supplied):
                request.session["admin_return_to"] = target
        response = await super().login(request)
        if request.method == "POST" and response.status_code == 302:
            target = safe_admin_return_to(
                request.session.pop("admin_return_to", None)
            )
            if target:
                return RedirectResponse(target, status_code=302)
        return response

    def _edit_form_data(
        self, model: Any, model_view: ModelView
    ) -> dict[str, Any]:
        """Build form data for edit. Enum fields use .value for SelectField.

        WTForms gives obj precedence over data, so we pass only data (no obj)
        with enum values as strings to fix select display.
        """
        data = dict(self._normalize_wtform_data(model))
        for prop_name in model_view._form_prop_names:
            if prop_name in data:
                continue
            try:
                value = getattr(model, prop_name, None)
            except Exception:
                continue
            if value is not None and isinstance(value, Enum):
                data[prop_name] = value.value
            elif value is not None:
                data[prop_name] = value
        return data

    @login_required
    async def edit(self, request: Request):  # pragma: no cover
        """Override edit to pass enum .value for correct select display."""
        from starlette.exceptions import HTTPException
        from starlette.responses import RedirectResponse

        await self._edit(request)

        identity = request.path_params["identity"]
        model_view = self._find_model_view(identity)

        model = await model_view.get_object_for_edit(request)
        if not model:
            raise HTTPException(status_code=404)

        Form = await model_view.scaffold_form(model_view._form_edit_rules)
        form_data = self._edit_form_data(model, model_view)
        context = {
            "obj": model,
            "model_view": model_view,
            "form": Form(data=form_data),
        }
        await _inject_order_eligible_bloggers_count(context, model_view, model)
        await _inject_order_managers(context, model_view, model)
        await _inject_order_quote_details(context, model_view, model)
        if isinstance(model_view, OrderAdmin):
            details = await model_view.worklist_details([model])
            context.update(
                order_actions=details.get(model.order_id),
                order_sections=ORDER_EDITOR_SECTIONS,
                order_limits=ORDER_EDITOR_LIMITS,
                order_hints=ORDER_EDITOR_HINTS,
                order_status_labels=ORDER_STATUS_LABELS,
            )

        if request.method == "GET":
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context
            )

        form_data_post = await self._handle_form_data(request, model)
        form = Form(form_data_post)
        context["form"] = form
        valid = form.validate()
        if isinstance(model_view, OrderAdmin):
            for name, error in changed_text_errors(model, form.data).items():
                form[name].errors = [*form[name].errors, error]
                valid = False
        if not valid:
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context, status_code=400
            )

        form_data_dict = self._denormalize_wtform_data(form.data, model)
        try:
            if (
                model_view.save_as
                and form_data_post.get("save") == "Save as new"
            ):
                obj = await model_view.insert_model(request, form_data_dict)
            else:
                obj = await model_view.update_model(
                    request, pk=request.path_params["pk"], data=form_data_dict
                )
        except Exception as e:
            logger.exception(e)
            context["error"] = str(e)
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context, status_code=400
            )

        url = self.get_save_redirect_url(
            request=request,
            form=form_data_post,
            obj=obj,
            model_view=model_view,
        )
        return RedirectResponse(url=url, status_code=302)


def _add_health_route(app: FastAPI, engine) -> None:
    """Register /health endpoint that checks DB connectivity."""

    @app.get("/health")
    async def health() -> dict[str, bool | str]:
        db_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok}


def _add_admin_views(admin: Admin) -> None:
    """Register all SQLAdmin model and base views."""
    admin.add_base_view(DashboardLinkView)
    admin.add_view(UserAdmin)
    admin.add_view(BloggerProfileAdmin)
    admin.add_view(AdvertiserProfileAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(BloggerRatingAdmin)
    admin.add_view(OfferDispatchAdmin)
    admin.add_view(InteractionAdmin)
    admin.add_view(InstagramVerificationAdmin)
    admin.add_view(ComplaintAdmin)
    admin.add_view(CountryAdmin)
    admin.add_view(ContactPricingAdmin)
    admin.add_view(LanguageAdmin)
    admin.add_view(BotTextAdmin)
    admin.add_view(NpsResponseAdmin)
    admin.add_view(PaymentAdmin)
    admin.add_view(PayoutRequestAdmin)
    admin.add_view(ReferralIncomeEntryAdmin)
    admin.add_view(AuditLogAdmin)


async def _change_order_dispatch(order_id: UUID, operation: str) -> str:
    container = _get_admin_container()
    if container is None or container.transaction_manager is None:
        return "Управление рассылкой недоступно."
    repos = container.build_repos()
    control = repos.get("dispatch_control")
    if control is None:
        return "Управление рассылкой недоступно."
    paused = operation == "pause"
    async with container.transaction_manager.transaction() as session:
        run = await control.change(order_id, paused=paused, session=session)
        if run is None:
            return "Действие недоступно для текущего состояния рассылки."
        if not paused:
            order = await repos["order_repo"].get_by_id(
                order_id, session=session
            )
            await container.build_outbox_publisher().resume_order_dispatch(
                order, run, session=session
            )
    return (
        "Рассылка на паузе."
        if paused
        else "Продолжение рассылки поставлено в очередь."
    )


def _register_order_worklist_action(
    app: FastAPI, auth: AdminAuth, engine: Engine, cache: AdminCache
) -> None:
    @app.post(
        "/admin/order-worklist/{order_id}/{operation}",
        dependencies=[Depends(_make_require_admin(auth))],
    )
    async def update_order_worklist(
        request: Request, order_id: UUID, operation: str
    ) -> Response:
        if operation not in {
            "close",
            "hide",
            "restore",
            "pause",
            "resume",
            "mark-test",
            "unmark-test",
            "delete-test",
        }:
            raise HTTPException(status_code=404)
        await _require_action_token(request)

        def update() -> str:
            with Session(engine) as session, session.begin():
                return change_order_worklist(session, order_id, operation)

        if operation in {"pause", "resume"}:
            message = await _change_order_dispatch(order_id, operation)
        else:
            message = await asyncio.to_thread(update)
        if operation in {
            "delete-test",
            "mark-test",
            "unmark-test",
            "hide",
            "restore",
            "close",
        }:
            await cache.invalidate_prefixes(
                "dashboard:",
                "dashboard_api:",
                "orders:",
                "charts:",
                "advertisers:",
            )
        request.session["order_worklist_message"] = message
        if "return_to" in request.query_params:
            target = _order_return_url(request)
            if URL(target).path != _ORDER_LIST_PATH:
                target = str(
                    URL(_ORDER_LIST_PATH).include_query_params(
                        search=str(order_id)
                    )
                )
        else:
            target = str(
                request.url_for(
                    "admin:list", identity=OrderAdmin.identity
                ).replace(query=request.url.query)
            )
        return RedirectResponse(target, status_code=303)


def _register_complaint_action(
    app: FastAPI, auth: AdminAuth, engine: Engine, cache: AdminCache
) -> None:
    @app.post(
        "/admin/complaints/{complaint_id}/close",
        dependencies=[Depends(_make_require_admin(auth))],
    )
    async def close_complaint(request: Request, complaint_id: UUID) -> Response:
        await _require_action_token(request)

        def update() -> bool:
            with Session(engine) as session, session.begin():
                return dismiss_open_complaint(session, complaint_id)

        closed = await asyncio.to_thread(update)
        if closed:
            await cache.invalidate_prefixes(
                "dashboard:", "dashboard_api:", "orders:"
            )
        request.session["complaint_message"] = (
            "Жалоба закрыта без мер."
            if closed
            else "Жалоба уже закрыта или недоступна."
        )
        return RedirectResponse(_complaint_return_url(request), status_code=303)


def create_admin_app() -> FastAPI:
    """Create a FastAPI app with SQLAdmin."""

    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )

    log_startup_info(logger=logger, service_name="admin", config=config)
    if not config.admin.admin_secret:
        raise ValueError("ADMIN_SECRET is required for SQLAdmin.")
    if not config.admin.admin_password:
        raise ValueError("ADMIN_PASSWORD is required for SQLAdmin.")

    container = Container(config)
    engine = container.get_admin_engine()
    app = FastAPI(title=config.admin.admin_site_name)
    app.add_middleware(SessionMiddleware, secret_key=config.admin.admin_secret)

    _add_health_route(app, engine)

    auth = AdminAuth(
        secret_key=config.admin.admin_secret,
        username=config.admin.admin_username,
        password=config.admin.admin_password,
    )
    dashboard_service = _build_dashboard_service(config, container)
    zone = ZoneInfo(config.admin.admin_dashboard_timezone)
    templates = _build_templates(app, zone)
    admin_cache = AdminCache(
        redis_url=config.redis.redis_url,
        enabled=config.redis.use_redis_storage,
        max_connections=config.redis.redis_max_connections,
        socket_timeout=config.redis.redis_socket_timeout,
        socket_connect_timeout=config.redis.redis_socket_connect_timeout,
    )
    _register_dashboard_routes(
        app, auth, dashboard_service, templates, cache=admin_cache
    )

    @app.post("/admin/order-photo-upload")
    async def upload_order_photo(request: Request) -> JSONResponse:
        """Upload an order image and return its Telegram file_id."""
        return await _handle_order_photo_upload(request, auth, config)

    @app.get("/admin/order-images/{order_id}")
    async def order_image_preview(request: Request, order_id: UUID) -> Response:
        return await _handle_order_image_preview(
            request, auth, container, order_id
        )

    _register_order_worklist_action(app, auth, engine, admin_cache)
    _register_complaint_action(app, auth, engine, admin_cache)

    admin = EnumAwareAdmin(
        app,
        engine,
        authentication_backend=auth,
        base_url="/admin",
        templates_dir=str(Path(__file__).parent / "templates"),
    )

    global _admin_container
    _admin_container = container

    admin.templates.env.filters["admin_date"] = lambda value: _admin_date(
        value, zone
    )
    PaymentAdmin.dashboard_timezone = zone
    _add_admin_views(admin)
    for view in admin.views:
        if isinstance(view, OrderAdmin):
            view.unpaid_age_hours = config.admin.admin_no_responses_hours
            view.unpaid_reminders_enabled = bool(
                config.order.unpaid_reminders_enabled
                and config.order.unpaid_reminders_start_at
            )

    @app.on_event("shutdown")
    async def _dispose_container() -> None:
        await container.dispose()

    return app


app = create_admin_app()
