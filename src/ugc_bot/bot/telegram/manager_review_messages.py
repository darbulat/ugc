"""Telegram cards for reviewing and welcoming managers."""

from html import escape
from urllib.parse import urlsplit

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.domain.manager_application import (
    MANAGER_FIELD_LABELS,
    MANAGER_PROGRAM_URL,
    MANAGER_STATES,
    application_version,
)

REVIEW_PREFIX = "mreview:"


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
    for field, label in MANAGER_FIELD_LABELS.items():
        if field == "name" or not answers.get(field):
            continue
        value = escape(str(answers[field]))
        if field in {"case", "shortfall_plan", "reliability", "coverage"}:
            written.append(f"<b>{label}</b>\n<blockquote>{value}</blockquote>")
        else:
            facts.append(f"<b>{label}</b> · {value}")
    return ["\n".join(facts), *written] if facts else written


def review_message(config, row, *, full=False):
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
    identity = f"<b>{name}</b> · {telegram}" if telegram else f"<b>{name}</b>"
    lines = [f"<b>{heading}</b>", identity, f"{state} · {instagram}"]
    if full:
        lines.extend(_review_answers(answers))
    buttons: list[list[Button]] = []
    if url := _admin_card_url(config, user_id):
        buttons.append([Button(text="Открыть анкету в админке", url=url)])
    if row["state"] == "submitted":
        if full and row["instagram_verified_at"]:
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
        else:
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


def manager_welcome(config, note=None):
    text = (
        "<b>Вы приняты в команду менеджеров UMC</b>\n\n"
        "Начните с пополнения своей базы блогеров. Откройте реферальную "
        "программу, скопируйте личную ссылку и пригласите блогеров, "
        "с которыми хотите работать. Чем шире ваша база, тем быстрее "
        "вы сможете подбирать авторов на заказы.\n\n"
        "<b>Два способа заработать</b>\n"
        "• Сопровождать заказы и получать оплату за работу с блогерами.\n"
        "• Приглашать блогеров по личной ссылке и получать вознаграждение "
        "по условиям реферальной программы."
    )
    if note:
        text += f"\n\n<blockquote>{escape(note)}</blockquote>"
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
