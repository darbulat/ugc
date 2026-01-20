"""SQLAdmin application setup."""

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqladmin import Admin, ModelView

from ugc_bot.admin.auth import AdminAuth
from ugc_bot.config import load_config
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


class BloggerProfileAdmin(ModelView, model=BloggerProfileModel):
    """Admin view for blogger profiles."""

    column_list = [
        BloggerProfileModel.user_id,
        BloggerProfileModel.instagram_url,
        BloggerProfileModel.confirmed,
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
        InteractionModel.created_at,
    ]


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
        ComplaintModel.status,
        ComplaintModel.created_at,
    ]


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
