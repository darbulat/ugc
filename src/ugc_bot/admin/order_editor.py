"""Order editor sections, input guidance and saved-field validation."""

from collections.abc import Mapping

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
ORDER_EDITOR_HINTS = {
    "price": "Вознаграждение креатора за заказ в указанной валюте.",
    "status": "Перевод нового заказа или заказа на модерации в «Активный» "
    "запускает рассылку.",
    "geography": "Укажите город или регион. Например, Казань.",
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
    return errors
