"""Explicit single-request receipts; never use the generic retrying send_text.

Telegram sendMessage returns Message.message_id; MAX POST /messages returns
message.body.mid. These references prove provider acceptance only. No retry is
performed after network ambiguity or a missing/invalid provider reference.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from typing import TypedDict
from urllib.parse import urlsplit

import aiohttp
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
    NoticeReceiptTransport,
    ReceiptMessage,
)


def _address(attempt: ReceiptMessage, channel: str) -> int:
    try:
        address = int(attempt.address or "")
    except (ValueError, TypeError) as exc:
        raise DeliveryFailure(
            "recipient_contact_unavailable", uncertain=False
        ) from exc
    if (
        attempt.channel != channel
        or not address
        or attempt.address_kind not in ("chat_id", "user_id")
    ):
        raise DeliveryFailure("recipient_contact_unavailable", uncertain=False)
    return address


def _action(message: ReceiptMessage) -> tuple[str, str] | None:
    url, label = message.action_url, message.action_label
    if url is None and label is None:
        return None
    try:
        if not isinstance(url, str) or not isinstance(label, str):
            raise ValueError("invalid_action")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(char.isspace() or ord(char) < 32 for char in url)
            or not label.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in label)
        ):
            raise ValueError("invalid_action")
        # Access validates malformed ports before a request can be attempted.
        _ = parsed.port
    except ValueError as exc:
        raise DeliveryFailure(
            "receipt_action_invalid", uncertain=False
        ) from exc
    return url, label


def _retry_after_seconds(value: str | None) -> int | None:
    if value is None:
        return 30
    value = value.strip()
    try:
        if value.isascii() and value.isdigit():
            delay = int(value)
        else:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                return None
            delay = max(
                0, ceil((target - datetime.now(timezone.utc)).total_seconds())
            )
    except (ValueError, TypeError, OverflowError):
        return None
    return delay if 0 <= delay <= 31_536_000 else None


class _TelegramAction(TypedDict, total=False):
    reply_markup: InlineKeyboardMarkup


@dataclass(slots=True)
class TelegramNoticeReceipts:
    bot: Bot

    async def send(self, attempt: ReceiptMessage) -> DeliveryReceipt:
        address = _address(attempt, "telegram")
        action = _action(attempt)
        kwargs: _TelegramAction = {}
        if action is not None:
            if address < 0:
                raise DeliveryFailure(
                    "telegram_native_action_requires_private_chat",
                    uncertain=False,
                )
            url, label = action
            kwargs["reply_markup"] = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=label, web_app=WebAppInfo(url=url)
                        )
                    ]
                ]
            )
        try:
            message = await self.bot.send_message(
                chat_id=address, text=attempt.text, parse_mode=None, **kwargs
            )
        except TelegramRetryAfter as exc:
            delay = exc.retry_after
            if not isinstance(delay, int) or not 0 <= delay <= 31_536_000:
                raise DeliveryFailure(
                    "telegram_rejected", uncertain=False
                ) from exc
            raise DeliveryFailure(
                "telegram_rate_limited",
                uncertain=False,
                retry_after_seconds=delay,
            ) from exc
        except (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramNotFound,
            TelegramUnauthorizedError,
        ) as exc:
            raise DeliveryFailure("telegram_rejected", uncertain=False) from exc
        except Exception as exc:
            raise DeliveryFailure(
                "telegram_result_unknown", uncertain=True
            ) from exc
        mid = getattr(message, "message_id", None)
        chat_id = getattr(getattr(message, "chat", None), "id", None)
        if type(mid) is not int or mid <= 0 or chat_id != address:
            raise DeliveryFailure(
                "telegram_receipt_unavailable", uncertain=True
            )
        return DeliveryReceipt("telegram", f"{chat_id}:{mid}")


@dataclass(slots=True)
class MaxNoticeReceipts:
    session: aiohttp.ClientSession
    token: str

    async def send(self, attempt: ReceiptMessage) -> DeliveryReceipt:
        address = _address(attempt, "max")
        action = _action(attempt)
        if not self.token:
            raise DeliveryFailure(
                "max_receipt_transport_unavailable", uncertain=False
            )
        request_body: dict[str, object] = {"text": attempt.text}
        if action is not None:
            url, label = action
            request_body["attachments"] = [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [
                            [
                                {
                                    "type": "open_app",
                                    "text": label,
                                    "web_app": url,
                                }
                            ]
                        ]
                    },
                }
            ]
        try:
            async with self.session.post(
                "https://platform-api2.max.ru/messages",
                params={attempt.address_kind: address},
                headers={"Authorization": self.token},
                json=request_body,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 429:
                    delay = _retry_after_seconds(
                        getattr(response, "headers", {}).get("Retry-After")
                    )
                    if delay is None:
                        raise DeliveryFailure("max_rejected", uncertain=False)
                    raise DeliveryFailure(
                        "max_rate_limited",
                        uncertain=False,
                        retry_after_seconds=delay,
                    )
                if not 200 <= response.status < 300:
                    raise DeliveryFailure(
                        "max_rejected"
                        if 400 <= response.status < 500
                        else "max_result_unknown",
                        uncertain=not 400 <= response.status < 500,
                    )
                payload = await response.json()
        except DeliveryFailure:
            raise
        except Exception as exc:
            raise DeliveryFailure("max_result_unknown", uncertain=True) from exc
        message = payload.get("message") if isinstance(payload, dict) else None
        body = message.get("body") if isinstance(message, dict) else None
        mid = body.get("mid") if isinstance(body, dict) else None
        if not isinstance(mid, str) or not mid.strip():
            raise DeliveryFailure("max_receipt_unavailable", uncertain=True)
        return DeliveryReceipt("max", mid)


@dataclass(slots=True)
class RoutedNoticeReceipts:
    transports: dict[str, NoticeReceiptTransport]

    async def send(self, attempt: ReceiptMessage) -> DeliveryReceipt:
        transport = self.transports.get(attempt.channel or "")
        if transport is None:
            raise DeliveryFailure(
                "receipt_transport_unavailable", uncertain=False
            )
        return await transport.send(attempt)
