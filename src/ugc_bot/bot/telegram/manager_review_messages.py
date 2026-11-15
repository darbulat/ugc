"""Telegram cards for reviewing and welcoming managers."""

from html import escape
from urllib.parse import urlsplit

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.domain.manager_application import (
    MANAGER_FIELD_LABELS,
    MANAGER_PROGRAM_URL,
    MANAGER_REVIEWABLE_STATES,
    MANAGER_STATES,
    application_version,
)

REVIEW_PREFIX = "mreview:"
REVIEW_PREVIEW_UNITS = 550


def _admin_card_url(config, user_id):
    base = (
        (config.admin.admin_base_url or config.webhook.webhook_base_url)
        .strip()
        .rstrip("/")
    )
    if not base:
        return None
    if not urlsplit(base).path:
        base += "/admin"
    return f"{base}/managers/{user_id}"


def _review_answers(answers):
    facts, written = [], []
    shortened = False
    for field, label in MANAGER_FIELD_LABELS.items():
        if field == "name" or not answers.get(field):
            continue
        value = str(answers[field])
        if field in {"case", "shortfall_plan", "reliability", "coverage"}:
            utf16 = value.encode("utf-16-le")
            if len(utf16) > REVIEW_PREVIEW_UNITS * 2:
                value = (
                    utf16[: REVIEW_PREVIEW_UNITS * 2]
                    .decode("utf-16-le", errors="ignore")
                    .rstrip()
                    + "…"
                )
                shortened = True
            written.append(
                f"<b>{label}</b>\n<blockquote>{escape(value)}</blockquote>"
            )
        else:
            facts.append(f"<b>{label}</b> · {escape(value)}")
    sections = ["\n".join(facts), *written] if facts else written
    if shortened:
        sections.append("<i>Полные ответы открываются в админке.</i>")
    return sections


def review_message(config, row, *, full=False, ready=False):
    user_id = row["user_id"]
    answers = row["answers"] or {}
    name = escape(answers.get("name") or row["username"] or "Менеджер")
    telegram = escape(f"@{row['telegram']}") if row["telegram"] else ""
    state = MANAGER_STATES[row["state"]]
    instagram = (
        "Instagram подтверждён"
        if row["instagram_verified_at"]
        else "Instagram ожидает подтверждения"
    )
    heading = "Анкета менеджера" if full else "Новая заявка менеджера"
    if ready:
        heading = "Заявка менеджера готова к проверке"
    identity = f"<b>{name}</b> · {telegram}" if telegram else f"<b>{name}</b>"
    lines = [f"<b>{heading}</b>", identity, f"{state} · {instagram}"]
    if full:
        lines.extend(_review_answers(answers))
    buttons: list[list[Button]] = []
    if url := _admin_card_url(config, user_id):
        buttons.append([Button(text="Открыть анкету в админке", url=url)])
    if row["state"] in MANAGER_REVIEWABLE_STATES:
        if row["instagram_verified_at"]:
            version = application_version(row["submitted_at"])
            buttons.insert(
                0,
                [
                    Button(
                        text="Принять менеджера",
                        callback_data=f"{REVIEW_PREFIX}a:{user_id.hex}:{version}",
                    )
                ],
            )
        if not full or not row["instagram_verified_at"]:
            buttons.append(
                [
                    Button(
                        text="Проверить в Telegram"
                        if not full
                        else "Обновить статус",
                        callback_data=f"{REVIEW_PREFIX}v:{user_id.hex}",
                    )
                ]
            )
    return "\n\n".join(lines), Keyboard(KeyboardKind.INLINE, buttons)


def instagram_verified_message(state):
    text = "<b>Instagram подтверждён</b>\n\n"
    if state == "draft":
        return (
            text + "Продолжите анкету с того места, где остановились.",
            Keyboard(
                KeyboardKind.INLINE,
                [
                    [
                        Button(
                            text="Продолжить анкету",
                            callback_data="mgr:next",
                        )
                    ]
                ],
            ),
        )
    return (
        text
        + "Анкета передана команде. Сообщим в этом чате, когда примем решение.",
        None,
    )


def manager_welcome(config):
    text = (
        "<b>Вы приняты в команду менеджеров UMC</b>\n\n"
        "С сегодняшнего дня можете начинать работу.\n\n"
        "<b>С чего начать</b>\n"
        "1. Откройте кабинет менеджера. Там появятся назначенные заказы "
        "с брифом и откликами.\n"
        "2. Согласуйте работу с блогерами, следите за сроками "
        "и отмечайте результат в заказе.\n"
        "3. Пополняйте свою базу блогеров. В реферальной программе "
        "скопируйте личную ссылку и приглашайте авторов, "
        "с которыми готовы работать.\n\n"
        "<b>Два способа заработать</b>\n"
        "• Сопровождать заказы и получать оплату за работу с блогерами.\n"
        "• Приглашать блогеров по личной ссылке и получать вознаграждение "
        "по условиям реферальной программы."
    )
    base = config.webhook.webhook_base_url.strip().rstrip("/")
    buttons = []
    if base:
        buttons.extend(
            [
                [
                    Button(
                        text="Кабинет менеджера",
                        web_app_url=f"{base}/miniapp/app.html?view=manager",
                    )
                ],
                [
                    Button(
                        text="Реферальная программа",
                        web_app_url=f"{base}/miniapp/app.html?view=partner",
                    )
                ],
            ]
        )
    buttons.append(
        [
            Button(
                text="Как работает менеджерская программа",
                url=MANAGER_PROGRAM_URL,
            )
        ]
    )
    return text, Keyboard(KeyboardKind.INLINE, buttons)
