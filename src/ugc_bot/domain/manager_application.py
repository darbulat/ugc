"""Questions and response options for Telegram manager onboarding."""

import re
from collections.abc import Mapping
from datetime import datetime

from ugc_bot.domain.creator_invites import instagram_handle

MANAGER_NOTIFICATION_RECIPIENTS = ("kamilbakhteev", "usemycontent")
MANAGER_PROGRAM_URL = "https://usemycontent.ru/partner"
MANAGER_SUBMITTED = "manager.application.submitted"
MANAGER_APPROVED = "manager.application.approved"
MANAGER_INSTAGRAM_VERIFIED = "manager.application.instagram_verified"
MANAGER_READY_FOR_REVIEW = "manager.application.ready_for_review"
MANAGER_READY_FOR_REVIEW_V2 = "manager.application.ready_for_review.v2"
MANAGER_REVIEWABLE_STATES = frozenset({"submitted", "clarify"})
MANAGER_NOTICE_EVENTS = frozenset(
    {
        MANAGER_SUBMITTED,
        MANAGER_APPROVED,
        MANAGER_INSTAGRAM_VERIFIED,
        MANAGER_READY_FOR_REVIEW,
        MANAGER_READY_FOR_REVIEW_V2,
    }
)
MANAGER_STATES = {
    "submitted": "На проверке",
    "clarify": "Нужно уточнение",
    "approved": "Одобрен",
    "declined": "Отклонён",
    "existing": "Уже назначался",
    "busy": "Ведёт заказ",
    "available": "Свободен",
}
MANAGER_FIELD_LABELS = {
    "name": "Имя",
    "rate": "Ставка за блогера",
    "work_format": "Формат работы",
    "work_format_details": "Подробнее о формате",
    "weekly_capacity": "Блогеров в неделю",
    "location": "Город",
    "location_region": "Регион",
    "location_country": "Страна",
    "phone": "Телефон",
    "instagram": "Instagram",
    "case": "Опыт работы с блогерами",
    "settlement": "Способ расчёта",
    "shortfall_plan": "Если нужно найти ещё 5 блогеров",
    "reliability": "Если блогер откажется",
    "coverage": "Ниши и площадки",
}


def application_version(submitted_at: datetime | None) -> int:
    return round(submitted_at.timestamp() * 1_000_000) if submitted_at else 0


INTRO = (
    "UMC подбирает блогеров и передаёт вам заказ с брифом и откликами. "
    "Вы общаетесь с блогерами, согласуете детали, следите за сроками "
    "и фиксируете результат.\n\n"
    "Укажите вашу ожидаемую ставку за сопровождение одного блогера."
)

MIN_WRITTEN_LENGTH = 20
MAX_WRITTEN_LENGTH = 1800
WRITTEN_FIELDS = frozenset({"case", "shortfall_plan"})

FIELDS = {
    "name": ("Как к вам обращаться?", 80),
    "rate": (
        "Сколько вы хотите получать за сопровождение одного блогера?\n\n"
        "UMC даёт бриф, подбор и отклики, а вы ведёте переписку с блогером "
        "и сопровождаете его до результата.\n\nВведите сумму в рублях "
        "или две суммы через тире.",
        80,
    ),
    "work_format": ("В каком формате вы работаете?", 40),
    "work_format_details": ("Коротко опишите, как вы работаете.", 180),
    "weekly_capacity": (
        "Сколько авторов вы можете пригласить за неделю?",
        20,
    ),
    "location": (
        "В каком городе вы живёте?\n\n"
        "Напишите название города. "
        "Например, Казань, Москва или Санкт-Петербург.",
        100,
    ),
    "phone": ("Поделитесь своим номером телефона для анкеты менеджера.", 20),
    "instagram": ("Укажите ник или ссылку на свой Instagram.", 250),
    "settlement": ("Как вам удобно получать оплату?", 40),
    "case": (
        "Расскажите об одном проекте с блогерами.\n\n"
        "Опишите задачу, вашу роль и результат. Например, сколько блогеров "
        "вы привлекли, за какой срок и что получил заказчик. "
        "Если есть ссылка на кейс, добавьте её. Если опыта ещё нет, "
        "расскажите, как организовали бы первый заказ.\n\n"
        f"(От {MIN_WRITTEN_LENGTH} символов.)",
        MAX_WRITTEN_LENGTH,
    ),
    "reliability": (
        "До публикации остался день, и блогер отказался от участия. "
        "Что вы сделаете и когда предупредите команду UMC?",
        500,
    ),
    "shortfall_plan": (
        "Как вы найдёте ещё 5 блогеров?\n\n"
        "Вы взяли заказ на 30 блогеров. UMC подобрала 25. Ещё 5 нужно "
        "найти в указанном городе или районе.\n\n"
        "Расскажите, где будете искать авторов вне базы UMC, как проверите, "
        "что они подходят, и когда сообщите команде о результате. "
        "Опишите порядок шагов и почему вы выбрали именно их.\n\n"
        f"(От {MIN_WRITTEN_LENGTH} символов. "
        "После ответа заявка отправится автоматически.)",
        MAX_WRITTEN_LENGTH,
    ),
    # Preserve the prompt and answers for older applications.
    "coverage": (
        "Если хотите, добавьте ниши, площадки, города или сколько авторов "
        "можете вести одновременно. Этот вопрос можно пропустить.",
        350,
    ),
}
FIELD_CHOICES = {
    "work_format": ("Фрилансер", "Агентство", "В команде бренда", "Другое"),
    "weekly_capacity": ("0", "1–10", "11–30", "31–100", "101+"),
    "settlement": (
        "Самозанятый",
        "ИП",
        "Компания или агентство",
        "Физлицо",
        "Пока не определился",
    ),
}


def application_fields(answers: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        field
        for field in FIELDS
        if field not in {"coverage", "reliability"}
        and (
            field != "work_format_details"
            or answers.get("work_format") == "Другое"
        )
    )


_AMOUNT = r"([0-9]{1,3}(?: [0-9]{3})+|[0-9]+)\s*₽?"
_RATE = re.compile(rf"{_AMOUNT}(?:\s*[-–—]\s*{_AMOUNT})?")


def normalize_manager_rate(value: str) -> str | None:
    match = _RATE.fullmatch(" ".join(value.split()))
    if not match:
        return None
    start, end = match.groups()
    amount = int(start.replace(" ", ""))
    upper = int(end.replace(" ", "")) if end else amount
    if not 0 < amount <= upper:
        return None
    return str(amount) if amount == upper else f"{amount}–{upper}"


def _validate_written_answer(value: str) -> str:
    if len(" ".join(value.split())) < MIN_WRITTEN_LENGTH:
        raise ValueError(f"Напишите ответ от {MIN_WRITTEN_LENGTH} символов.")
    if len(value) > MAX_WRITTEN_LENGTH:
        raise ValueError(f"Сократите ответ до {MAX_WRITTEN_LENGTH} символов.")
    return value


def validate_application_answer(field: str, value: str) -> str:
    value = value.strip()
    if field in WRITTEN_FIELDS:
        return _validate_written_answer(value)
    if field not in FIELDS or not 0 < len(value) <= FIELDS[field][1]:
        raise ValueError("Проверьте длину ответа.")
    if field == "rate":
        rate = normalize_manager_rate(value)
        if rate is None:
            raise ValueError("Введите сумму в рублях или две суммы через тире.")
        return rate
    if field == "instagram":
        try:
            return instagram_handle(value)
        except ValueError as exc:
            raise ValueError(
                "Укажите ник или ссылку на свой Instagram."
            ) from exc
    if field in FIELD_CHOICES and value not in FIELD_CHOICES[field]:
        raise ValueError("Выберите один из предложенных вариантов.")
    if field == "phone" and not re.fullmatch(r"\+?[0-9]{7,15}", value):
        raise ValueError("Поделитесь своим номером через кнопку.")
    return value


def missing_application_fields(answers: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        field
        for field in application_fields(answers)
        if not answers.get(field)
        or (field == "rate" and normalize_manager_rate(answers[field]) is None)
        or (field == "location" and not answers.get("location_country"))
        or (
            field in WRITTEN_FIELDS
            and len(" ".join(answers[field].split())) < MIN_WRITTEN_LENGTH
        )
    )
