"""MaxRouter — lightweight message/callback router for Max messenger."""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage

logger = logging.getLogger(__name__)

_MessageHandler = Callable[
    [IncomingMessage, dict[str, Any]], Coroutine[Any, Any, None]
]
_CallbackHandler = Callable[
    [IncomingCallback, dict[str, Any]], Coroutine[Any, Any, None]
]
_MessagePredicate = Callable[[IncomingMessage], bool]
_CallbackPredicate = Callable[[IncomingCallback], bool]


class MaxRouter:
    """Routes incoming Max messages and callbacks to registered handlers.

    Usage::

        router = MaxRouter()

        @router.message(lambda m: m.text == "/start")
        async def start(msg, deps):
            ...

        @router.callback(lambda c: c.data.startswith("order:"))
        async def order(cb, deps):
            ...
    """

    def __init__(self) -> None:
        self._message_handlers: list[
            tuple[_MessagePredicate, _MessageHandler]
        ] = []
        self._callback_handlers: list[
            tuple[_CallbackPredicate, _CallbackHandler]
        ] = []

    def message(
        self, predicate: _MessagePredicate
    ) -> Callable[[_MessageHandler], _MessageHandler]:
        """Register a message handler for messages matching predicate."""

        def decorator(func: _MessageHandler) -> _MessageHandler:
            self._message_handlers.append((predicate, func))
            return func

        return decorator

    def callback(
        self, predicate: _CallbackPredicate
    ) -> Callable[[_CallbackHandler], _CallbackHandler]:
        """Register a callback handler for callbacks matching predicate."""

        def decorator(func: _CallbackHandler) -> _CallbackHandler:
            self._callback_handlers.append((predicate, func))
            return func

        return decorator

    async def route_message(
        self, incoming: IncomingMessage, deps: dict[str, Any]
    ) -> None:
        """Route an incoming message to the first matching handler."""
        for predicate, handler in self._message_handlers:
            try:
                if predicate(incoming):
                    await handler(incoming, deps)
                    return
            except Exception:
                logger.exception(
                    "Error in Max message handler %s", handler.__name__
                )
                return
        logger.debug(
            "No Max message handler matched for text=%r", incoming.text
        )

    async def route_callback(
        self, incoming: IncomingCallback, deps: dict[str, Any]
    ) -> None:
        """Route an incoming callback to the first matching handler."""
        for predicate, handler in self._callback_handlers:
            try:
                if predicate(incoming):
                    await handler(incoming, deps)
                    return
            except Exception:
                logger.exception(
                    "Error in Max callback handler %s", handler.__name__
                )
                return
        logger.debug(
            "No Max callback handler matched for data=%r", incoming.data
        )

    def include(self, router: "MaxRouter") -> None:
        """Merge all handlers from another router into this one."""
        self._message_handlers.extend(router._message_handlers)
        self._callback_handlers.extend(router._callback_handlers)
