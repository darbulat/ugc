"""Telegram cards for reviewing and welcoming managers."""

from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlsplit
from uuid import UUID

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
REVIEW_PAGE_SIZE = 10


def review_queue_cursor(payload: str) -> tuple[datetime, UUID] | None:
    if not payload:
        return None
    micros, identity = payload.split(":", 1)
    queued_at = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(
        microseconds=int(micros)
    )
    return queued_at, UUID(hex=identity)


def review_queue_message(rows, *, after: tuple[datetime, UUID] | None):
    buttons = [
        [
            Button(
                text=(row["name"] or row["username"] or "Менеджер")[:80],
                callback_data=f"{REVIEW_PREFIX}v:{row['user_id'].hex}",
            )
        ]
        for row in rows[:REVIEW_PAGE_SIZE]
    ]
    navigation = []
    if after is not None:
        navigation.append(
            Button(text="К началу", callback_data=f"{REVIEW_PREFIX}q")
        )
    if len(rows) > REVIEW_PAGE_SIZE:
        last = rows[REVIEW_PAGE_SIZE - 1]
        cursor = (
            f"{application_version(last['queued_at'])}:{last['user_id'].hex}"
        )
        navigation.append(
            Button(text="Далее", callback_data=f"{REVIEW_PREFIX}q:{cursor}")
        )
    if navigation:
        buttons.append(navigation)
    text = (
        "Заявки менеджеров с подтверждённым Instagram"
        if rows
        else "На этой странице нет заявок, готовых к одобрению."
    )
    return text, Keyboard(KeyboardKind.INLINE, buttons) if buttons else None


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


def manager_workspace_keyboard(config) -> Keyboard:
    base = (config.webhook.webhook_base_url or "").strip().rstrip("/")
    links = (
        ("Моя база креаторов", "view=manager&section=creators"),
        ("Мои заказы", "view=manager"),
        ("Моя ссылка для приглашений", "view=partner"),
    )
    return Keyboard(
        KeyboardKind.INLINE,
        [
            [Button(text=label, web_app_url=f"{base}/miniapp/app.html?{query}")]
            for label, query in links
        ]
        if base
        else [],
    )


def instagram_verified_message(state, config):
    text = "<b>Instagram подтверждён ✅</b>\n\n"
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
    if state == "approved":
        workspace = manager_workspace_keyboard(config)
        return (
            text + "Анкета одобрена. Теперь вам доступен кабинет менеджера.",
            workspace if workspace.rows else None,
        )
    if state == "declined":
        return (
            text + "Анкета отклонена. Текущий статус доступен в /manager.",
            None,
        )
    return (
        text
        + "Анкета передана команде. Проверяйте статус заявки через /manager.",
        Keyboard(
            KeyboardKind.INLINE,
            [[Button(text="Проверить статус", callback_data="mgr:status")]],
        ),
    )


def manager_welcome(config):
    text = (
        "<b>Вы приняты в команду менеджеров UMC</b>\n\n"
        "С сегодняшнего дня можете начинать работу.\n\n"
        "<b>С чего начать</b>\n"
        "1. Откройте «Мои заказы». Там появятся назначенные заказы "
        "с брифом и откликами.\n"
        "2. Согласуйте работу с блогерами, следите за сроками "
        "и отмечайте результат в заказе.\n"
        "3. Пополняйте свою базу блогеров. Скопируйте личную ссылку "
        "для приглашений. Авторы, которые перейдут по ней и заполнят анкету, "
        "появятся в разделе «Моя база креаторов».\n\n"
        "<b>Два способа заработать</b>\n"
        "• Сопровождать заказы и получать оплату за работу с блогерами.\n"
        "• Приглашать блогеров по личной ссылке и получать вознаграждение "
        "по условиям реферальной программы."
    )
    buttons = manager_workspace_keyboard(config).rows
    buttons.append(
        [
            Button(
                text="Как работает менеджерская программа",
                url=MANAGER_PROGRAM_URL,
            )
        ]
    )
    return text, Keyboard(KeyboardKind.INLINE, buttons)
