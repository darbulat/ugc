"""Explicit financial consumers, running in the delivery transaction."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from ugc_bot.domain.entities import OutboxEvent


class FinancialHandlerUnreadyError(RuntimeError):
    """Persist unsupported delivery as a retry, never success."""


class FinancialEventHandler(Protocol):
    async def handle(self, event: OutboxEvent, *, session: object) -> None: ...


class FinancialEventRouter:
    """Unregistered types fail closed; consumers own durable business dedupe."""

    def __init__(
        self, handlers: Mapping[str, FinancialEventHandler] | None = None
    ):
        self.handlers = MappingProxyType(dict(handlers or {}))

    async def route(
        self, event: OutboxEvent, *, session: object | None
    ) -> None:
        handler = self.handlers.get(event.event_type)
        if handler is None or not event.event_type.startswith("financial."):
            raise FinancialHandlerUnreadyError(
                f"financial_handler_unready: {event.event_type}"
            )
        if session is None:
            raise ValueError("financial_transaction_required")
        await handler.handle(event, session=session)
