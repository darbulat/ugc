"""One editable Telegram card for all positions of an order."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from math import ceil
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import Router

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.bot.customer_intake import principal_for
from ugc_bot.bot.telegram import order_summary_runtime
from ugc_bot.bot.telegram.handlers.utils import resolve_messenger_dependencies

router = Router()
PREFIX = "os:"
PAGE_SIZE = 5
REASONS = (
    ("no_answer", "Не отвечает"),
    ("refused", "Отказался"),
    ("not_done", "Работа не выполнена"),
    ("other", "Другая проблема"),
)
WORK = {
    None: "Результат ещё не подтверждён",
    "assigned": "Назначен",
    "in_progress": "В работе",
    "success_claimed": "Заявлен результат",
    "success_final": "Работа подтверждена",
    "available": "Работа подтверждена",
    "unconfirmed_expired": "Результат не подтверждён",
    "rejected": "Работа не подтверждена",
    "disputed": "Спор",
}
REPORT = {
    "queued": "Готовим уведомление",
    "waiting": "Ждём ответ креатора",
    "answered": "Креатор ответил",
    "withdrawn": "Отметка снята",
    "review": "Передано на проверку",
    "reviewed": "Проверено поддержкой",
    "replaced": "Замена назначена",
}


def encode_id(value):
    return urlsafe_b64encode(value.bytes).decode().rstrip("=")


def decode_id(value):
    if len(value) != 22:
        raise ValueError("summary_identity_invalid")
    return UUID(bytes=urlsafe_b64decode(value + "=="))


def summary_button(order_id, number=None):
    return Button(
        "Итоги заказа" if number is None else f"Итоги заказа №{number}",
        callback_data=f"{PREFIX}open:{order_id.hex}",
    )


def render_card(service, data, mode="open", page=0, reason_index=0):  # noqa: C901, PLR0912
    positions = data["positions"]
    pages = max(1, ceil(len(positions) / PAGE_SIZE))
    page = min(max(0, page), pages - 1)
    visible = positions[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    order = data["order_id"].hex
    draft = encode_id(data["draft_id"]) if data["draft_id"] else None

    def button(text, action, suffix=""):
        return Button(text, callback_data=f"{PREFIX}{action}:{order}{suffix}")

    title = f"Итоги заказа №{order[:8].upper()}"
    status = "Подбор закрыт" if data["closed"] else "Подбор открыт"
    lines = [
        title,
        status,
        "Заказ закрыт" if data["work_closed"] else "Итоги по позициям",
        f"Замены: {data['used']} из {data['limit']}",
        f"Позиции · {page + 1}/{pages}",
    ]
    if data["message"]:
        lines.append(data["message"])
    rows = []
    for item in visible:
        name = " ".join((item["username"] or "Креатор").split())[:55]
        report = REPORT.get(item["report_state"])
        if not item["assignment_id"]:
            state = {"refunded": "Возврат", "paid": "Ожидает контакта"}.get(
                item["selection_state"], "Подбор"
            )
        else:
            state = WORK.get(item["work_state"], item["work_state"])
        if item["report_state"] == "waiting" and item["answer_due_at"]:
            due = item["answer_due_at"].astimezone(ZoneInfo("Europe/Moscow"))
            report = f"Ждём ответ до {due:%d.%m %H:%M} МСК"
        if report:
            state += f" · {report}"
        if item["replacement_id"]:
            state += " · Новый креатор"
        lines.append(f"{item['ordinal']}. {name} — {state}")
        if mode == "exceptions" and draft and service.reportable(item):
            picked = data["draft"].get(str(item["assignment_id"]))
            label = dict(REASONS).get(picked, "")
            rows.append(
                [
                    Button(
                        f"{'✓ ' if picked else ''}{item['ordinal']}. {name}"
                        + (f" · {label}" if label else ""),
                        callback_data=(
                            f"{PREFIX}pick:{draft}:{encode_id(item['assignment_id'])}:{reason_index}"
                        ),
                    )
                ]
            )
        if mode == "open" and item["report_state"] in {
            "queued",
            "waiting",
            "answered",
            "review",
        }:
            rows.append(
                [
                    Button(
                        f"Снять отметку №{item['ordinal']}",
                        callback_data=f"{PREFIX}withdraw:{item['report_id'].hex}",
                    )
                ]
            )
        if mode == "open" and item["replacement_id"]:
            rows.append(
                [
                    Button(
                        f"Контакт замены №{item['ordinal']}",
                        callback_data=f"{PREFIX}contact:{item['replacement_id'].hex}",
                    )
                ]
            )
    if mode == "exceptions" and draft:
        lines += [
            f"Причина: {REASONS[reason_index][1]}",
            f"Выбрано: {len(data['draft'])}",
        ]
        rows += [
            [
                button(label, "exceptions", f":{page}:{index}")
                for index, (_, label) in enumerate(REASONS[:2])
            ],
            [
                button(label, "exceptions", f":{page}:{index}")
                for index, (_, label) in enumerate(REASONS[2:], 2)
            ],
            [
                Button(
                    "Сохранить отметки", callback_data=f"{PREFIX}save:{draft}"
                ),
                Button(
                    "Отменить выбор", callback_data=f"{PREFIX}discard:{draft}"
                ),
            ],
        ]
    elif mode == "confirm":
        eligible = [
            str(row["ordinal"])
            for row in positions
            if service.confirmable(row, data["client_id"])
        ]
        shown = ", ".join(eligible[:60])
        if len(eligible) > 60:
            shown += f" и ещё {len(eligible) - 60}"
        lines.append(
            "Будут подтверждены заявленные результаты: " + (shown or "нет")
        )
        if eligible:
            rows.append(
                [
                    button(
                        "Подтвердить показанные результаты",
                        "apply",
                        ":"
                        + service.confirmation_key(
                            positions, data["client_id"]
                        ),
                    )
                ]
            )
        rows.append([button("Назад", "open")])
    elif mode == "remind":
        rows += [
            [
                button("Завтра", "remind1"),
                button("Через 3 дня", "remind3"),
                button("Через 7 дней", "remind7"),
            ],
            [button("Назад", "open")],
        ]
    elif not data["work_closed"]:
        rows += [
            [
                button("Всё в порядке", "confirm"),
                button("Есть проблемы", "exceptions"),
            ]
        ]
        if data["reminder"] is None:
            rows.append([button("Ещё работаем", "remind")])
    if mode in {"open", "exceptions"}:
        arrows = [
            button(label, mode, f":{index}:{reason_index}")
            for label, index in (("←", page - 1), ("→", page + 1))
            if 0 <= index < pages
        ]
        if arrows:
            rows.append(arrows)
        if mode == "open":
            rows.append([button("Обновить", "open", f":{page}:0")])
    return "\n".join(lines), Keyboard(KeyboardKind.INLINE, rows)


@router.callback_query(lambda c: bool(c.data and c.data.startswith(PREFIX)))
async def order_summary_callback(
    callback,
    user_role_service,
    order_summary_service=None,
    messenger_client=None,
    event_adapter=None,
):
    messenger, adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = adapter.from_callback(callback)
    if not incoming.chat_id or incoming.chat_id != incoming.user.external_id:
        await messenger.answer_callback(callback_id=incoming.callback_id)
        return
    try:
        if order_summary_service is None:
            raise ValueError("summary_unavailable")
        user = await user_role_service.get_user(
            external_id=incoming.user.external_id,
            messenger_type=incoming.user.messenger_type,
        )
        if user is None:
            raise PermissionError("summary_unavailable")
        principal = principal_for(incoming, user.user_id)
        _, action, key, *args = incoming.data.split(":")
        identity = (
            decode_id(key)
            if action in {"pick", "save", "discard"}
            else UUID(key)
        )
        service = order_summary_service
        if action == "answer":
            accepted = await service.creator_answer(principal, identity)
            if incoming.message_id:
                await messenger.edit_text(
                    chat_id=incoming.chat_id,
                    message_id=incoming.message_id,
                    text="Ответ сохранён. Свяжитесь с заказчиком."
                    if accepted
                    else "Запрос уже закрыт.",
                    keyboard=None,
                )
        else:
            await update_card(
                incoming,
                messenger,
                service,
                principal,
                action,
                identity,
                args,
                callback.bot,
            )
    except (ValueError, PermissionError, LookupError, IndexError):
        await messenger.answer_callback(
            callback_id=incoming.callback_id,
            text="Откройте итоги заказа заново.",
            show_alert=True,
        )
        return
    await messenger.answer_callback(callback_id=incoming.callback_id)


async def update_card(
    incoming,
    messenger,
    service,
    principal,
    action,
    identity,
    args,
    callback_bot,
):
    if action not in {
        "open",
        "exceptions",
        "pick",
        "save",
        "discard",
        "confirm",
        "contact",
        "apply",
        "remind",
        "remind1",
        "remind3",
        "remind7",
        "withdraw",
    }:
        raise ValueError("summary_action_invalid")
    draft_action = action in {"pick", "save", "discard"}
    assignment_id = decode_id(args[0]) if action == "pick" else None
    reason_index = int(args[1]) if len(args) == 2 else 0
    if not 0 <= reason_index < len(REASONS):
        raise ValueError("summary_reason_invalid")
    page = int(args[0]) if action in {"open", "exceptions"} and args else 0
    if action == "contact":
        order_id, contact = await service.contact(principal, identity)
        action = "open"
        identity = order_id
    else:
        contact = None
    data = await service.view(
        principal,
        None if draft_action or action == "withdraw" else identity,
        action="confirm"
        if action == "apply"
        else "open"
        if action == "confirm"
        else action,
        draft_id=identity if draft_action else None,
        assignment_id=assignment_id,
        report_id=identity if action == "withdraw" else None,
        reason=REASONS[reason_index][0],
        confirmation=args[0] if action == "apply" and args else None,
    )
    mode = (
        "exceptions"
        if action in {"exceptions", "pick"}
        else action
        if action in {"confirm", "remind"}
        else "open"
    )
    if assignment_id is not None:
        index = next(
            i
            for i, row in enumerate(data["positions"])
            if row["assignment_id"] == assignment_id
        )
        page = index // PAGE_SIZE
    text, keyboard = render_card(service, data, mode, page, reason_index)
    if contact:
        text += f"\n\nКонтакт замены\n{contact[:900]}"
    message_id = data["message_id"]
    title = text.splitlines()[0]
    if (
        message_id is None
        and incoming.message_id
        and (incoming.message_text or "").split("\n", 1)[0] == title
    ):
        async with service.transactions.transaction() as session:
            await service.record_card_delivery(
                data["order_id"],
                data["client_id"],
                incoming.message_id,
                session=session,
            )
            latest = await service.read(
                data["order_id"], data["client_id"], session=session
            )
            message_id = latest["message_id"]
    if message_id:
        from aiogram.exceptions import TelegramBadRequest

        try:
            await messenger.edit_text(
                chat_id=incoming.chat_id,
                message_id=message_id,
                text=text,
                keyboard=keyboard,
            )
            return
        except TelegramBadRequest as exc:
            if "message to edit not found" not in str(exc).lower():
                raise
            async with service.transactions.transaction() as session:
                await service.summaries.forget_message(
                    data["order_id"], message_id, session=session
                )
    await order_summary_runtime.send_card(
        service, data, text, keyboard, incoming.chat_id, callback_bot
    )
