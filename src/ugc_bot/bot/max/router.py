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

_ERROR_TEXT = "Произошла ошибка. Попробуйте позже."


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

    async def route_message(
        self, incoming: IncomingMessage, deps: dict[str, Any]
    ) -> None:
        """Route an incoming message to the first matching handler.

        State-based handlers are checked first (if a state_store is present in
        deps), then regular predicate-based handlers.
        """
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
                except Exception:
                    logger.exception(
                        "Error in Max state message handler %s",
                        handler.__name__,
                    )
                    await self._send_error(incoming.chat_id, deps)
                return

        for predicate, handler in self._message_handlers:
            try:
                matched = predicate(incoming)
            except Exception:
                logger.debug("Predicate error for handler %s", handler.__name__)
                continue
            if matched:
                try:
                    await handler(incoming, deps)
                except Exception:
                    logger.exception(
                        "Error in Max message handler %s",
                        handler.__name__,
                    )
                    await self._send_error(incoming.chat_id, deps)
                return
        logger.debug(
            "No Max message handler matched for text=%r", incoming.text
        )

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
        await self._remove_callback_keyboard(incoming, deps)

        state_store = deps.get("state_store")
        if state_store is not None and self._state_callback_handlers:
            current_state = await state_store.get_state()
            for state_name, predicate, handler in self._state_callback_handlers:
                if current_state != state_name:
                    continue
                if predicate is not None and not predicate(incoming):
                    continue
                try:
                    await handler(incoming, deps)
                except Exception:
                    logger.exception(
                        "Error in Max state callback handler %s",
                        handler.__name__,
                    )
                    await self._send_error(incoming.chat_id, deps)
                return

        for predicate, handler in self._callback_handlers:
            try:
                matched = predicate(incoming)
            except Exception:
                logger.debug("Predicate error for handler %s", handler.__name__)
                continue
            if matched:
                try:
                    await handler(incoming, deps)
                except Exception:
                    logger.exception(
                        "Error in Max callback handler %s",
                        handler.__name__,
                    )
                    await self._send_error(incoming.chat_id, deps)
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
