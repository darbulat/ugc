"""Tortoise ORM models for FastAPI Admin."""

from __future__ import annotations

from tortoise import fields, models
from fastapi_admin.models import AbstractAdmin  # type: ignore[import-untyped]


class Admin(AbstractAdmin):
    """Admin user model for FastAPI Admin."""

    class Meta:
        table = "admin"


class User(models.Model):
    """User model for admin panel."""

    user_id = fields.UUIDField(pk=True)
    external_id = fields.CharField(max_length=255)
    messenger_type = fields.CharField(max_length=32)
    username = fields.CharField(max_length=255)
    role = fields.CharField(max_length=32)
    status = fields.CharField(max_length=32)
    issue_count = fields.IntField()
    created_at = fields.DatetimeField()

    class Meta:
        table = "users"


class BloggerProfile(models.Model):
    """Blogger profile model for admin panel."""

    user_id = fields.UUIDField(pk=True)
    instagram_url = fields.CharField(max_length=255)
    confirmed = fields.BooleanField()
    topics: fields.JSONField = fields.JSONField()
    audience_gender = fields.CharField(max_length=16)
    audience_age_min = fields.IntField()
    audience_age_max = fields.IntField()
    audience_geo = fields.CharField(max_length=255)
    price = fields.DecimalField(max_digits=10, decimal_places=2)
    updated_at = fields.DatetimeField()

    class Meta:
        table = "blogger_profiles"


class AdvertiserProfile(models.Model):
    """Advertiser profile model for admin panel."""

    user_id = fields.UUIDField(pk=True)
    contact = fields.CharField(max_length=255)

    class Meta:
        table = "advertiser_profiles"


class Order(models.Model):
    """Order model for admin panel."""

    order_id = fields.UUIDField(pk=True)
    advertiser_id = fields.UUIDField()
    product_link = fields.CharField(max_length=500)
    offer_text = fields.TextField()
    ugc_requirements = fields.TextField(null=True)
    barter_description = fields.TextField(null=True)
    price = fields.DecimalField(max_digits=10, decimal_places=2)
    bloggers_needed = fields.IntField()
    status = fields.CharField(max_length=32)
    created_at = fields.DatetimeField()
    contacts_sent_at = fields.DatetimeField(null=True)

    class Meta:
        table = "orders"


class OrderResponse(models.Model):
    """Order response model for admin panel."""

    response_id = fields.UUIDField(pk=True)
    order_id = fields.UUIDField()
    blogger_id = fields.UUIDField()
    responded_at = fields.DatetimeField()

    class Meta:
        table = "order_responses"


class Interaction(models.Model):
    """Interaction model for admin panel."""

    interaction_id = fields.UUIDField(pk=True)
    order_id = fields.UUIDField()
    blogger_id = fields.UUIDField()
    advertiser_id = fields.UUIDField()
    status = fields.CharField(max_length=32)
    from_advertiser = fields.TextField(null=True)
    from_blogger = fields.TextField(null=True)
    created_at = fields.DatetimeField()

    class Meta:
        table = "interactions"


class InstagramVerificationCode(models.Model):
    """Instagram verification code model for admin panel."""

    code_id = fields.UUIDField(pk=True)
    user_id = fields.UUIDField()
    code = fields.CharField(max_length=16)
    expires_at = fields.DatetimeField()
    used = fields.BooleanField()
    created_at = fields.DatetimeField()

    class Meta:
        table = "instagram_verification_codes"


class Complaint(models.Model):
    """Complaint model for admin panel."""

    complaint_id = fields.UUIDField(pk=True)
    reporter_id = fields.UUIDField()
    reported_id = fields.UUIDField()
    order_id = fields.UUIDField()
    reason = fields.TextField()
    status = fields.CharField(max_length=32)
    created_at = fields.DatetimeField()
    reviewed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "complaints"
