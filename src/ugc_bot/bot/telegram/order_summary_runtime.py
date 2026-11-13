"""Telegram transport and scheduler for order summaries."""

import asyncio
import logging
from datetime import timedelta
from re import fullmatch

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.infrastructure.messenger.telegram.client import _build_markup

logger = logging.getLogger(__name__)
DEFINITE_REJECTION = (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)


def provider_reference(message, chat_id):
    mid = getattr(message, "message_id", None)
    if (
        type(mid) is not int
        or mid <= 0
        or getattr(getattr(message, "chat", None), "id", None) != int(chat_id)
    ):
        return None
    return str(mid)


async def send_card(service, data, text, keyboard, chat_id, bot):
    if bot is None:
        raise ValueError("summary_transport_unavailable")
    order_id, client_id = data["order_id"], data["client_id"]
    async with service.transactions.transaction() as session:
        claimed = await service.summaries.claim_message(
            order_id, client_id, service.now(), session=session
        )
    if not claimed:
        raise ValueError("summary_message_already_claimed")
    try:
        message = await bot.send_message(
            chat_id=int(chat_id),
            text=text,
            parse_mode=None,
            reply_markup=_build_markup(keyboard),
        )
    except DEFINITE_REJECTION:
        async with service.transactions.transaction() as session:
            await service.summaries.patch_card(
                order_id, message_claimed_at=None, session=session
            )
        raise ValueError("summary_transport_rejected") from None
    except Exception:
        # With no provider receipt, a repeat could produce a second card.
        raise ValueError("summary_transport_unknown") from None
    reference = provider_reference(message, chat_id)
    if reference is None:
        raise ValueError("summary_transport_unknown")
    async with service.transactions.transaction() as session:
        await service.record_card_delivery(
            order_id, client_id, reference, session=session
        )


async def _prepare(service, job):
    from ugc_bot.bot.telegram.handlers.order_summary import (
        PREFIX,
        render_card,
        summary_button,
    )

    async with service.transactions.transaction() as session:
        user = await service.summaries.user(
            job["recipient_id"], session=session
        )
        if (
            user is None
            or not fullmatch(r"[1-9][0-9]*", user.telegram_id or "")
            or user.status != "active"
        ):
            return None
        if job["kind"] == "creator":
            report = await service.summaries.report(
                job["report_id"], session=session
            )
            if report is None or report["state"] != "queued":
                return None
            context = await service.summaries.report_context(
                report, session=session
            )
            if (
                context is None
                or context["valid_to"] is not None
                or context["status"] not in {"active", "closed"}
                or context["advertiser_id"] != report["client_id"]
                or context["creator_id"] != job["recipient_id"]
                or context["work_state"]
                in {"success_final", "available", "rejected"}
            ):
                return None
            return (
                user.telegram_id,
                (
                    f"Заказ №{job['order_id'].hex[:8].upper()}. "
                    "Заказчик сообщил, что не может с вами связаться. "
                    "Если вы на связи, подтвердите в течение 24 часов "
                    "и напишите заказчику."
                ),
                Keyboard(
                    KeyboardKind.INLINE,
                    [
                        [
                            Button(
                                "Я на связи",
                                callback_data=f"{PREFIX}answer:{report['report_id'].hex}",
                            )
                        ]
                    ],
                ),
                None,
            )
        try:
            _, card = await service.summaries.card(
                job["order_id"],
                user.user_id,
                service.now(),
                session=session,
                lock=True,
            )
        except PermissionError:
            return None
        data = await service.read(
            job["order_id"], user.user_id, session=session
        )
        if job["kind"] == "summary":
            if card["message_id"] or not await service.summaries.claim_message(
                job["order_id"],
                user.user_id,
                service.now(),
                session=session,
            ):
                return None
            text, keyboard = render_card(service, data)
            return user.telegram_id, text, keyboard, job["order_id"]
        if service.is_resolved(data) or (
            not job["requested"] and card["responded_at"] is not None
        ):
            return None
        return (
            user.telegram_id,
            "Напоминание об итогах заказа.",
            Keyboard(KeyboardKind.INLINE, [[summary_button(job["order_id"])]]),
            None,
        )


async def _deliver(service, bot, job):
    prepared = await _prepare(service, job)
    state, reference = "obsolete", None
    if prepared:
        address, text, keyboard, card_id = prepared
        try:
            message = await bot.send_message(
                chat_id=int(address),
                text=text,
                parse_mode=None,
                reply_markup=_build_markup(keyboard),
            )
            reference = provider_reference(message, address)
            state = "sent" if reference else "unknown"
        except DEFINITE_REJECTION:
            state = "failed"
        except Exception:
            state = "unknown"
    at = service.now()
    async with service.transactions.transaction() as session:
        won = await service.summaries.finish_job(
            job["job_id"], state, reference, at, session=session
        )
        if not won:
            return
        if prepared and card_id is not None:
            if state == "sent":
                await service.record_card_delivery(
                    card_id, job["recipient_id"], reference, session=session
                )
            elif state == "failed":
                await service.summaries.patch_card(
                    card_id, message_claimed_at=None, session=session
                )
        if job["kind"] == "creator" and state == "sent":
            report = await service.summaries.report(
                job["report_id"], lock=True, session=session
            )
            if report["state"] == "queued":
                await service.summaries.set_report(
                    report["report_id"],
                    state="waiting",
                    answer_due_at=at + timedelta(hours=24),
                    session=session,
                )


async def run_once(service, bot, *, limit=40):
    at = service.now()
    async with service.transactions.transaction() as session:
        await service.summaries.discover(at, session=session, limit=limit)
        jobs = await service.summaries.claim_jobs(
            at, session=session, limit=limit
        )
    for job in jobs:
        await _deliver(service, bot, job)
    async with service.transactions.transaction() as session:
        reports = await service.summaries.expired(
            at, session=session, limit=limit
        )
    for report in reports:
        await service.replace_report(report)
    async with service.transactions.transaction() as session:
        await service.summaries.notify_reviews(at, session=session, limit=limit)
        closing = await service.summaries.closing_candidates(
            at, session=session, limit=limit
        )
    for order_id, client_id in closing:
        try:
            await service.close_if_resolved(order_id, client_id)
        except (ValueError, PermissionError):
            continue


async def run_enabled(config, container, bot):
    from ugc_bot.container.order_summary_factory import build_order_summary

    if (
        not config.financial.core_enabled
        or not config.order.customer_workflows_enabled
    ):
        return
    service = build_order_summary(config, container.transaction_manager)
    if service is None:
        return
    while True:
        try:
            await run_once(service, bot)
        except Exception as exc:
            logger.error(
                "Telegram order summary batch failed",
                extra={"error_type": type(exc).__name__},
            )
        await asyncio.sleep(60)
