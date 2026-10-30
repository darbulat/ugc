"""MaxRouter — lightweight message/callback router for Max messenger."""

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ugc_bot.application.messenger.dto import IncomingCallback, IncomingMessage
from ugc_bot.bot.customer_activity import record_customer_visit
from ugc_bot.infrastructure.messenger.max.client import (
    MaxChatNotFoundError,
    MaxUserBlockedError,
)

logger = logging.getLogger(__name__)

_MessageHandler = Callable[
    [IncomingMessage, dict[str, Any]], Coroutine[Any, Any, None]
]
_CallbackHandler = Callable[
    [IncomingCallback, dict[str, Any]], Coroutine[Any, Any, None]
]
_MessagePredicate = Callable[[IncomingMessage], bool]
_CallbackPredicate = Callable[[IncomingCallback], bool]

_ERROR_TEXT = "Произошла ошибка. Попробуйте позже."


def _is_unreachable_chat_error(exc: Exception) -> bool:
    """Return True when callback/message comes from unreachable Max chat."""
    return isinstance(exc, (MaxUserBlockedError, MaxChatNotFoundError))


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

        @router.message_in_state("registration:name")
        async def handle_name(msg, deps):
            ...

        @router.callback_in_state("order:confirm", lambda c: c.data == "yes")
        async def confirm_order(cb, deps):
            ...
    """

    def __init__(self) -> None:
        self._message_handlers: list[
            tuple[_MessagePredicate, _MessageHandler]
        ] = []
        self._callback_handlers: list[
            tuple[_CallbackPredicate, _CallbackHandler]
        ] = []
        self._state_message_handlers: list[
            tuple[str, _MessagePredicate | None, _MessageHandler]
        ] = []
        self._state_callback_handlers: list[
            tuple[str, _CallbackPredicate | None, _CallbackHandler]
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

    def message_in_state(
        self,
        state_name: str,
        predicate: _MessagePredicate | None = None,
    ) -> Callable[[_MessageHandler], _MessageHandler]:
        """Register a message handler that fires only when FSM state matches.

        Args:
            state_name: Exact FSM state name to match against.
            predicate: Optional additional predicate; both state and predicate
                must match for the handler to fire.
        """

        def decorator(func: _MessageHandler) -> _MessageHandler:
            self._state_message_handlers.append((state_name, predicate, func))
            return func

        return decorator

    def callback_in_state(
        self,
        state_name: str,
        predicate: _CallbackPredicate | None = None,
    ) -> Callable[[_CallbackHandler], _CallbackHandler]:
        """Register a callback handler that fires only when FSM state matches.

        Args:
            state_name: Exact FSM state name to match against.
            predicate: Optional additional predicate; both state and predicate
                must match for the handler to fire.
        """

        def decorator(func: _CallbackHandler) -> _CallbackHandler:
            self._state_callback_handlers.append((state_name, predicate, func))
            return func

        return decorator

    async def _send_error(self, chat_id: str, deps: dict[str, Any]) -> None:
        """Try to send an error message to the user."""
        try:
            mc = deps.get("messenger_client")
            if mc:
                await mc.send_text(chat_id=chat_id, text=_ERROR_TEXT)
        except Exception:
            logger.debug("Failed to send error message to chat %s", chat_id)

    async def _handle_handler_error(
        self,
        *,
        scope: str,
        handler_name: str,
        chat_id: str,
        deps: dict[str, Any],
        exc: Exception,
    ) -> None:
        """Log handler errors and optionally notify user."""
        if _is_unreachable_chat_error(exc):
            logger.warning(
                "Skipping Max %s handler %s: %s",
                scope,
                handler_name,
                exc,
            )
            return
        logger.exception(
            "Error in Max %s handler %s",
            scope,
            handler_name,
        )
        await self._send_error(chat_id, deps)

    async def route_message(
        self, incoming: IncomingMessage, deps: dict[str, Any]
    ) -> None:
        """Route an incoming message to the first matching handler.

        Commands (messages starting with ``/``) are checked against
        predicate-based handlers first so they work even when the user
        is in an FSM state.  For regular text the order is reversed:
        state-based handlers are checked first, then predicate-based.
        """
        await record_customer_visit(incoming, deps)
        is_command = bool(incoming.text and incoming.text.startswith("/"))

        if is_command and await self._try_predicate_handlers(incoming, deps):
            return

        state_store = deps.get("state_store")
        if state_store is not None and self._state_message_handlers:
            current_state = await state_store.get_state()
            for state_name, predicate, handler in self._state_message_handlers:
                if current_state != state_name:
                    continue
                if predicate is not None and not predicate(incoming):
                    continue
                try:
                    await handler(incoming, deps)
                except Exception as exc:
                    await self._handle_handler_error(
                        scope="state message",
                        handler_name=handler.__name__,
                        chat_id=incoming.chat_id,
                        deps=deps,
                        exc=exc,
                    )
                return

        if not is_command and await self._try_predicate_handlers(
            incoming, deps
        ):
            return
        logger.debug(
            "No Max message handler matched for text=%r", incoming.text
        )

    async def _try_predicate_handlers(
        self, incoming: IncomingMessage, deps: dict[str, Any]
    ) -> bool:
        """Try predicate-based handlers. Return True if one matched."""
        for predicate, handler in self._message_handlers:
            try:
                matched = predicate(incoming)
            except Exception:
                logger.debug("Predicate error for handler %s", handler.__name__)
                continue
            if matched:
                try:
                    await handler(incoming, deps)
                except Exception as exc:
                    await self._handle_handler_error(
                        scope="message",
                        handler_name=handler.__name__,
                        chat_id=incoming.chat_id,
                        deps=deps,
                        exc=exc,
                    )
                return True
        return False

    async def _try_state_callback_handlers(
        self, incoming: IncomingCallback, deps: dict[str, Any]
    ) -> bool:
        """Try callback handlers bound to current FSM state."""
        state_store = deps.get("state_store")
        if state_store is None or not self._state_callback_handlers:
            return False
        current_state = await state_store.get_state()
        for state_name, predicate, handler in self._state_callback_handlers:
            if current_state != state_name:
                continue
            if predicate is not None and not predicate(incoming):
                continue
            try:
                await handler(incoming, deps)
            except Exception as exc:
                await self._handle_handler_error(
                    scope="state callback",
                    handler_name=handler.__name__,
                    chat_id=incoming.chat_id,
                    deps=deps,
                    exc=exc,
                )
            return True
        return False

    async def _try_callback_handlers(
        self, incoming: IncomingCallback, deps: dict[str, Any]
    ) -> bool:
        """Try predicate-based callback handlers."""
        for predicate, handler in self._callback_handlers:
            try:
                matched = predicate(incoming)
            except Exception:
                logger.debug("Predicate error for handler %s", handler.__name__)
                continue
            if not matched:
                continue
            try:
                await handler(incoming, deps)
            except Exception as exc:
                await self._handle_handler_error(
                    scope="callback",
                    handler_name=handler.__name__,
                    chat_id=incoming.chat_id,
                    deps=deps,
                    exc=exc,
                )
            return True
        return False

    async def _remove_callback_keyboard(
        self, incoming: IncomingCallback, deps: dict[str, Any]
    ) -> None:
        """Remove inline keyboard from the callback message."""
        messenger_client = deps.get("messenger_client")
        if messenger_client is None or not incoming.message_id:
            return
        try:
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
        except Exception:
            logger.warning(
                "Could not remove callback keyboard for mid=%s",
                incoming.message_id,
                exc_info=True,
            )

    async def route_callback(
        self, incoming: IncomingCallback, deps: dict[str, Any]
    ) -> None:
        """Route an incoming callback to the first matching handler.

        State-based handlers are checked first (if a state_store is present in
        deps), then regular predicate-based handlers.
        """
        await record_customer_visit(incoming, deps)
        await self._remove_callback_keyboard(incoming, deps)

        if await self._try_state_callback_handlers(incoming, deps):
            return
        if await self._try_callback_handlers(incoming, deps):
            return
        logger.debug(
            "No Max callback handler matched for data=%r", incoming.data
        )

    def include(self, router: "MaxRouter") -> None:
        """Merge all handlers from another router into this one."""
        self._message_handlers.extend(router._message_handlers)
        self._callback_handlers.extend(router._callback_handlers)
        self._state_message_handlers.extend(router._state_message_handlers)
        self._state_callback_handlers.extend(router._state_callback_handlers)
