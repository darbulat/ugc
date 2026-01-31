"""Prompt texts for each FSM state, used when restoring a draft."""

DRAFT_PROMPT_BY_STATE: dict[str, str] = {
    # BloggerRegistrationStates
    "BloggerRegistrationStates:name": "Введите имя или ник для профиля, который увидят бренды:",
    "BloggerRegistrationStates:instagram": "Прикрепите ссылку на инстаграмм в формате instagram.com/name",
    "BloggerRegistrationStates:city": (
        "Из какого вы города?\nПример: Казань / Москва / Санкт‑Петербург"
    ),
    "BloggerRegistrationStates:topics": (
        "О чём ваш контент?\n"
        "Напишите 1–3 тематики через запятую: бизнес, инвестиции, фитнес, питание, "
        "бьюти, уход за кожей, путешествия, еда, рестораны, мода, стиль, дети, семья, "
        "технологии, гаджеты, лайфстайл, повседневная жизнь, другое"
    ),
    "BloggerRegistrationStates:audience_gender": (
        "Кто в основном смотрит ваш контент? По вашим наблюдениям или статистике"
    ),
    "BloggerRegistrationStates:audience_age": "Основной возраст вашей аудитории?",
    "BloggerRegistrationStates:audience_geo": (
        "Где находится основная аудитория? Укажите до 3 городов через запятую: "
        "Москва, Казань, Санкт‑Петербург"
    ),
    "BloggerRegistrationStates:price": (
        "Сколько стоит 1 UGC‑видео? Укажите цену в рублях: 500, 1000, 2000"
    ),
    "BloggerRegistrationStates:barter": (
        "Иногда вы готовы работать с брендами по бартеру?"
    ),
    "BloggerRegistrationStates:work_format": (
        "Помимо UGC, как ещё вы готовы работать с брендами?"
    ),
    "BloggerRegistrationStates:agreements": (
        "Пожалуйста, ознакомьтесь с документами и подтвердите согласие."
    ),
    # AdvertiserRegistrationStates
    "AdvertiserRegistrationStates:name": "Как вас зовут?",
    "AdvertiserRegistrationStates:phone": (
        "Номер телефона для связи по заказу (пример: +7 900 000-00-00):"
    ),
    "AdvertiserRegistrationStates:brand": (
        "Название вашего бренда / компании / бизнеса:"
    ),
    # OrderCreationStates
    "OrderCreationStates:product_link": "Введите ссылку на продукт:",
    "OrderCreationStates:offer_text": "Введите краткий offer для блогеров:",
    "OrderCreationStates:ugc_requirements": (
        "Введите требования к UGC или напишите 'пропустить':"
    ),
    "OrderCreationStates:barter_choice": "Есть бартер? Выберите:",
    "OrderCreationStates:barter_description": "Опишите бартерную продукцию:",
    "OrderCreationStates:price": "Введите цену за 1 UGC-видео:",
    "OrderCreationStates:bloggers_needed": "Выберите количество блогеров:",
    # EditProfileStates
    "EditProfileStates:choosing_field": "Выберите раздел для редактирования:",
    "EditProfileStates:entering_value": "",  # Filled from editing_field below
}

EDIT_FIELD_PROMPTS: dict[str, str] = {
    "nickname": "Введите новое имя или ник:",
    "instagram_url": "Прикрепите новую ссылку в формате instagram.com/name:",
    "city": "Из какого вы города?",
    "topics": "Напишите 1–3 тематики через запятую:",
    "audience_gender": "Кто в основном смотрит ваш контент?",
    "audience_age": "Основной возраст вашей аудитории?",
    "audience_geo": "Укажите до 3 городов через запятую:",
    "price": "Укажите цену за 1 UGC‑видео в рублях:",
    "barter": "Готовы работать по бартеру?",
    "work_format": "Как готовы работать с брендами?",
}


def get_draft_prompt(state_key: str, data: dict) -> str:
    """Return the prompt text for the given state_key and optional draft data.

    For EditProfileStates:entering_value, uses data['editing_field'] to look up
    the prompt in EDIT_FIELD_PROMPTS.
    """
    prompt = DRAFT_PROMPT_BY_STATE.get(state_key, "")
    if state_key == "EditProfileStates:entering_value" and data:
        field = data.get("editing_field")
        if field and field in EDIT_FIELD_PROMPTS:
            prompt = EDIT_FIELD_PROMPTS[field]
    return prompt or "Продолжите заполнение."
