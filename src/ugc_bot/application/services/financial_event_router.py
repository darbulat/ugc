"""Fail closed until a real financial consumer is ready."""

from typing import NoReturn

from ugc_bot.domain.entities import OutboxEvent


class FinancialHandlerUnreadyError(RuntimeError):
    """Persist unsupported delivery as a retry, never success."""


class FinancialEventRouter:
    """No monetary handlers are registered by this negative slice."""

    def route(self, event: OutboxEvent) -> NoReturn:
        raise FinancialHandlerUnreadyError(
            f"financial_handler_unready: {event.event_type}"
        )
