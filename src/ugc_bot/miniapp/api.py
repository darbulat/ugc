"""FastAPI router for Mini App HTTP API: auth, registration, orders."""

import logging
from datetime import date
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    BloggerRegistrationError,
    OrderCreationError,
    UserNotFoundError,
)
from ugc_bot.bot.validators import (
    VALIDATOR_ERR_KEYS,
    normalize_instagram_url,
    validate_audience_geo,
    validate_barter_description,
    validate_birth_date,
    validate_brand,
    validate_city,
    validate_company_activity,
    validate_geography,
    validate_instagram_url,
    validate_name,
    validate_nickname,
    validate_offer_text,
    validate_phone,
    validate_price,
    validate_product_link,
    validate_site_link,
    validate_topics,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    OrderType,
    WorkFormat,
)
from ugc_bot.miniapp.auth import validate_init_data_and_get_telegram_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["miniapp"])


# --- Request/response models ---


class InitDataBody(BaseModel):
    """Body that includes Telegram initData for auth."""

    init_data: str = Field(..., description="Telegram.WebApp.initData string")


class MeResponse(BaseModel):
    """Current user and profile flags."""

    user_id: str
    external_id: str
    role: str | None  # "advertiser" | "blogger" | null
    has_advertiser_profile: bool
    has_blogger_profile: bool


class RegisterAdvertiserRequest(BaseModel):
    """Advertiser registration payload."""

    init_data: str
    phone: str
    brand: str
    site_link: str | None = None
    city: str | None = None
    company_activity: str | None = None
    display_name: str | None = None


class RegisterBloggerRequest(BaseModel):
    """Blogger registration payload (all fields as in bot flow)."""

    init_data: str
    instagram_url: str
    city: str
    audience_geo: str
    audience_age_min: int = Field(..., ge=1)
    audience_age_max: int = Field(..., ge=1)
    audience_gender: str  # "m" | "f" | "all"
    price: float = Field(..., gt=0)
    barter: bool = False
    work_format: str  # "ads_in_account" | "ugc_only"
    topics: list[str] = Field(default_factory=list)  # 1-10 topics
    blogger_gender: str | None = None  # "m" | "f"
    display_name: str | None = None  # name / nickname
    birth_date: str | None = None  # DD.MM.YYYY
    telegram_username: str | None = None
    region: str | None = None
    country: str | None = None


class CreateOrderRequest(BaseModel):
    """Order creation payload."""

    init_data: str
    product_link: str
    offer_text: str
    price: float = Field(..., ge=0)
    bloggers_needed: int = Field(..., ge=1)
    order_type: str = "ugc_only"  # "ugc_only" | "ugc_plus_placement"
    barter_description: str | None = None
    content_usage: str | None = None
    deadlines: str | None = None
    geography: str | None = None


class OrderListItem(BaseModel):
    """Order summary for list."""

    order_id: str
    status: str
    product_link: str
    price: float
    order_type: str
    created_at: str


class OrdersListResponse(BaseModel):
    """List of orders."""

    orders: list[OrderListItem]


async def _get_validator_texts(request: Request) -> dict[str, str]:
    """Load validator error messages from bot_texts_service (same as bot)."""
    dispatcher = request.app.state.dispatcher
    bot_texts = dispatcher["bot_texts_service"]
    config = request.app.state.config
    locale = config.market.default_locale
    return await bot_texts.get_many(list(VALIDATOR_ERR_KEYS), locale)


def _get_telegram_user_id(request: Request, init_data: str) -> str:
    """Validate init_data and return Telegram user id. Raises HTTPException."""
    config = request.app.state.config
    bot_token = config.bot.bot_token
    try:
        return validate_init_data_and_get_telegram_user_id(init_data, bot_token)
    except ValueError as e:
        logger.warning("init_data validation failed: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e


async def _ensure_user_and_get_id(request: Request, init_data: str) -> UUID:
    """Ensure user exists (set_user), return internal user_id."""
    external_id = _get_telegram_user_id(request, init_data)
    dispatcher = request.app.state.dispatcher
    user_role_service = dispatcher["user_role_service"]
    user = await user_role_service.get_user(
        external_id=external_id, messenger_type=MessengerType.TELEGRAM
    )
    if user is None:
        await user_role_service.set_user(
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=f"user_{external_id}",
            role_chosen=False,
        )
        user = await user_role_service.get_user(
            external_id=external_id, messenger_type=MessengerType.TELEGRAM
        )
    if user is None:
        raise HTTPException(status_code=500, detail="Failed to resolve user")
    return user.user_id


@router.post("/me", response_model=MeResponse)
async def me(request: Request, body: InitDataBody) -> MeResponse:
    """Return current user id and profile flags (advertiser/blogger)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    profile_service = dispatcher["profile_service"]
    advertiser = await profile_service.get_advertiser_profile(user_id)
    blogger = await profile_service.get_blogger_profile(user_id)
    user = await profile_service.get_user_by_external(
        _get_telegram_user_id(request, body.init_data), MessengerType.TELEGRAM
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    role: str | None = None
    if advertiser is not None:
        role = "advertiser"
    elif blogger is not None:
        role = "blogger"
    return MeResponse(
        user_id=str(user_id),
        external_id=user.external_id,
        role=role,
        has_advertiser_profile=advertiser is not None,
        has_blogger_profile=blogger is not None,
    )


def _validate_advertiser_body(
    body: RegisterAdvertiserRequest, texts: dict[str, str]
) -> str | None:
    """Run bot validators on advertiser payload. Return first error or None."""
    err = validate_phone(body.phone, texts=texts)
    if err:
        return err
    err = validate_brand(body.brand, texts=texts)
    if err:
        return err
    if body.site_link:
        err = validate_site_link(body.site_link, texts=texts)
        if err:
            return err
    err = validate_city(body.city, required=False, texts=texts)
    if err:
        return err
    if body.company_activity:
        err = validate_company_activity(body.company_activity, texts=texts)
        if err:
            return err
    if body.display_name:
        err = validate_name(body.display_name, texts=texts)
        if err:
            return err
    return None


@router.post("/register/advertiser")
async def register_advertiser(
    request: Request, body: RegisterAdvertiserRequest
) -> dict:
    """Register current user as advertiser (same validation as bot)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    texts = await _get_validator_texts(request)
    err = _validate_advertiser_body(body, texts)
    if err:
        raise HTTPException(status_code=400, detail=err)
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["advertiser_registration_service"]
    try:
        profile = await svc.register_advertiser(
            user_id=user_id,
            phone=body.phone,
            brand=body.brand,
            site_link=body.site_link,
            city=body.city,
            company_activity=body.company_activity,
            display_name=body.display_name,
        )
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AdvertiserRegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "user_id": str(profile.user_id)}


def _parse_work_format(s: str) -> WorkFormat:
    try:
        return WorkFormat(s)
    except ValueError:
        vals = [e.value for e in WorkFormat]
        raise HTTPException(
            status_code=400, detail=f"work_format must be one of: {vals}"
        ) from None


def _parse_audience_gender(s: str) -> AudienceGender:
    try:
        return AudienceGender(s)
    except ValueError:
        vals = [e.value for e in AudienceGender]
        raise HTTPException(
            status_code=400, detail=f"audience_gender must be one of: {vals}"
        ) from None


def _parse_blogger_gender(s: str | None) -> BloggerGender:
    if s is None or s == "":
        return BloggerGender.MALE
    try:
        return BloggerGender(s)
    except ValueError:
        vals = [e.value for e in BloggerGender]
        raise HTTPException(
            status_code=400, detail=f"blogger_gender must be one of: {vals}"
        ) from None


def _validate_blogger_body(
    body: RegisterBloggerRequest,
    texts: dict[str, str],
    max_price: float,
    currency_symbol: str,
) -> str | None:
    """Run bot validators on blogger payload. Return first error or None."""
    err = validate_instagram_url(body.instagram_url, texts=texts)
    if err:
        return err
    if body.display_name:
        err = validate_nickname(body.display_name, texts=texts)
        if err:
            return err
    if body.birth_date:
        _, err = validate_birth_date(body.birth_date, texts=texts)
        if err:
            return err
    err = validate_topics(body.topics, texts=texts)
    if err:
        return err
    err = validate_city(body.city, required=True, texts=texts)
    if err:
        return err
    err = validate_audience_geo(body.audience_geo, texts=texts)
    if err:
        return err
    return validate_price(
        body.price, max_price, currency_symbol=currency_symbol, texts=texts
    )


@router.post("/register/blogger")
async def register_blogger(
    request: Request, body: RegisterBloggerRequest
) -> dict:
    """Register current user as blogger (same validation as bot)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    if body.audience_age_max < body.audience_age_min:
        raise HTTPException(
            status_code=400,
            detail="audience_age_max must be >= audience_age_min",
        )
    texts = await _get_validator_texts(request)
    config = request.app.state.config
    err = _validate_blogger_body(
        body,
        texts,
        config.order.max_order_price,
        config.market.currency_symbol,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    instagram_url = normalize_instagram_url(body.instagram_url)
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["blogger_registration_service"]
    existing = await svc.get_profile_by_instagram_url(instagram_url)
    if existing is not None:
        taken = (texts or {}).get(
            "err_instagram_taken",
            "This Instagram is already registered. Use another one.",
        )
        raise HTTPException(status_code=400, detail=taken)
    birth_date_val: date | None = None
    if body.birth_date:
        parsed, _ = validate_birth_date(body.birth_date, texts=texts)
        birth_date_val = parsed
    work_format = _parse_work_format(body.work_format)
    audience_gender = _parse_audience_gender(body.audience_gender)
    blogger_gender = _parse_blogger_gender(body.blogger_gender)
    topics_dict = {"selected": body.topics}
    try:
        await svc.save_blogger_before_agreement(
            user_id=user_id,
            instagram_url=instagram_url,
            city=body.city,
            topics=topics_dict,
            audience_gender=audience_gender,
            audience_age_min=body.audience_age_min,
            audience_age_max=body.audience_age_max,
            audience_geo=body.audience_geo,
            price=body.price,
            barter=body.barter,
            work_format=work_format,
            blogger_gender=blogger_gender,
            display_name=body.display_name,
            telegram_username=body.telegram_username,
            birth_date=birth_date_val,
            region=body.region,
            country=body.country,
        )
        await svc.confirm_blogger_agreement(
            user_id=user_id, telegram_username=body.telegram_username
        )
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except BloggerRegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "user_id": str(user_id)}


def _parse_order_type(s: str) -> OrderType:
    try:
        return OrderType(s)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"order_type must be one of: {[e.value for e in OrderType]}",
        ) from None


def _validate_order_body(
    body: CreateOrderRequest,
    texts: dict[str, str],
    max_price: float,
    currency_symbol: str,
) -> str | None:
    """Run bot validators on order payload. Return first error or None."""
    err = validate_product_link(body.product_link, texts=texts)
    if err:
        return err
    err = validate_offer_text(body.offer_text, texts=texts)
    if err:
        return err
    if body.price > 0:
        err = validate_price(
            body.price, max_price, currency_symbol=currency_symbol, texts=texts
        )
        if err:
            return err
    barter_required = body.price <= 0
    err = validate_barter_description(
        body.barter_description or "", required=barter_required, texts=texts
    )
    if err:
        return err
    if body.geography:
        return validate_geography(body.geography, texts=texts)
    return None


@router.post("/orders")
async def create_order(request: Request, body: CreateOrderRequest) -> dict:
    """Create an order (advertiser only, same validation as bot)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    profile_service = dispatcher["profile_service"]
    advertiser = await profile_service.get_advertiser_profile(user_id)
    if advertiser is None:
        raise HTTPException(
            status_code=403,
            detail="Advertiser profile required. Register as advertiser first.",
        )
    texts = await _get_validator_texts(request)
    config = request.app.state.config
    err = _validate_order_body(
        body,
        texts,
        config.order.max_order_price,
        config.market.currency_symbol,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    order_service = dispatcher["order_service"]
    order_type = _parse_order_type(body.order_type)
    try:
        order = await order_service.create_order(
            advertiser_id=user_id,
            order_type=order_type,
            product_link=body.product_link,
            offer_text=body.offer_text,
            barter_description=body.barter_description,
            price=body.price,
            bloggers_needed=body.bloggers_needed,
            content_usage=body.content_usage,
            deadlines=body.deadlines,
            geography=body.geography,
        )
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OrderCreationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "order_id": str(order.order_id),
        "status": order.status.value,
    }


class OrdersListRequest(BaseModel):
    """Request body for listing orders."""

    init_data: str


@router.post("/orders/list", response_model=OrdersListResponse)
async def list_orders(
    request: Request, body: OrdersListRequest
) -> OrdersListResponse:
    """List orders for the current advertiser."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    order_service = dispatcher["order_service"]
    orders = await order_service.list_by_advertiser(user_id)
    items = [
        OrderListItem(
            order_id=str(o.order_id),
            status=o.status.value,
            product_link=o.product_link,
            price=float(o.price),
            order_type=o.order_type.value,
            created_at=o.created_at.isoformat(),
        )
        for o in orders
    ]
    return OrdersListResponse(orders=items)
