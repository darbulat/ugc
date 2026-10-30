"""Record actual customer menu visits without starting series for outsiders."""

import logging

from ugc_bot.application.messenger.dto import IncomingCallback
from ugc_bot.bot.customer_intake import principal_for
from ugc_bot.bot.telegram.handlers.keyboards import (
    CALLBACK_ADV_START,
    CALLBACK_ORDER_AGREE,
    CALLBACK_PROFILE_MENU_CREATE_ORDER,
    CALLBACK_ROLE_ADVERTISER,
)
from ugc_bot.bot.telegram.handlers.profile import _ADVERTISER_AGREEMENTS_STATE
from ugc_bot.bot.texts.defaults import DEFAULT_TEXTS
from ugc_bot.domain.enums import UserStatus

logger = logging.getLogger(__name__)
_MENU_CALLBACKS = frozenset({CALLBACK_ROLE_ADVERTISER, CALLBACK_ADV_START})
_BRIEF_CALLBACKS = frozenset(
    {CALLBACK_PROFILE_MENU_CREATE_ORDER, CALLBACK_ORDER_AGREE}
)


def _visit_kind(incoming):
    if isinstance(incoming, IncomingCallback):
        if incoming.data in _MENU_CALLBACKS:
            return "menu"
        if incoming.data in _BRIEF_CALLBACKS:
            return "brief_opened"
        return None
    text = (incoming.text or "").strip()
    command = text.split(" ", 1)[0].split("@", 1)[0]
    if command == "/create_order":
        return "brief_opened"
    if command == "/advertiser":
        return "menu"
    for values in DEFAULT_TEXTS.values():
        if text == values.get("btn_create_order"):
            return "brief_opened"
        if text in {
            values.get("btn_advertiser"),
            values.get("btn_advertiser_start"),
        }:
            return "menu"
    return None


async def record_customer_visit(incoming, deps):
    # This optional reminder write must never prevent the requested bot action.
    try:
        await _record_customer_visit(incoming, deps)
    except Exception as exc:
        logger.warning(
            "Customer activity unavailable",
            extra={
                "platform": incoming.user.messenger_type.value,
                "error_type": type(exc).__name__,
            },
        )


async def _record_customer_visit(incoming, deps):
    followup = deps.get("client_followup_service")
    profiles = deps.get("profile_service")
    roles = deps.get("user_role_service")
    event = _visit_kind(incoming)
    if followup is None or profiles is None or roles is None or event is None:
        return
    user = await roles.get_user(
        external_id=incoming.user.external_id,
        messenger_type=incoming.user.messenger_type,
    )
    if user is None or user.status != UserStatus.ACTIVE:
        return
    profile = await profiles.get_advertiser_profile(user.user_id)
    if profile is None:
        return
    if event == "brief_opened":
        if getattr(incoming, "data", None) == CALLBACK_ORDER_AGREE:
            state = deps.get("state_store") or deps.get("state")
            if (
                state is None
                or await state.get_state() != _ADVERTISER_AGREEMENTS_STATE
                or (await state.get_data()).get("flow_type") != "order_creation"
            ):
                return
        elif profile.agreement_confirmed_at is not None:
            # Existing confirmed-profile order handlers record this event.
            return
    await followup.record_activity(
        user.user_id, event, principal=principal_for(incoming, user.user_id)
    )
