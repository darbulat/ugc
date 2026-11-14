"""Send staff deadline alerts using the receipt-aware Telegram transport."""

import asyncio
import logging
from datetime import timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.application.services.customer_workflow_delivery import (
    WorkflowMessage,
)
from ugc_bot.domain.order_display import public_order_number
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.order_review import (
    claim_alert,
    finish_alert,
    schedule_alerts,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    TelegramNoticeReceipts,
)

logger = logging.getLogger(__name__)


def _message(job, admin_base_url):
    order_number = public_order_number(job["order_id"])
    overdue = job["stage"] == "overdue"
    title = (
        "Срок подбора истёк" if overdue else "Срок подбора в ближайшие 24 часа"
    )
    deadline = job["deadline"].astimezone(ZoneInfo("Europe/Moscow"))
    text = (
        f"{order_number} · {title}\n"
        f"Срок подбора: {deadline:%d.%m.%Y %H:%M} мск.\n"
        "Позиции без подтверждённого контакта или полного возврата: "
        f"{len(job['ordinals'])}.\n"
        "Проверьте позиции и назначьте следующий шаг."
    )
    if job["duty"] and admin_base_url:
        base = admin_base_url.strip().rstrip("/")
        if not urlsplit(base).path:
            base += "/admin"
        text += (
            f"\nОткрыть очередь: {base}/order-review?order_id={job['order_id']}"
        )
    if not job["duty"]:
        ordinals = ", ".join(str(n) for n in job["ordinals"][:20])
        more = " и другие" if len(job["ordinals"]) > 20 else ""
        text += f"\nВаши позиции: {ordinals}{more}."
    return WorkflowMessage(
        job["id"], "telegram", job["address"], "chat_id", text
    )


async def _send(transport, job, clock, admin_base_url):
    try:
        receipt = await transport.send(_message(job, admin_base_url))
        if receipt.channel == "telegram" and receipt.reference.strip():
            return "accepted", receipt.reference, None
    except DeliveryFailure as exc:
        if not exc.uncertain:
            if exc.retry_after_seconds is None:
                return "failed", None, None
            retry_at = clock.now() + timedelta(
                seconds=max(1, exc.retry_after_seconds)
            )
            return "ready", None, retry_at
    except Exception as exc:
        logger.warning(
            "Order review delivery result unknown",
            extra={"error_type": type(exc).__name__},
        )
    return "unknown", None, None


async def run_once(
    engine, transport, clock, start_at, duty_id, admin_base_url, *, limit=50
):
    def schedule(at):
        with Session(engine) as db, db.begin():
            schedule_alerts(db, at, start_at, duty_id, limit)

    def claim(at):
        with Session(engine) as db, db.begin():
            return claim_alert(db, at, start_at, duty_id)

    def finish(job, state, reference, retry_at):
        with Session(engine) as db, db.begin():
            finish_alert(db, job, state, reference, retry_at)

    at = clock.now()
    if at < start_at:
        return
    await asyncio.to_thread(schedule, at)
    for _ in range(limit):
        job = await asyncio.to_thread(claim, clock.now())
        if job is None:
            return
        if not job:
            continue
        state, reference, retry_at = await _send(
            transport, job, clock, admin_base_url
        )
        await asyncio.to_thread(finish, job, state, reference, retry_at)


async def run_enabled(config, container, bot):
    start_at = config.order.order_review_alerts_start_at
    duty_id = config.order.order_review_duty_admin_id
    if start_at is None or duty_id is None:
        return
    engine = container.get_admin_engine()
    while True:
        try:
            await run_once(
                engine,
                TelegramNoticeReceipts(bot),
                SystemClock(),
                start_at,
                duty_id,
                config.admin.admin_base_url,
            )
        except Exception as exc:
            logger.error(
                "Order review alert batch failed",
                extra={"error_type": type(exc).__name__},
            )
        await asyncio.sleep(60)
