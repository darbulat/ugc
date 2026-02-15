"""SQLAdmin application setup."""

import asyncio
import logging
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar, cast
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from sqladmin import Admin, BaseView, ModelView, expose
from sqladmin.authentication import login_required
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from ugc_bot.admin.auth import AdminAuth
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
    PeriodKey,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
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
    ComplaintStatus,
    InteractionStatus,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    NpsResponseModel,
    OrderModel,
    OrderResponseModel,
    PayoutRequestModel,
    UserModel,
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
    outbox_publisher, _ = container.build_outbox_deps()
    order_repo = container.build_repos()["order_repo"]
    return (content_moderation, outbox_publisher, order_repo)


T = TypeVar("T")
_DASHBOARD_PERIODS = ("today", "yesterday", "7d", "30d")
_PERIOD_LABELS = {
    "today": "Сегодня",
    "yesterday": "Вчера",
    "7d": "7 дней",
    "30d": "30 дней",
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
    "active_overdue": "Слишком долго активен",
    "no_responses": "Нет откликов",
    "low_picked": "Мало подобрано",
}


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
    return AdminDashboardService(
        session_factory=container.session_factory,
        timezone_name=config.admin.admin_dashboard_timezone,
        thresholds=thresholds,
        referral_income_service=referral_income_service,
    )


def _build_templates(app: FastAPI) -> Jinja2Templates:
    """Attach static assets and return templates instance."""
    templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )
    app.mount(
        "/admin/mvp-static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="admin_mvp_static",
    )
    return templates


def _dashboard_cache_ttl(period: str) -> int:
    """TTL in seconds for dashboard/charts by period."""
    if period in ("today", "yesterday"):
        return 90
    return 300


def _register_dashboard_routes(  # noqa: C901
    app: FastAPI,
    auth: AdminAuth,
    dashboard_service: AdminDashboardService,
    templates: Jinja2Templates,
    cache: AdminCache | None = None,
) -> None:
    """Register dashboard and list routes on the admin app."""
    _LIST_CACHE_TTL = 90

    async def _require_admin(request: Request) -> None:
        """Raise HTTP 401 when admin session is missing."""
        if not await auth.authenticate(request):
            raise HTTPException(status_code=401, detail="Не авторизован")

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
        """Render dashboard page with KPI cards."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        include_timings = (
            timings.lower() in ("1", "true", "yes") if timings else False
        )
        use_cache = cache and not include_timings
        cache_key = None
        if use_cache:
            cache_key = (
                f"dashboard:{period_key}:{referrers_filter or 'all'}:"
                f"{referrers_page}:{referrers_per_page}:"
                f"{referrers_sort or ''}:{referrers_order}"
            )
        payload = None
        if cache and use_cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                payload = cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        if payload is None:
            payload = await dashboard_service.get_dashboard(
                period_key,
                referrers_page=referrers_page,
                referrers_per_page=referrers_per_page,
                referrers_sort=referrers_sort or None,
                referrers_order=referrers_order,
                referrers_filter=referrers_filter or None,
                include_timings=include_timings,
            )
            if cache and use_cache and cache_key:
                await cache.set(
                    cache_key,
                    serialize_admin_payload(payload),
                    _dashboard_cache_ttl(period_key),
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
        """Render referrers (managers) page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        include_timings = (
            timings.lower() in ("1", "true", "yes") if timings else False
        )
        use_cache = cache and not include_timings
        cache_key = None
        if use_cache:
            cache_key = (
                f"dashboard:{period_key}:{referrers_filter or 'all'}:"
                f"{referrers_page}:{referrers_per_page}:"
                f"{referrers_sort or ''}:{referrers_order}"
            )
        payload = None
        if cache and use_cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                payload = cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        if payload is None:
            payload = await dashboard_service.get_dashboard(
                period_key,
                referrers_page=referrers_page,
                referrers_per_page=referrers_per_page,
                referrers_sort=referrers_sort or None,
                referrers_order=referrers_order,
                referrers_filter=referrers_filter or None,
                include_timings=include_timings,
            )
            if cache and use_cache and cache_key:
                await cache.set(
                    cache_key,
                    serialize_admin_payload(payload),
                    _dashboard_cache_ttl(period_key),
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

    @app.get("/admin/users/creators", response_class=HTMLResponse)
    async def admin_creators(
        request: Request,
        period: str = "today",
        only_new: bool = False,
        with_complaints: bool = False,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ):
        """Render creator list page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        cache_key = None
        if cache:
            cache_key = (
                f"creators:{period_key}:{only_new}:{with_complaints}:"
                f"{page}:{per_page}:{q or ''}:{sort}:{order}"
            )
        result = None
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                result = cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        if result is None:
            result = await dashboard_service.list_creators(
                period=period_key,
                only_new=only_new,
                only_with_complaints=with_complaints,
                page=page,
                per_page=per_page,
                q=q or None,
                sort=sort,
                order=order,
            )
            if cache and cache_key:
                await cache.set(
                    cache_key,
                    serialize_admin_payload(result),
                    _LIST_CACHE_TTL,
                )
        creators_by_city = await dashboard_service.get_creators_by_city()
        return templates.TemplateResponse(
            request,
            "creators.html",
            {
                "creators": result["items"],
                "total": result["total"],
                "page": result["page"],
                "per_page": result["per_page"],
                "total_pages": result["total_pages"],
                "period": period_key,
                "periods": _DASHBOARD_PERIODS,
                "period_labels": _PERIOD_LABELS,
                "user_status_labels": _USER_STATUS_LABELS,
                "only_new": only_new,
                "with_complaints": with_complaints,
                "search_query": q,
                "sort": sort,
                "order": order,
                "creators_by_city": creators_by_city,
            },
        )

    @app.get("/admin/users/advertisers", response_class=HTMLResponse)
    async def admin_advertisers(
        request: Request,
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ):
        """Render advertiser list page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        cache_key = (
            f"advertisers:{page}:{per_page}:{q or ''}:{sort}:{order}"
            if cache
            else None
        )
        result = None
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                result = cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        if result is None:
            result = await dashboard_service.list_advertisers(
                page=page,
                per_page=per_page,
                q=q or None,
                sort=sort,
                order=order,
            )
            if cache and cache_key:
                await cache.set(
                    cache_key,
                    serialize_admin_payload(result),
                    _LIST_CACHE_TTL,
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
            },
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
    ):
        """Render order list page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        period_key = _normalize_period(period)
        cache_key = None
        if cache:
            cache_key = (
                f"orders:{period_key}:{status or ''}:"
                f"{page}:{per_page}:{sort}:{order}"
            )
        result = None
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                result = cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        if result is None:
            result = await dashboard_service.list_orders(
                period=period_key,
                status_filter=status,
                page=page,
                per_page=per_page,
                sort=sort,
                order=order,
            )
            if cache and cache_key:
                await cache.set(
                    cache_key,
                    serialize_admin_payload(result),
                    _LIST_CACHE_TTL,
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
            },
        )

    @app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
    async def admin_order_detail(request: Request, order_id: UUID):
        """Render order detail page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        order = await dashboard_service.get_order_card(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        return templates.TemplateResponse(
            request,
            "order_detail.html",
            {
                "order": order,
                "status_labels": _STATUS_LABELS,
            },
        )

    @app.get("/admin/users/{user_id}", response_class=HTMLResponse)
    async def admin_user_card(request: Request, user_id: UUID):
        """Render user card (read-only) with all user and profile fields."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        user_card = await dashboard_service.get_user_card(user_id)
        if user_card is None:
            raise HTTPException(
                status_code=404, detail="Пользователь не найден"
            )
        return templates.TemplateResponse(
            request,
            "user_card.html",
            {
                "user": user_card,
                "user_status_labels": _USER_STATUS_LABELS,
            },
        )

    @app.get("/admin/api/dashboard", dependencies=[Depends(_require_admin)])
    async def dashboard_api(period: str = "today", timings: str = "") -> dict:
        """Return dashboard data as JSON."""
        period_key = _normalize_period(period)
        include_timings = (
            timings.lower() in ("1", "true", "yes") if timings else False
        )
        if cache and not include_timings:
            cache_key = f"dashboard_api:{period_key}"
            raw = await cache.get(cache_key)
            if raw is not None:
                return cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        payload = await dashboard_service.get_dashboard(
            period_key, include_timings=include_timings
        )
        if cache and not include_timings:
            await cache.set(
                cache_key,
                serialize_admin_payload(payload),
                _dashboard_cache_ttl(period_key),
            )
        return payload

    @app.get(
        "/admin/api/dashboard/charts", dependencies=[Depends(_require_admin)]
    )
    async def dashboard_charts_api(period: str = "7d") -> dict:
        """Return chart time-series data as JSON."""
        period_key = _normalize_period(period)
        if cache:
            cache_key = f"charts:{period_key}"
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

    @app.get(
        "/admin/api/users/creators", dependencies=[Depends(_require_admin)]
    )
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
        """Return creator list as JSON with pagination."""
        period_key = _normalize_period(period)
        cache_key = (
            f"creators:{period_key}:{only_new}:{with_complaints}:"
            f"{page}:{per_page}:{q or ''}:{sort}:{order}"
            if cache
            else None
        )
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                return cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        result = await dashboard_service.list_creators(
            period=period_key,
            only_new=only_new,
            only_with_complaints=with_complaints,
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )
        if cache and cache_key:
            await cache.set(
                cache_key,
                serialize_admin_payload(result),
                _LIST_CACHE_TTL,
            )
        return result

    @app.get(
        "/admin/api/users/advertisers", dependencies=[Depends(_require_admin)]
    )
    async def advertisers_api(
        page: int = 1,
        per_page: int = 25,
        q: str = "",
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        """Return advertiser list as JSON with pagination."""
        cache_key = (
            f"advertisers:{page}:{per_page}:{q or ''}:{sort}:{order}"
            if cache
            else None
        )
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                return cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        result = await dashboard_service.list_advertisers(
            page=page,
            per_page=per_page,
            q=q or None,
            sort=sort,
            order=order,
        )
        if cache and cache_key:
            await cache.set(
                cache_key,
                serialize_admin_payload(result),
                _LIST_CACHE_TTL,
            )
        return result

    @app.get("/admin/api/orders", dependencies=[Depends(_require_admin)])
    async def orders_api(
        period: str = "today",
        status: str | None = None,
        page: int = 1,
        per_page: int = 25,
        sort: str = "created_at",
        order: str = "desc",
    ) -> dict:
        """Return order list as JSON with pagination."""
        period_key = _normalize_period(period)
        cache_key = (
            f"orders:{period_key}:{status or ''}:{page}:{per_page}:"
            f"{sort}:{order}"
            if cache
            else None
        )
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                return cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
        result = await dashboard_service.list_orders(
            period=period_key,
            status_filter=status,
            page=page,
            per_page=per_page,
            sort=sort,
            order=order,
        )
        if cache and cache_key:
            await cache.set(
                cache_key,
                serialize_admin_payload(result),
                _LIST_CACHE_TTL,
            )
        return result

    @app.get(
        "/admin/api/orders/{order_id}", dependencies=[Depends(_require_admin)]
    )
    async def order_api(order_id: UUID) -> dict:
        """Return order card as JSON."""
        order = await dashboard_service.get_order_card(order_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Заказ не найден")
        return order

    @app.get("/admin/search", response_class=HTMLResponse)
    async def admin_search(
        request: Request,
        q: str = "",
    ):
        """Search users by nickname or Telegram ID; render results page."""
        if not await auth.authenticate(request):
            return RedirectResponse(url="/admin/login")
        cache_key = f"search:{q or ''}:50" if cache else None
        users = None
        if cache and cache_key:
            raw = await cache.get(cache_key)
            if raw is not None:
                data = cast(
                    dict[str, Any],
                    deserialize_admin_payload(raw),
                )
                users = data.get("users", [])
        if users is None:
            users = await dashboard_service.search_users(q, limit=50)
            if cache and cache_key:
                await cache.set(
                    cache_key,
                    serialize_admin_payload({"query": q, "users": users}),
                    _LIST_CACHE_TTL,
                )
        return templates.TemplateResponse(
            request,
            "search.html",
            {"query": q, "users": users},
        )

    @app.get("/admin/api/search", dependencies=[Depends(_require_admin)])
    async def search_api(q: str = "") -> dict:
        """Return search results as JSON."""
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
                _LIST_CACHE_TTL,
            )
        return result


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

    name = "Пользователь"
    name_plural = "Пользователи"
    column_list = [
        UserModel.user_id,
        UserModel.external_id,
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
    column_labels = {
        UserModel.user_id: "ID пользователя",
        UserModel.external_id: "Внешний ID",
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
    form_columns = [
        UserModel.admin,
        UserModel.referral_payout_rate,
    ]

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
                                "external_id": user.external_id,
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


class BloggerProfileAdmin(ModelView, model=BloggerProfileModel):
    """Admin view for blogger profiles."""

    name = "Профиль креатора"
    name_plural = "Профили креаторов"
    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.confirmed,
        BloggerProfileModel.city,
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
    column_labels = {
        BloggerProfileModel.user_id: "ID пользователя",
        BloggerProfileModel.instagram_url: "Instagram",
        BloggerProfileModel.confirmed: "Подтверждён",
        BloggerProfileModel.city: "Город",
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


class AdvertiserProfileAdmin(ModelView, model=AdvertiserProfileModel):
    """Admin view for advertiser profiles."""

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
    column_labels = {
        AdvertiserProfileModel.user_id: "ID пользователя",
        AdvertiserProfileModel.contact: "Контакт",
        AdvertiserProfileModel.brand: "Бренд",
        AdvertiserProfileModel.city: "Город",
        AdvertiserProfileModel.company_activity: "Деятельность компании",
        AdvertiserProfileModel.site_link: "Сайт",
    }


class OrderAdmin(ModelView, model=OrderModel):
    """Admin view for orders with moderation support."""

    name = "Заказ"
    name_plural = "Заказы"
    column_list = [
        OrderModel.order_id,
        OrderModel.advertiser_id,
        OrderModel.product_link,
        OrderModel.offer_text,
        OrderModel.price,
        OrderModel.bloggers_needed,
        OrderModel.content_usage,
        OrderModel.deadlines,
        OrderModel.geography,
        OrderModel.status,
        OrderModel.created_at,
    ]
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
        OrderModel.status: "Статус",
        OrderModel.created_at: "Дата создания",
        OrderModel.order_type: "Тип заказа",
        OrderModel.barter_description: "Описание бартера",
        OrderModel.product_photo_file_id: "ID фото товара",
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
        OrderModel.product_photo_file_id,
    ]

    async def update_model(self, request: Request, pk: str, data: dict):
        """Update order with banned content check and activation publishing."""
        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        old_status = obj.status if obj else None
        new_status_raw = data.get("status")
        new_status_active = (
            new_status_raw == "active" or new_status_raw == OrderStatus.ACTIVE
        )

        if new_status_active and old_status == OrderStatus.PENDING_MODERATION:
            container = _get_admin_container()
            if container:
                content_moderation, _, _ = _get_order_moderation_deps(container)
                if content_moderation.order_contains_banned_content(
                    product_link=data.get("product_link"),
                    offer_text=data.get("offer_text"),
                    barter_description=data.get("barter_description"),
                    content_usage=data.get("content_usage"),
                    geography=data.get("geography"),
                ):
                    matches = content_moderation.get_order_banned_matches(
                        product_link=data.get("product_link"),
                        offer_text=data.get("offer_text"),
                        barter_description=data.get("barter_description"),
                        content_usage=data.get("content_usage"),
                        geography=data.get("geography"),
                    )
                    raise ValueError(
                        f"Запрещённый контент. Найдено: {', '.join(matches)}. "
                        "Отредактируйте заявку."
                    )

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, OrderModel, pk_uuid)
        new_status = obj.status if obj else None

        if (
            old_status != OrderStatus.ACTIVE
            and new_status == OrderStatus.ACTIVE
        ):
            try:
                container = _get_admin_container()
                if container:
                    _, outbox_publisher, order_repo = (
                        _get_order_moderation_deps(container)
                    )
                    tm = container.transaction_manager
                    if tm:
                        async with tm.transaction() as session:
                            order = await order_repo.get_by_id(
                                pk_uuid, session=session
                            )
                            if order:
                                await outbox_publisher.publish_order_activation(
                                    order, session=session
                                )
            except Exception:
                logger.exception(
                    "Failed to publish order activation after admin approval",
                    extra={"order_id": str(pk_uuid)},
                )

        return result


class OrderResponseAdmin(ModelView, model=OrderResponseModel):
    """Admin view for order responses."""

    name = "Отклик на заказ"
    name_plural = "Отклики на заказы"
    column_list = [
        OrderResponseModel.response_id,
        OrderResponseModel.order_id,
        OrderResponseModel.blogger_id,
        OrderResponseModel.responded_at,
    ]
    column_labels = {
        OrderResponseModel.response_id: "ID отклика",
        OrderResponseModel.order_id: "ID заказа",
        OrderResponseModel.blogger_id: "ID креатора",
        OrderResponseModel.responded_at: "Дата отклика",
    }


class InteractionAdmin(ModelView, model=InteractionModel):
    """Admin view for interactions."""

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
        """Update interaction model with manual issue resolution."""

        pk_uuid = UUID(pk)
        obj = await _get_obj_by_pk(self, InteractionModel, pk_uuid)
        old_status = obj.status if obj else None

        result = await super().update_model(request, pk, data)

        obj = await _get_obj_by_pk(self, InteractionModel, pk_uuid)
        new_status = obj.status if obj else None

        # If manually resolving ISSUE to OK or NO_DEAL
        if old_status == InteractionStatus.ISSUE and new_status in (
            InteractionStatus.OK,
            InteractionStatus.NO_DEAL,
        ):
            try:
                container = _get_admin_container()
                if container:
                    _, _, interaction_service = _get_services(container)
                    await interaction_service.manually_resolve_issue(
                        UUID(pk), new_status
                    )
            except Exception:
                logger.exception(
                    "manually_resolve_issue failed after admin status change",
                    extra={
                        "interaction_id": pk,
                        "new_status": str(new_status),
                    },
                )

        return result


class InstagramVerificationAdmin(
    ModelView, model=InstagramVerificationCodeModel
):
    """Admin view for Instagram verification codes."""

    name = "Код верификации Instagram"
    name_plural = "Коды верификации Instagram"
    column_list = [
        InstagramVerificationCodeModel.code_id,
        InstagramVerificationCodeModel.user_id,
        InstagramVerificationCodeModel.code,
        InstagramVerificationCodeModel.expires_at,
        InstagramVerificationCodeModel.used,
    ]
    column_labels = {
        InstagramVerificationCodeModel.code_id: "ID кода",
        InstagramVerificationCodeModel.user_id: "ID пользователя",
        InstagramVerificationCodeModel.code: "Код",
        InstagramVerificationCodeModel.expires_at: "Истекает",
        InstagramVerificationCodeModel.used: "Использован",
    }


class ComplaintAdmin(ModelView, model=ComplaintModel):
    """Admin view for complaints."""

    name = "Жалоба"
    name_plural = "Жалобы"
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


class ContactPricingAdmin(ModelView, model=ContactPricingModel):
    """Admin view for contact pricing."""

    name = "Цена контакта"
    name_plural = "Цены контактов"
    column_list = [
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.updated_at,
    ]
    column_labels = {
        ContactPricingModel.bloggers_count: "Кол-во креаторов",
        ContactPricingModel.price: "Цена",
        ContactPricingModel.updated_at: "Обновлено",
    }
    form_columns = [
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
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
    column_labels = {
        NpsResponseModel.id: "ID",
        NpsResponseModel.user_id: "ID пользователя",
        NpsResponseModel.score: "Оценка",
        NpsResponseModel.comment: "Комментарий",
        NpsResponseModel.created_at: "Дата",
    }


class PayoutRequestAdmin(ModelView, model=PayoutRequestModel):
    """Admin view for payout requests (referral).

    Process: user requests payout in bot -> PENDING created -> support pays
    -> set status to PAID here. Changing amount here affects user's paid_total
    in referral stats. See docs/REFERRAL_PAYOUTS.md.
    """

    name = "Заявка на вывод"
    name_plural = "Заявки на вывод"
    can_create = False
    column_list = [
        PayoutRequestModel.request_id,
        PayoutRequestModel.user_id,
        PayoutRequestModel.requested_at,
        PayoutRequestModel.status,
        PayoutRequestModel.amount,
    ]
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
    }


class DashboardLinkView(BaseView):
    """Sidebar link: redirect to dashboard (no intermediate page)."""

    name = "Дашборд"
    icon = "fa-solid fa-chart-line"

    @expose("/dashboard-mvp", methods=["GET"])
    @login_required
    async def dashboard_redirect(self, request: Request):
        """Redirect to dashboard page."""
        return RedirectResponse(url="/admin/dashboard")


class EnumAwareAdmin(Admin):
    """Admin that fixes enum select fields showing first option instead of DB.

    SQLAdmin's conv_enum uses SQLAlchemy Enum.enums which with values_callable
    returns string values (e.g. 'pending_moderation'). The form receives
    Python enum from model (OrderStatus.PENDING_MODERATION). SelectField
    compares these and finds no match, defaulting to first option. We pass
    enum.value in form data so the select shows the correct option.
    """

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

        if request.method == "GET":
            return await self.templates.TemplateResponse(
                request, model_view.edit_template, context
            )

        form_data_post = await self._handle_form_data(request, model)
        form = Form(form_data_post)
        if not form.validate():
            context["form"] = form
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


def create_admin_app() -> FastAPI:  # noqa: C901
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

    @app.get("/health")
    async def health() -> dict[str, bool | str]:
        """Lightweight health check for admin app."""

        db_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "db": db_ok}

    auth = AdminAuth(
        secret_key=config.admin.admin_secret,
        username=config.admin.admin_username,
        password=config.admin.admin_password,
    )
    dashboard_service = _build_dashboard_service(config, container)
    templates = _build_templates(app)
    admin_cache = AdminCache(
        redis_url=config.redis.redis_url,
        enabled=config.redis.use_redis_storage,
    )
    _register_dashboard_routes(
        app, auth, dashboard_service, templates, cache=admin_cache
    )
    admin = EnumAwareAdmin(
        app, engine, authentication_backend=auth, base_url="/admin"
    )

    # Store container for service access in admin views
    global _admin_container
    _admin_container = container

    admin.add_base_view(DashboardLinkView)
    admin.add_view(UserAdmin)
    admin.add_view(BloggerProfileAdmin)
    admin.add_view(AdvertiserProfileAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderResponseAdmin)
    admin.add_view(InteractionAdmin)
    admin.add_view(InstagramVerificationAdmin)
    admin.add_view(ComplaintAdmin)
    admin.add_view(ContactPricingAdmin)
    admin.add_view(NpsResponseAdmin)
    admin.add_view(PayoutRequestAdmin)

    return app


app = create_admin_app()
