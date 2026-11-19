"""Correlate /start handling with replies accepted by Telegram."""

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.dispatcher.flags import get_flag
from aiogram.filters import CommandStart
from aiogram.methods import (
    Response,
    SendInvoice,
    SendMessage,
    SendPhoto,
    TelegramMethod,
)
from aiogram.methods.base import TelegramType
from aiogram.types import Message, TelegramObject, Update

logger = logging.getLogger(__name__)


@dataclass
class _StartTrace:
    update_id: int
    chat_id: int
    reply_ids: list[int] = field(default_factory=list)
    active: bool = True


_current_start: ContextVar[_StartTrace | None] = ContextVar(
    "telegram_start_trace", default=None
)


def _log(trace: _StartTrace, event: str, **fields: object) -> None:
    logger.info(
        event,
        extra={
            "event_type": event,
            "command": "/start",
            "update_id": trace.update_id,
            "reply_message_id": trace.reply_ids[-1]
            if trace.reply_ids
            else None,
            "reply_message_ids": trace.reply_ids.copy(),
            **fields,
        },
    )


class StartCommandLogging(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update = data.get("event_update")
        if (
            not any(
                isinstance(command, CommandStart)
                for command in get_flag(data, "commands", default=[])
            )
            or not isinstance(update, Update)
            or not isinstance(event, Message)
        ):
            return await handler(event, data)

        trace = _StartTrace(update.update_id, event.chat.id)
        token = _current_start.set(trace)
        started = perf_counter()
        _log(trace, "telegram.start.received")
        outcome = "failed"
        error_type = None
        try:
            result = await handler(event, data)
            outcome = "completed" if trace.reply_ids else "no_reply"
            return result
        except BaseException as exc:
            error_type = type(exc).__name__
            raise
        finally:
            trace.active = False
            _current_start.reset(token)
            _log(
                trace,
                "telegram.start.completed",
                outcome=outcome,
                error_type=error_type,
                duration_ms=round((perf_counter() - started) * 1000, 3),
            )


class StartReplyLogging(BaseRequestMiddleware):
    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        response = await make_request(bot, method)
        trace = _current_start.get()
        if (
            trace is not None
            and trace.active
            and isinstance(method, (SendMessage, SendPhoto, SendInvoice))
            and str(method.chat_id) == str(trace.chat_id)
            and isinstance(response, Message)
        ):
            trace.reply_ids.append(response.message_id)
            _log(
                trace,
                "telegram.start.reply_sent",
                api_method=type(method).__name__,
            )
        return response


def install_start_logging(dispatcher: Dispatcher, bot: Bot) -> None:
    """Install once on the production dispatcher and its Telegram session."""
    dispatcher.message.middleware(StartCommandLogging())
    bot.session.middleware(StartReplyLogging())
