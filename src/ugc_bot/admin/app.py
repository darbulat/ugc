"""SQLAdmin application setup."""

import logging
from uuid import UUID

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqladmin import Admin, ModelView
from starlette.requests import Request

from ugc_bot.admin.auth import AdminAuth
from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import load_config
from ugc_bot.domain.enums import ComplaintStatus, InteractionStatus, UserStatus
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    OrderModel,
    OrderResponseModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyComplaintRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory

logger = logging.getLogger(__name__)


def _get_services(
    engine,
) -> tuple[UserRoleService, ComplaintService, InteractionService]:
    """Get services for admin actions."""

    database_url = str(engine.url)
    session_factory = create_session_factory(database_url)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    complaint_repo = SqlAlchemyComplaintRepository(session_factory=session_factory)
    interaction_repo = SqlAlchemyInteractionRepository(session_factory=session_factory)

    user_role_service = UserRoleService(user_repo=user_repo)
    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    interaction_service = InteractionService(interaction_repo=interaction_repo)

    return user_role_service, complaint_service, interaction_service


class UserAdmin(ModelView, model=UserModel):
    """Admin view for users."""

    column_list = [
        UserModel.user_id,
        UserModel.external_id,
        UserModel.messenger_type,
        UserModel.username,
        UserModel.status,
        UserModel.issue_count,
        UserModel.created_at,
    ]
    form_columns = [
        UserModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict) -> None:
        """Update user model with status change handling."""

        # Get current object before update using session
        async with self.session.begin():  # type: ignore[attr-defined]
            obj = await self.session.get(UserModel, UUID(pk))  # type: ignore[attr-defined]
            old_status = obj.status if obj else None

        await super().update_model(request, pk, data)

        # Get updated object
        async with self.session.begin():  # type: ignore[attr-defined]
            obj = await self.session.get(UserModel, UUID(pk))  # type: ignore[attr-defined]
            new_status = obj.status if obj else None

        # If status changed to BLOCKED, log it
        if old_status != new_status and new_status == UserStatus.BLOCKED:
            try:
                engine = getattr(self, "_engine", None)  # type: ignore[attr-defined]
                if engine:
                    user_role_service, _, _ = _get_services(engine)
                    user = user_role_service.get_user_by_id(UUID(pk))
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
                # If logging fails, don't break the update
                pass


class BloggerProfileAdmin(ModelView, model=BloggerProfileModel):
    """Admin view for blogger profiles."""

    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.audience_gender,
        BloggerProfileModel.audience_age_min,
        BloggerProfileModel.audience_age_max,
        BloggerProfileModel.audience_geo,
        BloggerProfileModel.price,
        BloggerProfileModel.updated_at,
    ]


class AdvertiserProfileAdmin(ModelView, model=AdvertiserProfileModel):
    """Admin view for advertiser profiles."""

    column_list = [
        AdvertiserProfileModel.user_id,
        AdvertiserProfileModel.instagram_url,
        AdvertiserProfileModel.confirmed,
        AdvertiserProfileModel.contact,
    ]


class OrderAdmin(ModelView, model=OrderModel):
    """Admin view for orders."""

    column_list = [
        OrderModel.order_id,
        OrderModel.advertiser_id,
        OrderModel.product_link,
        OrderModel.offer_text,
        OrderModel.price,
        OrderModel.bloggers_needed,
        OrderModel.status,
        OrderModel.created_at,
    ]


class OrderResponseAdmin(ModelView, model=OrderResponseModel):
    """Admin view for order responses."""

    column_list = [
        OrderResponseModel.response_id,
        OrderResponseModel.order_id,
        OrderResponseModel.blogger_id,
        OrderResponseModel.responded_at,
    ]


class InteractionAdmin(ModelView, model=InteractionModel):
    """Admin view for interactions."""

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
    form_columns = [
        InteractionModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict) -> None:
        """Update interaction model with manual issue resolution."""

        # Get current object before update using session
        async with self.session.begin():  # type: ignore[attr-defined]
            obj = await self.session.get(InteractionModel, UUID(pk))  # type: ignore[attr-defined]
            old_status = obj.status if obj else None

        await super().update_model(request, pk, data)

        # Get updated object
        async with self.session.begin():  # type: ignore[attr-defined]
            obj = await self.session.get(InteractionModel, UUID(pk))  # type: ignore[attr-defined]
            new_status = obj.status if obj else None

        # If manually resolving ISSUE to OK or NO_DEAL
        if old_status == InteractionStatus.ISSUE and new_status in (
            InteractionStatus.OK,
            InteractionStatus.NO_DEAL,
        ):
            try:
                engine = getattr(self, "_engine", None)  # type: ignore[attr-defined]
                if engine:
                    _, _, interaction_service = _get_services(engine)
                    interaction_service.manually_resolve_issue(UUID(pk), new_status)
            except Exception:
                # If service call fails, the status change is already saved
                pass


class InstagramVerificationAdmin(ModelView, model=InstagramVerificationCodeModel):
    """Admin view for Instagram verification codes."""

    column_list = [
        InstagramVerificationCodeModel.code_id,
        InstagramVerificationCodeModel.user_id,
        InstagramVerificationCodeModel.code,
        InstagramVerificationCodeModel.expires_at,
        InstagramVerificationCodeModel.used,
    ]


class ComplaintAdmin(ModelView, model=ComplaintModel):
    """Admin view for complaints."""

    column_list = [
        ComplaintModel.complaint_id,
        ComplaintModel.reporter_id,
        ComplaintModel.reported_id,
        ComplaintModel.order_id,
        ComplaintModel.reason,
        ComplaintModel.status,
        ComplaintModel.created_at,
        ComplaintModel.reviewed_at,
    ]
    form_columns = [
        ComplaintModel.status,
    ]

    async def update_model(self, request: Request, pk: str, data: dict) -> None:
        """Update complaint model with automatic user blocking."""

        # Get current object before update using session
        async with self.session.begin():  # type: ignore[attr-defined]
            obj = await self.session.get(ComplaintModel, UUID(pk))  # type: ignore[attr-defined]
            old_status = obj.status if obj else None
            reported_id = obj.reported_id if obj else None

        await super().update_model(request, pk, data)

        # Get updated object
        async with self.session.begin():  # type: ignore[attr-defined]
            obj = await self.session.get(ComplaintModel, UUID(pk))  # type: ignore[attr-defined]
            new_status = obj.status if obj else None

        # If status changed to ACTION_TAKEN, block the reported user
        if (
            old_status != new_status
            and new_status == ComplaintStatus.ACTION_TAKEN
            and reported_id
        ):
            try:
                engine = getattr(self, "_engine", None)  # type: ignore[attr-defined]
                if engine:
                    user_role_service, complaint_service, _ = _get_services(engine)
                    # Update complaint status via service (sets reviewed_at)
                    complaint_service.resolve_complaint_with_action(UUID(pk))
                    # Block the reported user
                    user_role_service.update_status(reported_id, UserStatus.BLOCKED)
            except Exception:
                # If service call fails, the status change is already saved
                pass
        elif old_status != new_status and new_status == ComplaintStatus.DISMISSED:
            try:
                engine = getattr(self, "_engine", None)  # type: ignore[attr-defined]
                if engine:
                    _, complaint_service, _ = _get_services(engine)
                    # Update complaint status via service (sets reviewed_at)
                    complaint_service.dismiss_complaint(UUID(pk))
            except Exception:
                # If service call fails, the status change is already saved
                pass


class ContactPricingAdmin(ModelView, model=ContactPricingModel):
    """Admin view for contact pricing."""

    column_list = [
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
        ContactPricingModel.updated_at,
    ]
    form_columns = [
        ContactPricingModel.bloggers_count,
        ContactPricingModel.price,
    ]


def create_admin_app() -> FastAPI:
    """Create a FastAPI app with SQLAdmin."""

    config = load_config()
    if not config.admin_secret:
        raise ValueError("ADMIN_SECRET is required for SQLAdmin.")
    if not config.admin_password:
        raise ValueError("ADMIN_PASSWORD is required for SQLAdmin.")

    app = FastAPI(title=config.admin_site_name)
    engine = create_engine(config.database_url, pool_pre_ping=True)
    auth = AdminAuth(
        secret_key=config.admin_secret,
        username=config.admin_username,
        password=config.admin_password,
    )
    admin = Admin(app, engine, authentication_backend=auth, base_url="/admin")

    # Store engine reference in admin views for service access
    UserAdmin._engine = engine  # type: ignore[attr-defined]
    InteractionAdmin._engine = engine  # type: ignore[attr-defined]
    ComplaintAdmin._engine = engine  # type: ignore[attr-defined]

    admin.add_view(UserAdmin)
    admin.add_view(BloggerProfileAdmin)
    admin.add_view(AdvertiserProfileAdmin)
    admin.add_view(OrderAdmin)
    admin.add_view(OrderResponseAdmin)
    admin.add_view(InteractionAdmin)
    admin.add_view(InstagramVerificationAdmin)
    admin.add_view(ComplaintAdmin)
    admin.add_view(ContactPricingAdmin)
    return app


app = create_admin_app()
