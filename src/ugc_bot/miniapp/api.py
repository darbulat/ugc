"""FastAPI router for Mini App HTTP API: auth, registration, orders."""

import logging
from datetime import date
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import AnyHttpUrl, BaseModel, Field

from ugc_bot.application.errors import (
    AdvertiserRegistrationError,
    BloggerRegistrationError,
    OrderCreationError,
    OrderNotFoundError,
    UserNotFoundError,
)
from ugc_bot.application.geography import get_cities_list_for_miniapp
from ugc_bot.application.services.admin_notification_service import (
    notify_admins_about_complaint,
    notify_admins_about_order_created,
    notify_support_chat_about_new_order,
)
from ugc_bot.application.services.blogger_registration_service import (
    BloggerRegistrationService,
)
from ugc_bot.application.services.geocoder import wkt_multipoint_from_lat_lon
from ugc_bot.bot.telegram.handlers.utils import send_with_retry
from ugc_bot.bot.telegram.validators import (
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
from ugc_bot.domain.entities import User as UserEntity
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    MessengerType,
    OrderStatus,
    OrderType,
    WorkFormat,
)
from ugc_bot.miniapp.auth import (
    get_telegram_user_id_and_username,
    validate_init_data_and_get_telegram_user_id,
    validate_init_data_for_platform,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["miniapp"])


# --- Request/response models ---


class InitDataBody(BaseModel):
    """Body that includes initData for auth (Telegram or Max)."""

    init_data: str = Field(..., description="WebApp.initData string")
    platform: str = Field(
        default="telegram", description="Platform: 'telegram' or 'max'"
    )


class MeResponse(BaseModel):
    """Current user and profile flags plus profile data for pre-fill."""

    user_id: str
    external_id: str
    role: str | None  # "advertiser" | "blogger" | null
    has_advertiser_profile: bool
    has_blogger_profile: bool
    advertiser_profile: dict | None = None  # pre-fill form
    blogger_profile: dict | None = None  # pre-fill form
    country: str | None = None
    currency_code: str | None = None
    currency_symbol: str | None = None
    locale: str = "ru"
    is_manager: bool = False


# Content usage options for order form (same as bot order_creation_states).
CONTENT_USAGE_OPTIONS = [
    ("соцсети бренда", "📱 В соцсетях бренда"),
    ("реклама (таргет, объявления)", "📢 В рекламе (таргет, объявления)"),
    ("соцсети и реклама бренда", "🔄 В соцсетях и рекламе"),
]


class ConfigResponse(BaseModel):
    """Miniapp config: blogger counts, content usage, bot username, doc URLs."""

    allowed_blogger_counts: list[int]
    content_usage_options: list[
        dict[str, str]
    ]  # [{"value": "...", "label": "..."}]
    bot_username: str = ""
    docs_offer_url: str = ""
    docs_privacy_url: str = ""
    docs_consent_url: str = ""
    docs_offer_url_intl: str = ""
    docs_privacy_url_intl: str = ""
    docs_consent_url_intl: str = ""
    admin_instagram_username: str = ""
    countries: list[dict[str, str]] = []


class RegisterAdvertiserRequest(BaseModel):
    """Advertiser registration payload."""

    init_data: str
    platform: str = "telegram"
    phone: str
    brand: str
    site_link: str | None = None
    city: str | None = None
    company_activity: str | None = None
    display_name: str | None = None


class RegisterBloggerRequest(BaseModel):
    """Blogger registration payload (all fields as in bot flow)."""

    init_data: str
    platform: str = "telegram"
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
    lat: float | None = None  # from map picker; skip geocoder when set
    lon: float | None = None


def _location_geometry_from_blogger_request(
    body: RegisterBloggerRequest,
) -> str | None:
    """Build WKT from lat/lon when both are present and in valid range."""
    if body.lat is None or body.lon is None:
        return None
    if not (-90 <= body.lat <= 90 and -180 <= body.lon <= 180):
        return None
    return wkt_multipoint_from_lat_lon(body.lat, body.lon)


class CreateOrderRequest(BaseModel):
    """Order creation payload."""

    init_data: str
    platform: str = "telegram"
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
    payment_link: str = ""  # t.me/bot?start=pay_ORDER_ID
    currency_symbol: str = "₽"


class OrdersListResponse(BaseModel):
    """List of orders."""

    orders: list[OrderListItem]


class GetOrderRequest(BaseModel):
    """Request to fetch one order by id."""

    init_data: str
    platform: str = "telegram"
    order_id: str


class OrderDetailResponse(BaseModel):
    """Full order for view/edit screen."""

    order_id: str
    status: str
    product_link: str
    offer_text: str
    price: float
    bloggers_needed: int
    order_type: str
    barter_description: str | None
    content_usage: str | None
    deadlines: str | None
    geography: str | None
    created_at: str
    payment_link: str = ""


class UpdateOrderRequest(BaseModel):
    """Update order payload (same fields as create)."""

    init_data: str
    platform: str = "telegram"
    order_id: str
    product_link: str
    offer_text: str
    price: float = Field(..., ge=0)
    bloggers_needed: int = Field(..., ge=1)
    order_type: str = "ugc_only"
    barter_description: str | None = None
    content_usage: str | None = None
    deadlines: str | None = None
    geography: str | None = None


class ManagerOrdersRequest(BaseModel):
    """Manager orders list request."""

    init_data: str
    platform: str = "telegram"
    limit: int = 20
    offset: int = 0


class ManagerOrdersResponse(BaseModel):
    """Manager orders list response."""

    orders: list[OrderListItem]
    total: int


class ManagerCreatorsRequest(BaseModel):
    """Manager creators list request."""

    init_data: str
    platform: str = "telegram"
    in_offer: bool | None = None
    filter: Literal["in_offer", "reserve", "expensive"] | None = None
    search: str | None = None
    limit: int = 20
    offset: int = 0


class CreatorItem(BaseModel):
    """Creator summary for manager view."""

    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
    name: str | None = None
    desired_price: float | None = None


class ManagerCreatorsResponse(BaseModel):
    """Manager creators list response."""

    creators: list[CreatorItem]
    total: int


class CreatorDetailRequest(BaseModel):
    """Request to fetch a single creator's detail."""

    init_data: str
    platform: str = "telegram"


class CreatorDetailResponse(BaseModel):
    """Creator profile and current UGC video URL."""

    blogger_id: str
    instagram_url: str | None = None
    telegram: str | None = None
    ugc_video_url: str | None = None
    in_offer: bool = True


class UgcVideoRequest(BaseModel):
    """Request to save a UGC video URL."""

    init_data: str
    platform: str = "telegram"
    url: AnyHttpUrl


class ManagerFeedbackRequest(BaseModel):
    """Manager records advertiser-side feedback on an interaction."""

    init_data: str
    platform: str = "telegram"
    status: Literal["ok", "no_deal", "issue"]
    no_deal_reason: str | None = Field(None, max_length=1000)
    issue_description: str | None = Field(None, max_length=5000)


def _payment_link_for_order(order_id: str, bot_username: str) -> str:
    """Build t.me link to open bot with start=pay_ORDER_ID."""
    username = (bot_username or "").strip().lstrip("@")
    if not username:
        return ""
    return f"https://t.me/{username}?start=pay_{order_id}"


async def _currency_symbol_map(request: Request) -> dict[str, str]:
    """Build a mapping from currency code to currency symbol."""
    dispatcher = request.app.state.dispatcher
    country_repo = dispatcher.get("country_repo")
    if not country_repo:
        return {}
    countries = await country_repo.list_enabled()
    result: dict[str, str] = {}
    for c in countries:
        if c.currency_code not in result:
            result[c.currency_code] = c.currency_symbol
    return result


async def _get_user_locale(
    request: Request, external_id: str, *, platform: str = "telegram"
) -> str:
    """Resolve locale for user by external_id via user.language."""
    config = request.app.state.config
    default: str = config.market.default_locale
    dispatcher = request.app.state.dispatcher
    user_role_service = dispatcher.get("user_role_service")
    if not user_role_service:
        return default
    try:
        user = await user_role_service.get_user(
            external_id, _get_messenger_type(platform)
        )
    except Exception:
        logger.warning("Failed to resolve locale for user %s", external_id)
        return default
    if not user or not user.language:
        return default
    return user.language


async def _get_validator_texts(request: Request, locale: str) -> dict[str, str]:
    """Load validator error messages from bot_texts_service (same as bot)."""
    dispatcher = request.app.state.dispatcher
    bot_texts = dispatcher["bot_texts_service"]
    return await bot_texts.get_many(list(VALIDATOR_ERR_KEYS), locale)


def _get_bot_tokens(request: Request) -> tuple[str, str]:
    """Return (telegram_bot_token, max_bot_token) from config."""
    config = request.app.state.config
    tg_token = config.bot.bot_token
    max_bot = getattr(config, "max_bot", None)
    max_token = max_bot.token if max_bot else ""
    return tg_token, max_token


def _get_external_id(
    request: Request, init_data: str, *, platform: str = "telegram"
) -> str:
    """Validate init_data and return external user id. Raises HTTPException."""
    tg_token, max_token = _get_bot_tokens(request)
    try:
        return validate_init_data_for_platform(
            init_data,
            platform=platform,
            telegram_bot_token=tg_token,
            max_bot_token=max_token,
        )
    except ValueError as e:
        logger.warning("init_data validation failed: %s", e)
        raise HTTPException(status_code=401, detail=str(e)) from e


def _get_username_from_init_data(
    request: Request, init_data: str, *, platform: str = "telegram"
) -> str | None:
    """Return username from validated init_data, or None."""
    tg_token, max_token = _get_bot_tokens(request)
    token = tg_token if platform == "telegram" else max_token
    try:
        _, username = get_telegram_user_id_and_username(init_data, token)
        return username
    except ValueError:
        return None


def _get_messenger_type(platform: str) -> MessengerType:
    """Map platform string to MessengerType enum."""
    if platform == "max":
        return MessengerType.MAX
    return MessengerType.TELEGRAM


# Backward-compatible aliases
def _get_telegram_user_id(request: Request, init_data: str) -> str:
    return _get_external_id(request, init_data, platform="telegram")


def _get_telegram_username_from_init_data(
    request: Request, init_data: str
) -> str | None:
    return _get_username_from_init_data(request, init_data, platform="telegram")


async def _ensure_user_and_get_id(
    request: Request, init_data: str, *, platform: str = "telegram"
) -> UUID:
    """Ensure user exists (set_user), return internal user_id."""
    external_id = _get_external_id(request, init_data, platform=platform)
    messenger_type = _get_messenger_type(platform)
    username = _get_username_from_init_data(
        request, init_data, platform=platform
    )
    dispatcher = request.app.state.dispatcher
    user_role_service = dispatcher["user_role_service"]
    user = await user_role_service.get_user(
        external_id=external_id, messenger_type=messenger_type
    )
    if user is None:
        try:
            await user_role_service.set_user(
                external_id=external_id,
                messenger_type=messenger_type,
                username=f"user_{external_id}",
                role_chosen=False,
                telegram_username=username,
            )
        except Exception:
            logger.debug(
                "set_user race for external_id=%s, retrying GET",
                external_id,
            )
        user = await user_role_service.get_user(
            external_id=external_id, messenger_type=messenger_type
        )
    if user is None:
        raise HTTPException(status_code=500, detail="Failed to resolve user")
    if platform == "max" and user.country is None:
        try:
            await user_role_service.set_country(
                external_id=external_id,
                messenger_type=messenger_type,
                country_code="RU",
            )
        except Exception:
            logger.debug(
                "Failed to auto-set country for Max user %s", external_id
            )
    return user.user_id


async def _is_user_admin(dispatcher: Any, user_id: UUID) -> bool:
    """Check whether the user has the admin flag set."""
    try:
        user_repo = dispatcher.get("user_repo")
        if user_repo is None:
            return False
        user = await user_repo.get_by_id(user_id)
        return user is not None and getattr(user, "admin", False) is True
    except (TypeError, KeyError):
        return False


async def _notify_ugc_video_saved(
    creator: UserEntity | None,
    advertiser: UserEntity | None,
    video_url: str,
    messenger_client: Any,
    bot_texts_service: Any,
) -> None:
    """Send first-save notifications to creator and advertiser.

    Called only when ugc_video_url was previously None.
    Silently skips a recipient when their User record is None.
    """
    if creator is not None and creator.telegram_id:
        locale = creator.language or "ru"
        text = await bot_texts_service.get(
            "msg_ugc_video_saved_creator", locale
        )
        await send_with_retry(
            messenger_client,
            chat_id=creator.telegram_id,
            text=text,
            retries=3,
            delay_seconds=1.0,
            logger=logger,
            extra={"event": "ugc_video_saved_creator"},
        )
    if advertiser is not None and advertiser.telegram_id:
        locale = advertiser.language or "ru"
        template = await bot_texts_service.get(
            "msg_ugc_video_saved_advertiser", locale
        )
        creator_handle = (
            f"@{creator.telegram}"
            if creator is not None and creator.telegram
            else (
                f"tg://user?id={creator.telegram_id}"
                if creator is not None
                else "—"
            )
        )
        text = template.format(telegram=creator_handle, url=video_url)
        await send_with_retry(
            messenger_client,
            chat_id=advertiser.telegram_id,
            text=text,
            retries=3,
            delay_seconds=1.0,
            logger=logger,
            extra={"event": "ugc_video_saved_advertiser"},
        )


def _blogger_profile_to_dict(blogger, user) -> dict | None:
    """Build blogger pre-fill dict for frontend."""
    if blogger is None:
        return None
    birth = blogger.birth_date
    birth_str = None
    if isinstance(birth, date):
        birth_str = f"{birth.day:02d}.{birth.month:02d}.{birth.year}"
    topics = blogger.topics.get("selected", []) if blogger.topics else []
    return {
        "display_name": getattr(user, "username", None) or "",
        "instagram_url": blogger.instagram_url,
        "confirmed": getattr(blogger, "confirmed", False),
        "birth_date": birth_str,
        "topics": topics,
        "city": blogger.city,
        "audience_geo": blogger.audience_geo,
        "audience_age_min": blogger.audience_age_min,
        "audience_age_max": blogger.audience_age_max,
        "audience_gender": blogger.audience_gender.value,
        "price": blogger.price,
        "barter": blogger.barter,
        "work_format": blogger.work_format.value,
        "blogger_gender": (blogger.blogger_gender or BloggerGender.MALE).value,
    }


@router.post("/me", response_model=MeResponse)
async def me(request: Request, body: InitDataBody) -> MeResponse:
    """Return current user, profile flags and profile data for pre-fill."""
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
    adv_profile: dict | None = None
    if advertiser is not None:
        adv_profile = {
            "phone": advertiser.phone,
            "brand": advertiser.brand,
            "site_link": advertiser.site_link or "",
            "city": advertiser.city or "",
            "company_activity": advertiser.company_activity or "",
            "display_name": getattr(user, "username", None) or "",
        }
    blg_profile = _blogger_profile_to_dict(blogger, user)
    # Resolve currency from country
    user_country = getattr(user, "country", None)
    currency_code: str | None = None
    currency_symbol: str | None = None
    country_repo = dispatcher.get("country_repo")
    if user_country and country_repo:
        country_obj = await country_repo.get_by_code(user_country)
        if country_obj:
            currency_code = country_obj.currency_code
            currency_symbol = country_obj.currency_symbol
    config = request.app.state.config
    user_locale: str = (
        getattr(user, "language", None) or config.market.default_locale
    )
    # Resolve manager status — admins always see the manager view
    is_manager = False
    if getattr(user, "admin", False):
        is_manager = True
    else:
        manager_service = dispatcher.get("manager_service")
        if manager_service:
            is_manager = await manager_service.is_manager(user_id)
    return MeResponse(
        user_id=str(user_id),
        external_id=user.telegram_id or user.max_id or "",
        role=role,
        has_advertiser_profile=advertiser is not None,
        has_blogger_profile=blogger is not None,
        advertiser_profile=adv_profile,
        blogger_profile=blg_profile,
        country=user_country,
        currency_code=currency_code,
        currency_symbol=currency_symbol,
        locale=user_locale,
        is_manager=is_manager,
    )


@router.post("/config", response_model=ConfigResponse)
async def config(request: Request, body: InitDataBody) -> ConfigResponse:
    """Return miniapp config: counts, content usage, bot username, doc URLs."""
    _ = await _ensure_user_and_get_id(request, body.init_data)
    cfg = request.app.state.config
    counts = sorted(cfg.order.get_allowed_blogger_counts_set())
    options = [
        {"value": val, "label": label} for val, label in CONTENT_USAGE_OPTIONS
    ]
    bot_username = (cfg.bot.bot_username or "").strip().lstrip("@")
    docs = getattr(cfg, "docs", None)
    docs_offer_url = (docs.docs_offer_url or "").strip() if docs else ""
    docs_privacy_url = (docs.docs_privacy_url or "").strip() if docs else ""
    docs_consent_url = (docs.docs_consent_url or "").strip() if docs else ""
    docs_offer_url_intl = (
        (docs.docs_offer_url_intl or "").strip() if docs else ""
    )
    docs_privacy_url_intl = (
        (docs.docs_privacy_url_intl or "").strip() if docs else ""
    )
    docs_consent_url_intl = (
        (docs.docs_consent_url_intl or "").strip() if docs else ""
    )
    instagram_cfg = getattr(cfg, "instagram", None)
    admin_instagram_username = (
        (instagram_cfg.admin_instagram_username or "").strip().lstrip("@")
        if instagram_cfg
        else ""
    )
    dispatcher = request.app.state.dispatcher
    country_repo = dispatcher.get("country_repo")
    countries_list: list[dict[str, str]] = []
    if country_repo:
        enabled = await country_repo.list_enabled()
        countries_list = [
            {
                "code": c.code,
                "name_native": c.name_native,
                "currency_code": c.currency_code,
                "currency_symbol": c.currency_symbol,
            }
            for c in enabled
        ]
    return ConfigResponse(
        allowed_blogger_counts=counts,
        content_usage_options=options,
        bot_username=bot_username,
        docs_offer_url=docs_offer_url,
        docs_privacy_url=docs_privacy_url,
        docs_consent_url=docs_consent_url,
        docs_offer_url_intl=docs_offer_url_intl,
        docs_privacy_url_intl=docs_privacy_url_intl,
        docs_consent_url_intl=docs_consent_url_intl,
        admin_instagram_username=admin_instagram_username,
        countries=countries_list,
    )


@router.get("/cities")
async def cities() -> list[dict[str, str]]:
    """Return cities list for city picker mini app (id, label per item)."""
    return get_cities_list_for_miniapp()


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
    """Save advertiser profile; return needs_agreement (confirm docs in UI)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    telegram_username = _get_telegram_username_from_init_data(
        request, body.init_data
    )
    external_id = _get_telegram_user_id(request, body.init_data)
    locale = await _get_user_locale(request, external_id)
    texts = await _get_validator_texts(request, locale)
    err = _validate_advertiser_body(body, texts)
    if err:
        raise HTTPException(status_code=400, detail=err)
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["advertiser_registration_service"]
    try:
        profile = await svc.save_advertiser_before_agreement(
            user_id=user_id,
            phone=body.phone,
            brand=body.brand,
            site_link=body.site_link,
            city=body.city,
            company_activity=body.company_activity,
            display_name=body.display_name,
            telegram_username=telegram_username,
        )
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AdvertiserRegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "ok": True,
        "user_id": str(profile.user_id),
        "needs_agreement": True,
    }


@router.post("/register/advertiser/confirm-agreement")
async def confirm_advertiser_agreement_endpoint(
    request: Request, body: InitDataBody
) -> dict:
    """Confirm advertiser agreement with platform documents."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["advertiser_registration_service"]
    try:
        await svc.confirm_advertiser_agreement(user_id=user_id)
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}


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
    err = validate_nickname(body.display_name or "", texts=texts)
    if err:
        return err
    if (body.birth_date or "").strip():
        _, err = validate_birth_date(
            (body.birth_date or "").strip(), texts=texts
        )
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


async def _blogger_register_update(
    svc: BloggerRegistrationService,
    user_id: UUID,
    body: RegisterBloggerRequest,
    instagram_url: str,
    birth_date_val: date | None,
    work_format: WorkFormat,
    audience_gender: AudienceGender,
    blogger_gender: BloggerGender,
    topics_dict: dict,
    location_geometry: str | None = None,
) -> dict:
    """Update existing blogger profile. Raises HTTPException on error."""
    result = await svc.update_blogger_profile(
        user_id,
        instagram_url=instagram_url,
        city=body.city,
        region=body.region,
        country=body.country,
        topics=topics_dict,
        audience_gender=audience_gender,
        audience_age_min=body.audience_age_min,
        audience_age_max=body.audience_age_max,
        audience_geo=body.audience_geo,
        price=body.price,
        barter=body.barter,
        work_format=work_format,
        blogger_gender=blogger_gender,
        birth_date=birth_date_val,
        location_geometry=location_geometry,
    )
    if result.profile is None and not result.location_geometry_resolved:
        raise HTTPException(
            status_code=400,
            detail="City could not be resolved. Try another city.",
        )
    return {"ok": True, "user_id": str(user_id)}


async def _blogger_register_create(
    svc: BloggerRegistrationService,
    user_id: UUID,
    body: RegisterBloggerRequest,
    instagram_url: str,
    birth_date_val: date | None,
    work_format: WorkFormat,
    audience_gender: AudienceGender,
    blogger_gender: BloggerGender,
    topics_dict: dict,
    location_geometry: str | None = None,
    telegram_username: str | None = None,
) -> dict:
    """Save new blogger before agreement; client calls confirm-agreement."""
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
        telegram_username=telegram_username,
        birth_date=birth_date_val,
        region=body.region,
        country=body.country,
        location_geometry=location_geometry,
    )
    return {"ok": True, "user_id": str(user_id), "needs_agreement": True}


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
    external_id = _get_telegram_user_id(request, body.init_data)
    locale = await _get_user_locale(request, external_id)
    texts = await _get_validator_texts(request, locale)
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
    if existing is None and not (body.birth_date or "").strip():
        detail = (texts or {}).get(
            "err_birth_date_empty",
            "Enter date of birth as DD.MM.YYYY (e.g. 15.05.1995).",
        )
        raise HTTPException(status_code=400, detail=detail)
    if existing is not None and existing.user_id != user_id:
        taken = (texts or {}).get(
            "err_instagram_taken",
            "This Instagram is already registered. Use another one.",
        )
        raise HTTPException(status_code=400, detail=taken)
    birth_date_val = _parse_birth_date_optional(body.birth_date, texts)
    work_format = _parse_work_format(body.work_format)
    audience_gender = _parse_audience_gender(body.audience_gender)
    blogger_gender = _parse_blogger_gender(body.blogger_gender)
    topics_dict = {"selected": body.topics}
    location_geometry = _location_geometry_from_blogger_request(body)
    telegram_username = (
        body.telegram_username
        or _get_telegram_username_from_init_data(request, body.init_data)
    )
    if existing is not None and existing.user_id == user_id:
        try:
            return await _blogger_register_update(
                svc,
                user_id,
                body,
                instagram_url,
                birth_date_val,
                work_format,
                audience_gender,
                blogger_gender,
                topics_dict,
                location_geometry=location_geometry,
            )
        except UserNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except BloggerRegistrationError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    try:
        return await _blogger_register_create(
            svc,
            user_id,
            body,
            instagram_url,
            birth_date_val,
            work_format,
            audience_gender,
            blogger_gender,
            topics_dict,
            location_geometry=location_geometry,
            telegram_username=telegram_username,
        )
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except BloggerRegistrationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/register/blogger/confirm-agreement")
async def confirm_blogger_agreement_endpoint(
    request: Request, body: InitDataBody
) -> dict:
    """Confirm blogger agreement with platform documents."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["blogger_registration_service"]
    try:
        await svc.confirm_blogger_agreement(user_id=user_id)
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}


def _format_instagram_verification_instruction(
    template: str, admin_username: str
) -> str:
    """Format verification instruction with Instagram URL for miniapp."""
    base = "https://www.instagram.com/"
    username = (admin_username or "usemycontent").strip().lstrip("@")
    url = f"{base}{username}/"
    return template.replace("{url}", url)


@router.post("/blogger/instagram-verification/start")
async def start_instagram_verification(
    request: Request, body: InitDataBody
) -> dict:
    """Start Instagram verification: return code and instruction (like bot)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    profile_service = dispatcher["profile_service"]
    blogger = await profile_service.get_blogger_profile(user_id)
    if blogger is None:
        raise HTTPException(
            status_code=404, detail="Blogger profile not found."
        )
    if getattr(blogger, "confirmed", False):
        return {"already_confirmed": True}
    verification_service = dispatcher["instagram_verification_service"]
    bot_texts = dispatcher["bot_texts_service"]
    config = request.app.state.config
    verification = await verification_service.generate_code(user_id)
    external_id = _get_telegram_user_id(request, body.init_data)
    locale = await _get_user_locale(request, external_id)
    instruction_tpl = await bot_texts.get(
        "msg_instagram_verify_instruction", locale
    )
    instagram_cfg = getattr(config, "instagram", None)
    admin_username = (
        getattr(instagram_cfg, "admin_instagram_username", None) or ""
        if instagram_cfg
        else ""
    )
    instruction = _format_instagram_verification_instruction(
        instruction_tpl, admin_username
    )
    base_url = "https://www.instagram.com/"
    username = (admin_username or "usemycontent").strip().lstrip("@")
    instagram_url = f"{base_url}{username}/"
    return {
        "code": verification.code,
        "instruction": instruction,
        "instagram_url": instagram_url,
    }


def _parse_birth_date_optional(
    birth_date_str: str | None, texts: dict[str, str]
) -> date | None:
    """Parse birth_date DD.MM.YYYY. None if empty; raise 400 if invalid."""
    if not (birth_date_str or "").strip():
        return None
    parsed, err = validate_birth_date(
        (birth_date_str or "").strip(), texts=texts
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    return parsed


def _parse_order_type(s: str) -> OrderType:
    try:
        return OrderType(s)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"order_type must be one of: {[e.value for e in OrderType]}",
        ) from None


def _validate_order_body(
    body: CreateOrderRequest | UpdateOrderRequest,
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
    external_id = _get_telegram_user_id(request, body.init_data)
    locale = await _get_user_locale(request, external_id)
    texts = await _get_validator_texts(request, locale)
    config = request.app.state.config
    err = _validate_order_body(
        body,
        texts,
        config.order.max_order_price,
        config.market.currency_symbol,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    config = request.app.state.config
    allowed = config.order.get_allowed_blogger_counts_set()
    if body.bloggers_needed not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"bloggers_needed must be one of: {sorted(allowed)}",
        )
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

    try:
        messenger_client = dispatcher["messenger_client"]
        user_role_service = dispatcher["user_role_service"]
        content_moderation_service = dispatcher["content_moderation_service"]
        logger.info(
            "Sending admin notification for miniapp order",
            extra={"order_id": str(order.order_id)},
        )
        country_repo = dispatcher.get("country_repo")
        await notify_admins_about_order_created(
            order=order,
            messenger_client=messenger_client,
            user_role_service=user_role_service,
            content_moderation=content_moderation_service,
            admin_base_url=config.admin.admin_base_url,
            currency_symbol=config.market.currency_symbol,
            country_repo=country_repo,
        )
        support_chat_id = config.referral.referral_support_chat_id
        if support_chat_id.strip():
            advertiser_user = await user_role_service.get_user_by_id(user_id)
            if advertiser_user:
                await notify_support_chat_about_new_order(
                    order=order,
                    advertiser_user=advertiser_user,
                    advertiser_profile=advertiser,
                    messenger_client=messenger_client,
                    support_chat_id=support_chat_id,
                    admin_base_url=config.admin.admin_base_url,
                    currency_symbol=config.market.currency_symbol,
                    country_repo=country_repo,
                )
    except Exception as exc:
        logger.error(
            "Failed to send notifications for miniapp order",
            extra={
                "order_id": str(order.order_id),
                "error": str(exc),
            },
        )

    payment_link = _payment_link_for_order(
        str(order.order_id), config.bot.bot_username
    )
    return {
        "ok": True,
        "order_id": str(order.order_id),
        "status": order.status.value,
        "payment_link": payment_link,
    }


class OrdersListRequest(BaseModel):
    """Request body for listing orders."""

    init_data: str
    platform: str = "telegram"


class ReverseGeocodeRequest(BaseModel):
    """Request body for reverse geocode (coordinates to city)."""

    init_data: str
    platform: str = "telegram"
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class ReverseGeocodeResponse(BaseModel):
    """Reverse geocode result: city, region, country."""

    city: str
    region: str | None = None
    country: str | None = None


class ForwardGeocodeRequest(BaseModel):
    """Request body for forward geocode (city name to coordinates)."""

    init_data: str
    platform: str = "telegram"
    city: str
    region: str | None = None
    country: str | None = None


class ForwardGeocodePublicRequest(BaseModel):
    """Public forward geocode request (no auth, e.g. when opened in browser)."""

    city: str
    region: str | None = None
    country: str | None = None


class ForwardGeocodeResponse(BaseModel):
    """Forward geocode result: lat, lon, city, region, country."""

    lat: float
    lon: float
    city: str
    region: str | None = None
    country: str | None = None


@router.post("/geocode/reverse", response_model=ReverseGeocodeResponse)
async def reverse_geocode(
    request: Request, body: ReverseGeocodeRequest
) -> ReverseGeocodeResponse:
    """Reverse geocode (lat, lon) to city, region, country for map picker.

    Nominatim responses are cached via CachingGeocoder when
    GEOCODER_CACHE_ENABLED is true (default); repeated requests for the same
    coordinates use the cache.
    """
    await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["blogger_registration_service"]
    result = await svc.resolve_city_from_location(body.lat, body.lon)
    if result is None:
        raise HTTPException(
            status_code=404, detail="Location could not be resolved to a city."
        )
    city, region, country = result
    return ReverseGeocodeResponse(city=city, region=region, country=country)


@router.post("/geocode/forward", response_model=ForwardGeocodeResponse)
async def forward_geocode(
    request: Request, body: ForwardGeocodeRequest
) -> ForwardGeocodeResponse:
    """Geocode city name to coordinates for map search.

    Nominatim responses are cached via CachingGeocoder when
    GEOCODER_CACHE_ENABLED is true (default); repeated requests for the same
    city/region/country use the cache.
    """
    await _ensure_user_and_get_id(request, body.init_data)
    if not (body.city or "").strip():
        raise HTTPException(status_code=400, detail="city is required")
    dispatcher = request.app.state.dispatcher
    svc = dispatcher["blogger_registration_service"]
    result = await svc.resolve_city_to_coordinates(
        body.city.strip(),
        region=body.region or None,
        country=body.country or None,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="City could not be found.",
        )
    lat, lon, region, country = result
    return ForwardGeocodeResponse(
        lat=lat,
        lon=lon,
        city=body.city.strip(),
        region=region,
        country=country,
    )


@router.post("/geocode/forward/public", response_model=ForwardGeocodeResponse)
async def forward_geocode_public(
    request: Request, body: ForwardGeocodePublicRequest
) -> ForwardGeocodeResponse:
    """Geocode city name without auth (e.g. mini app opened in browser).

    Same geocoder as /geocode/forward; search works when initData is missing.
    Rate-limited: 30 requests per minute per IP.
    """
    if not (body.city or "").strip():
        raise HTTPException(status_code=400, detail="city is required")
    dispatcher = request.app.state.dispatcher
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[
        0
    ].strip() or (request.client.host if request.client else "unknown")
    rate_limiter = dispatcher["geocode_public_rate_limiter"]
    if not await rate_limiter.allow_async(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests")
    svc = dispatcher["blogger_registration_service"]
    result = await svc.resolve_city_to_coordinates(
        body.city.strip(),
        region=body.region or None,
        country=body.country or None,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="City could not be found.",
        )
    lat, lon, region, country = result
    return ForwardGeocodeResponse(
        lat=lat,
        lon=lon,
        city=body.city.strip(),
        region=region,
        country=country,
    )


@router.post("/orders/list", response_model=OrdersListResponse)
async def list_orders(
    request: Request, body: OrdersListRequest
) -> OrdersListResponse:
    """List orders for the current advertiser."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    order_service = dispatcher["order_service"]
    orders = await order_service.list_by_advertiser(user_id)
    cfg = request.app.state.config
    bot_username = (cfg.bot.bot_username or "").strip().lstrip("@")
    cur_map = await _currency_symbol_map(request)
    items = [
        OrderListItem(
            order_id=str(o.order_id),
            status=o.status.value,
            product_link=o.product_link,
            price=float(o.price),
            order_type=o.order_type.value,
            created_at=o.created_at.isoformat(),
            payment_link=_payment_link_for_order(str(o.order_id), bot_username)
            if o.status == OrderStatus.NEW
            else "",
            currency_symbol=cur_map.get(o.currency, "₽"),
        )
        for o in orders
    ]
    return OrdersListResponse(orders=items)


@router.post("/orders/list/creator", response_model=OrdersListResponse)
async def list_creator_orders(
    request: Request, body: OrdersListRequest
) -> OrdersListResponse:
    """List orders the current user (creator/blogger) has responded to."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    order_service = dispatcher["order_service"]
    offer_response_service = dispatcher["offer_response_service"]
    responses = await offer_response_service.list_by_blogger(
        user_id, in_offer_only=True
    )
    cur_map = await _currency_symbol_map(request)
    items: list[OrderListItem] = []
    seen_order_ids: set[UUID] = set()
    for resp in sorted(
        responses,
        key=lambda r: (r.updated_at or r.created_at, r.created_at),
        reverse=True,
    ):
        if resp.order_id in seen_order_ids:
            continue
        seen_order_ids.add(resp.order_id)
        order = await order_service.get_order(resp.order_id)
        if order is None:
            continue
        items.append(
            OrderListItem(
                order_id=str(order.order_id),
                status=order.status.value,
                product_link=order.product_link,
                price=float(order.price),
                order_type=order.order_type.value,
                created_at=order.created_at.isoformat(),
                payment_link="",
                currency_symbol=cur_map.get(order.currency, "₽"),
            )
        )
    return OrdersListResponse(orders=items)


@router.post("/orders/get", response_model=OrderDetailResponse)
async def get_order(
    request: Request, body: GetOrderRequest
) -> OrderDetailResponse:
    """Get one order by id (advertiser must own it)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    try:
        order_id = UUID(body.order_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid order_id"
        ) from None
    dispatcher = request.app.state.dispatcher
    order_service = dispatcher["order_service"]
    order = await order_service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.advertiser_id != user_id:
        raise HTTPException(status_code=404, detail="Order not found")
    cfg = request.app.state.config
    payment_link = (
        _payment_link_for_order(str(order.order_id), cfg.bot.bot_username)
        if order.status == OrderStatus.NEW
        else ""
    )
    return OrderDetailResponse(
        order_id=str(order.order_id),
        status=order.status.value,
        product_link=order.product_link,
        offer_text=order.offer_text,
        price=float(order.price),
        bloggers_needed=order.bloggers_needed,
        order_type=order.order_type.value,
        barter_description=order.barter_description,
        content_usage=order.content_usage,
        deadlines=order.deadlines,
        geography=order.geography,
        created_at=order.created_at.isoformat(),
        payment_link=payment_link,
    )


@router.post("/orders/update")
async def update_order(request: Request, body: UpdateOrderRequest) -> dict:
    """Update order (advertiser only, same validation as create)."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    profile_service = request.app.state.dispatcher["profile_service"]
    advertiser = await profile_service.get_advertiser_profile(user_id)
    if advertiser is None:
        raise HTTPException(
            status_code=403,
            detail="Advertiser profile required.",
        )
    try:
        order_id = UUID(body.order_id)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid order_id"
        ) from None
    external_id = _get_telegram_user_id(request, body.init_data)
    locale = await _get_user_locale(request, external_id)
    texts = await _get_validator_texts(request, locale)
    config = request.app.state.config
    err = _validate_order_body(
        body,
        texts,
        config.order.max_order_price,
        config.market.currency_symbol,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)
    allowed = config.order.get_allowed_blogger_counts_set()
    if body.bloggers_needed not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"bloggers_needed must be one of: {sorted(allowed)}",
        )
    order_service = request.app.state.dispatcher["order_service"]
    order_type = _parse_order_type(body.order_type)
    try:
        order = await order_service.update_order(
            order_id=order_id,
            advertiser_id=user_id,
            product_link=body.product_link,
            offer_text=body.offer_text,
            barter_description=body.barter_description,
            price=body.price,
            bloggers_needed=body.bloggers_needed,
            order_type=order_type,
            content_usage=body.content_usage,
            deadlines=body.deadlines,
            geography=body.geography,
        )
    except OrderNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OrderCreationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    payment_link = _payment_link_for_order(
        str(order.order_id), config.bot.bot_username
    )
    return {
        "ok": True,
        "order_id": str(order.order_id),
        "status": order.status.value,
        "payment_link": payment_link,
    }


class SetCountryRequest(BaseModel):
    """Request to set country for the current user."""

    init_data: str
    platform: str = "telegram"
    country_code: str


@router.post("/set-country")
async def set_country(request: Request, body: SetCountryRequest) -> dict:
    """Save user's country; return ok with currency info."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    country_repo = dispatcher.get("country_repo")
    if country_repo:
        country_obj = await country_repo.get_by_code(body.country_code)
        if country_obj is None:
            raise HTTPException(status_code=400, detail="Unknown country code.")
        currency_code = country_obj.currency_code
        currency_symbol = country_obj.currency_symbol
    else:
        currency_code = "RUB"
        currency_symbol = "₽"
    external_id = _get_telegram_user_id(request, body.init_data)
    user_role_service = dispatcher["user_role_service"]
    await user_role_service.set_country(
        external_id=external_id,
        messenger_type=MessengerType.TELEGRAM,
        country_code=body.country_code,
    )
    _ = user_id  # already used to ensure user exists
    return {
        "ok": True,
        "currency_code": currency_code,
        "currency_symbol": currency_symbol,
    }


@router.post("/manager/orders", response_model=ManagerOrdersResponse)
async def manager_orders(
    request: Request, body: ManagerOrdersRequest
) -> ManagerOrdersResponse:
    """List orders assigned to the current manager."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]
    if await _is_user_admin(dispatcher, user_id):
        orders, total = await manager_service.list_all_orders(
            limit=body.limit, offset=body.offset
        )
    else:
        orders, total = await manager_service.list_orders_for_manager(
            user_id, limit=body.limit, offset=body.offset
        )
    cfg = request.app.state.config
    bot_username = (cfg.bot.bot_username or "").strip().lstrip("@")
    cur_map = await _currency_symbol_map(request)
    items = [
        OrderListItem(
            order_id=str(o.order_id),
            status=o.status.value,
            product_link=o.product_link,
            price=float(o.price),
            order_type=o.order_type.value,
            created_at=o.created_at.isoformat(),
            payment_link=_payment_link_for_order(str(o.order_id), bot_username)
            if o.status == OrderStatus.NEW
            else "",
            currency_symbol=cur_map.get(o.currency, "₽"),
        )
        for o in orders
    ]
    return ManagerOrdersResponse(orders=items, total=total)


@router.post(
    "/manager/orders/{order_id}/creators",
    response_model=ManagerCreatorsResponse,
)
async def manager_creators(
    request: Request, order_id: UUID, body: ManagerCreatorsRequest
) -> ManagerCreatorsResponse:
    """List creators for an order assigned to the current manager."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]
    profile_service = dispatcher["profile_service"]

    is_admin = await _is_user_admin(dispatcher, user_id)
    if not is_admin and not await manager_service.is_manager_for_order(
        user_id, order_id
    ):
        raise HTTPException(
            status_code=403, detail="Not a manager for this order"
        )

    # Resolve filter: new 'filter' field takes priority, fallback to 'in_offer'
    effective_filter = body.filter
    if effective_filter is None:
        if body.in_offer is not None:
            effective_filter = "in_offer" if body.in_offer else "reserve"
        else:
            effective_filter = "in_offer"

    search_q = body.search.strip().lower() if body.search else ""

    # When searching, fetch all results and filter/paginate in Python
    fetch_limit = 500 if search_q else body.limit
    fetch_offset = 0 if search_q else body.offset

    # Admins see all creators regardless of manager assignment
    effective_manager_id = None if is_admin else user_id

    if effective_filter == "expensive":
        dispatches, total = await manager_service.list_expensive_creators(
            order_id=order_id,
            limit=fetch_limit,
            offset=fetch_offset,
        )
    else:
        dispatches, total = await manager_service.list_creators_for_order(
            order_id=order_id,
            manager_id=effective_manager_id,
            in_offer=effective_filter == "in_offer",
            limit=fetch_limit,
            offset=fetch_offset,
        )

    user_repo = dispatcher["user_repo"]
    blogger_ids = [d.blogger_id for d in dispatches]
    users_map = await user_repo.get_by_ids(blogger_ids)
    profiles_map = await profile_service.get_blogger_profiles(blogger_ids)

    all_creators: list[CreatorItem] = []
    dispatches_map = {d.blogger_id: d for d in dispatches}
    for bid in blogger_ids:
        d = dispatches_map[bid]
        user = users_map.get(bid)
        profile = profiles_map.get(bid)
        name = user.username if user else None
        tg = user.telegram if user else None
        if search_q:
            haystack = " ".join(s for s in [name, tg] if s).lower()
            if search_q not in haystack:
                continue
        price = float(d.desired_price) if d.desired_price is not None else None
        all_creators.append(
            CreatorItem(
                blogger_id=str(bid),
                instagram_url=(profile.instagram_url if profile else None),
                telegram=tg,
                name=name,
                desired_price=price,
            )
        )

    if search_q:
        total = len(all_creators)
        creators = all_creators[body.offset : body.offset + body.limit]
    else:
        creators = all_creators

    return ManagerCreatorsResponse(creators=creators, total=total)


@router.post("/manager/orders/{order_id}/creators/{blogger_id}")
async def manager_creator_detail(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: CreatorDetailRequest,
) -> CreatorDetailResponse:
    """Return creator profile and current ugc_video_url for manager."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await _is_user_admin(
        dispatcher, user_id
    ) and not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(
            status_code=403, detail="Not a manager for this order"
        )

    dispatch_repo = dispatcher["offer_dispatch_repo"]
    dispatch = await dispatch_repo.get_by_order_and_blogger(
        order_id, blogger_id
    )
    if dispatch is None:
        raise HTTPException(
            status_code=404, detail="Creator not found in this order"
        )

    profile_service = dispatcher["profile_service"]
    user_repo = dispatcher["user_repo"]
    user = await user_repo.get_by_id(blogger_id)
    profile = await profile_service.get_blogger_profile(blogger_id)

    return CreatorDetailResponse(
        blogger_id=str(blogger_id),
        instagram_url=profile.instagram_url if profile else None,
        telegram=user.telegram if user else None,
        ugc_video_url=dispatch.ugc_video_url,
        in_offer=dispatch.in_offer,
    )


@router.post("/manager/orders/{order_id}/creators/{blogger_id}/ugc-video")
async def manager_set_ugc_video(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: UgcVideoRequest,
) -> dict[str, Any]:
    """Save UGC video URL; on first save notifies creator and advertiser."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await _is_user_admin(
        dispatcher, user_id
    ) and not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(
            status_code=403, detail="Not a manager for this order"
        )

    order_repo = dispatcher["order_repo"]
    order = await order_repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    dispatch_repo = dispatcher["offer_dispatch_repo"]
    dispatch = await dispatch_repo.get_by_order_and_blogger(
        order_id, blogger_id
    )
    if dispatch is None:
        raise HTTPException(
            status_code=404, detail="Creator not found in this order"
        )

    previous_url = dispatch.ugc_video_url
    url_str = str(body.url)
    await dispatch_repo.set_ugc_video_url(order_id, blogger_id, url_str)

    if previous_url is None:
        user_repo = dispatcher["user_repo"]
        messenger_client = dispatcher["messenger_client"]
        bot_texts_service = dispatcher["bot_texts_service"]
        creator = await user_repo.get_by_id(blogger_id)
        advertiser = await user_repo.get_by_id(order.advertiser_id)
        await _notify_ugc_video_saved(
            creator=creator,
            advertiser=advertiser,
            video_url=url_str,
            messenger_client=messenger_client,
            bot_texts_service=bot_texts_service,
        )

    interaction_service = dispatcher["interaction_service"]
    interaction = await interaction_service.get_or_create(
        order_id, blogger_id, order.advertiser_id
    )

    return {
        "ok": True,
        "interaction_id": str(interaction.interaction_id),
    }


@router.post("/manager/orders/{order_id}/creators/{blogger_id}/remove")
async def manager_remove_creator(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: InitDataBody,
) -> dict[str, Any]:
    """Move creator to reserve; notify creator. Returns interaction_id."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await _is_user_admin(
        dispatcher, user_id
    ) and not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(
            status_code=403, detail="Not a manager for this order"
        )

    order_repo = dispatcher["order_repo"]
    order = await order_repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    dispatch_repo = dispatcher["offer_dispatch_repo"]
    dispatch = await dispatch_repo.get_by_order_and_blogger(
        order_id, blogger_id
    )
    if dispatch is None:
        raise HTTPException(
            status_code=404, detail="Creator not found in this order"
        )
    if not dispatch.in_offer:
        raise HTTPException(
            status_code=409, detail="Creator is already in reserve"
        )

    await dispatch_repo.set_in_offer(order_id, blogger_id, False)

    interaction_service = dispatcher["interaction_service"]
    interaction = await interaction_service.get_or_create(
        order_id, blogger_id, order.advertiser_id
    )
    # Set default NO_DEAL status; frontend may overwrite with
    # a more specific reason via the /feedback endpoint afterward.
    await interaction_service.record_advertiser_feedback(
        interaction.interaction_id, "❌ Не договорились"
    )

    user_repo = dispatcher["user_repo"]
    creator: UserEntity | None = await user_repo.get_by_id(blogger_id)
    if creator is not None and creator.telegram_id:
        locale = creator.language or "ru"
        bot_texts_service = dispatcher["bot_texts_service"]
        text = await bot_texts_service.get(
            "msg_creator_removed_from_order", locale
        )
        messenger_client = dispatcher["messenger_client"]
        await send_with_retry(
            messenger_client,
            chat_id=creator.telegram_id,
            text=text,
            retries=3,
            delay_seconds=1.0,
            logger=logger,
            extra={"event": "creator_removed_from_order"},
        )
    else:
        logger.warning(
            "Creator not found for removal notification",
            extra={"blogger_id": str(blogger_id)},
        )

    return {
        "ok": True,
        "interaction_id": str(interaction.interaction_id),
    }


@router.post("/manager/orders/{order_id}/creators/{blogger_id}/add")
async def manager_add_creator(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: InitDataBody,
) -> dict[str, bool]:
    """Add reserve creator to active order; create Interaction; notify."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await _is_user_admin(
        dispatcher, user_id
    ) and not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(
            status_code=403, detail="Not a manager for this order"
        )

    order_repo = dispatcher["order_repo"]
    order = await order_repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    dispatch_repo = dispatcher["offer_dispatch_repo"]
    dispatch = await dispatch_repo.get_by_order_and_blogger(
        order_id, blogger_id
    )
    if dispatch is None:
        raise HTTPException(
            status_code=404, detail="Creator not found in this order"
        )
    if dispatch.in_offer:
        raise HTTPException(
            status_code=409, detail="Creator is already in the order"
        )

    in_offer_count = await dispatch_repo.count_accepted_by_order(order_id)
    if in_offer_count >= order.bloggers_needed:
        raise HTTPException(
            status_code=409, detail="No free slots in this order"
        )

    await dispatch_repo.set_in_offer(order_id, blogger_id, True)
    await dispatch_repo.set_manager(order_id, blogger_id, user_id)

    interaction_service = dispatcher["interaction_service"]
    await interaction_service.reactivate_or_create_for_contacts_sent(
        order_id, blogger_id, order.advertiser_id
    )

    user_repo = dispatcher["user_repo"]
    creator: UserEntity | None = await user_repo.get_by_id(blogger_id)
    if creator is not None and creator.telegram_id:
        manager: UserEntity | None = None
        if dispatch.manager_id is not None:
            manager = await user_repo.get_by_id(dispatch.manager_id)
        manager_telegram = (
            f"@{manager.telegram}"
            if manager is not None and manager.telegram
            else (
                f"tg://user?id={manager.telegram_id}"
                if manager is not None
                else "—"
            )
        )
        locale = creator.language or "ru"
        bot_texts_service = dispatcher["bot_texts_service"]
        template = await bot_texts_service.get(
            "msg_creator_added_to_order", locale
        )
        text = template.format(manager_telegram=manager_telegram)
        messenger_client = dispatcher["messenger_client"]
        await send_with_retry(
            messenger_client,
            chat_id=creator.telegram_id,
            text=text,
            retries=3,
            delay_seconds=1.0,
            logger=logger,
            extra={"event": "creator_added_to_order"},
        )
    else:
        logger.warning(
            "Creator not found for add notification",
            extra={"blogger_id": str(blogger_id)},
        )

    return {"ok": True}


@router.post("/manager/orders/{order_id}/creators/{blogger_id}/feedback")
async def manager_feedback(
    request: Request,
    order_id: UUID,
    blogger_id: UUID,
    body: ManagerFeedbackRequest,
) -> dict[str, Any]:
    """Record advertiser-side feedback from manager on an interaction."""
    user_id = await _ensure_user_and_get_id(request, body.init_data)
    dispatcher = request.app.state.dispatcher
    manager_service = dispatcher["manager_service"]

    if not await _is_user_admin(
        dispatcher, user_id
    ) and not await manager_service.is_manager_for_order(user_id, order_id):
        raise HTTPException(
            status_code=403, detail="Not a manager for this order"
        )

    order_repo = dispatcher["order_repo"]
    order = await order_repo.get_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    interaction_service = dispatcher["interaction_service"]
    interaction = await interaction_service.get_or_create(
        order_id, blogger_id, order.advertiser_id
    )

    if body.status == "ok":
        feedback_text = "✅ Всё прошло хорошо"
    elif body.status == "no_deal":
        reason = body.no_deal_reason.strip() if body.no_deal_reason else ""
        feedback_text = (
            f"❌ Не договорились: {reason}" if reason else "❌ Не договорились"
        )
    else:
        # status == "issue"
        if not body.issue_description or not body.issue_description.strip():
            raise HTTPException(
                status_code=422,
                detail="issue_description is required for issue status",
            )
        feedback_text = "⚠️ Проблема/мошенничество"

        complaint_service = dispatcher["complaint_service"]
        complaint = await complaint_service.create_complaint(
            reporter_id=user_id,
            reported_id=blogger_id,
            order_id=order_id,
            reason=body.issue_description.strip(),
        )

        user_role_service = dispatcher["user_role_service"]
        messenger_client = dispatcher["messenger_client"]
        try:
            await notify_admins_about_complaint(
                complaint=complaint,
                messenger_client=messenger_client,
                user_role_service=user_role_service,
            )
        except Exception:
            logger.exception(
                "Failed to notify admins about complaint",
                extra={
                    "order_id": str(order_id),
                    "blogger_id": str(blogger_id),
                },
            )

    updated = await interaction_service.record_advertiser_feedback(
        interaction.interaction_id, feedback_text
    )
    return {"ok": True, "interaction_id": str(updated.interaction_id)}
