"""Order editor sections, input guidance and saved-field validation."""

from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ugc_bot.application.geography import has_unspecified_geography
from ugc_bot.domain.enums import BloggerGender, OrderType
from ugc_bot.domain.order_targeting import validate_range
from ugc_bot.infrastructure.db.models import OrderModel

ORDER_EDITOR_SECTIONS = {
    "brief": (
        "order_type",
        "offer_text",
        "barter_description",
        "product_link",
        "brief_link",
        "content_usage",
        "deadlines",
    ),
    "terms": ("status", "bloggers_needed", "price"),
    "audience": (
        "geography",
        "min_followers",
        "max_followers",
        "min_age",
        "max_age",
        "min_publications",
        "max_publications",
        "min_rating",
        "required_blogger_gender",
        "filter_by_price",
        "price_filter_delta",
        "filter_by_placement",
        "filter_by_barter",
    ),
}
ORDER_EDITOR_LIMITS = {
    "offer_text": 4000,
    "barter_description": 4000,
    "product_link": 2048,
    "brief_link": 2048,
    "content_usage": 4000,
    "deadlines": 4000,
    "geography": 200,
}
ORDER_GEOGRAPHY_HINT = (
    "Укажите город, регион или страну. Например, Казань или Россия."
)
ORDER_EDITOR_HINTS = {
    "price": "Вознаграждение креатора за заказ в указанной валюте.",
    "status": "Для запуска рассылки нажмите «Активировать заказ».",
    "geography": ORDER_GEOGRAPHY_HINT,
    "filter_by_price": "Сравнивает цену в анкете креатора с ценой заказа.",
    "price_filter_delta": (
        "Допустимое отклонение от цены заказа в его валюте. Например, при "
        "цене 1 000 и отклонении 200 подходят цены от 800 до 1 200. "
        "С пустым отклонением фильтр по цене не применяется."
    ),
    "filter_by_placement": (
        "Для заказов «UGC + размещение» и «Сторис» выбирает креаторов, "
        "готовых размещать рекламу в своём аккаунте."
    ),
    "filter_by_barter": "Оставляет креаторов, готовых к бартеру по их анкете.",
}


class OrderAudiencePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geography: str | None = Field(default=None, max_length=200)
    min_followers: int | None = None
    max_followers: int | None = None
    min_age: int | None = None
    max_age: int | None = None
    min_publications: int | None = None
    max_publications: int | None = None
    min_rating: float | None = Field(default=None, ge=0, le=5)
    required_blogger_gender: BloggerGender | None = None
    filter_by_price: bool = False
    price_filter_delta: float | None = Field(default=None, ge=0, le=1e10)
    filter_by_placement: bool = False
    filter_by_barter: bool = False
    order_type: OrderType | None = None
    price: float | None = Field(default=None, ge=0, le=1e10)

    @model_validator(mode="after")
    def validate_ranges(self) -> Self:
        validate_range(self.min_followers, self.max_followers, 2147483647)
        validate_range(self.min_publications, self.max_publications, 2147483647)
        validate_range(self.min_age, self.max_age, 120)
        return self


def changed_text_errors(order: OrderModel, values: Mapping) -> dict[str, str]:
    errors = {}
    for name, limit in ORDER_EDITOR_LIMITS.items():
        if not isinstance(value := values.get(name), str):
            continue
        normalized = value.replace("\r\n", "\n")
        saved = (getattr(order, name) or "").replace("\r\n", "\n")
        if normalized != saved and len(normalized) > limit:
            errors[name] = (
                f"Максимум {limit} символов. Сейчас {len(normalized)}."
            )
        elif (
            name == "geography"
            and normalized != saved
            and has_unspecified_geography(normalized)
        ):
            errors[name] = ORDER_GEOGRAPHY_HINT
    return errors
