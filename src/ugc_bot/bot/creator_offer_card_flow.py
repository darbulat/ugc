"""Edit the original offer as a creator reads, confirms, or skips it."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import escape
from typing import Protocol, cast
from uuid import UUID

from ugc_bot.application.creator_offer_cards import (
    CALLBACK_PREFIX,
    SKIP_REASONS,
    VIEWS,
    OfferCard,
    client_contact_links,
    client_contact_text,
    https_link,
    render_public_offer,
    render_saved_offer,
)
from ugc_bot.application.errors import (
    OrderCreationError,
    PaidSelectionResponseError,
)
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    OfferCardTransport,
)
from ugc_bot.application.ports import OrderRepository
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.offer_response_service import (
    OfferResponseResult,
    OfferResponseService,
)
from ugc_bot.application.services.profile_service import ProfileService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.selection_response import selection_response_message_key
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.domain.offer_intake import intake_open, reserve_notice

logger = logging.getLogger(__name__)


class ResponseRateLimiter(Protocol):
    async def allow_async(self, key: str) -> bool: ...


async def send_legacy_offer_confirmation(
    messenger: MessengerClient,
    texts: BotTextsService,
    locale: str,
    chat_id: str,
    order: Order,
) -> None:
    """Send the brief and confirmation for an older offer message."""
    if order.brief_link:
        brief_label = await texts.get("msg_offer_brief_link", locale)
        await messenger.send_text(
            chat_id=chat_id,
            text=f"{brief_label}\n{order.brief_link}",
        )

    confirm_text = await texts.get("msg_offer_confirm_response", locale)
    if order.offer_reserve_until is not None:
        confirm_text = reserve_notice(order.offer_reserve_until, locale)
    btn_texts = await texts.get_many(
        ["btn_offer_confirm", "btn_offer_cancel"], locale
    )
    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=btn_texts.get("btn_offer_confirm", "Готов"),
                    callback_data=f"offer_confirm:{order.order_id}",
                )
            ],
            [
                Button(
                    text=btn_texts.get("btn_offer_cancel", "Отмена"),
                    callback_data=f"offer_cancel:{order.order_id}",
                )
            ],
        ],
    )
    await messenger.send_text(
        chat_id=chat_id,
        text=confirm_text,
        keyboard=keyboard,
    )


async def prompt_offer_price(
    messenger: MessengerClient,
    texts: BotTextsService,
    locale: str,
    chat_id: str,
    order_id: UUID,
) -> None:
    prompt = await texts.get("msg_enter_desired_price", locale)
    cancel = await texts.get("btn_cancel_price_entry", locale)
    keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(cancel, callback_data=f"orr_cancel:{order_id}")]],
    )
    await messenger.send_text(chat_id=chat_id, text=prompt, keyboard=keyboard)


@dataclass
class CreatorOfferCardFlow:
    orders: OrderRepository
    dispatch: OfferDispatchService
    responses: OfferResponseService
    users: UserRoleService
    profiles: ProfileService
    texts: BotTextsService
    messenger: MessengerClient
    locale: str
    rate_limiter: ResponseRateLimiter | None = None
    start_price_entry: Callable[[UUID], Awaitable[None]] | None = None

    async def _answer(
        self,
        incoming: IncomingCallback,
        key: str | None = None,
    ) -> None:
        text = await self.texts.get(key, self.locale) if key else None
        await self.messenger.answer_callback(
            callback_id=incoming.callback_id,
            text=text,
        )

    async def handle(
        self,
        incoming: IncomingCallback,
    ) -> tuple[OfferResponseResult, User] | None:
        action, _, raw_id = (
            (incoming.data or "").removeprefix(CALLBACK_PREFIX).partition(":")
        )
        try:
            order_id = UUID(raw_id)
        except ValueError:
            await self._answer(incoming, "err_order_invalid_id")
            return None
        order = await self.orders.get_by_id(order_id)
        if order is None or not order.creator_offer_card:
            await self._answer(incoming, "msg_order_closed")
            return None
        user = await self._eligible_user(incoming, order_id)
        if user is None:
            return None
        response: OfferResponseResult | None = None
        if action == "done":
            card, response = await self._confirm(incoming, order, user)
            if card is None:
                return None
        else:
            card = await self._view(incoming, order, user, action)
            if card is None:
                return None
        await self._answer(incoming)
        if response and response.accepted and not response.delivery_queued:
            # Direct delivery has no paid delivery worker. Make the
            # notification available to the caller before editing the card.
            return response, user
        await self._edit(incoming, order, user, card, terminal=action == "done")
        return None

    async def _eligible_user(
        self,
        incoming: IncomingCallback,
        order_id: UUID,
    ) -> User | None:
        channel = incoming.user.messenger_type
        user = await self.users.get_user(
            external_id=incoming.user.external_id,
            messenger_type=channel,
        )
        if not user or user.status != UserStatus.ACTIVE:
            await self._answer(incoming, "msg_offer_response_blocked")
            return None
        receipts = self.dispatch.offer_dispatch_repo
        address = (
            user.telegram_id
            if channel == MessengerType.TELEGRAM
            else user.max_chat_id
        )
        if (
            not incoming.message_id
            or incoming.chat_id != address
            or not (
                await receipts.creator_card_matches(
                    order_id, user.user_id, channel, incoming.message_id
                )
                or await receipts.recover_creator_card_receipt(
                    order_id, user.user_id, channel, incoming.message_id
                )
            )
        ):
            await self._answer(incoming, "msg_order_closed")
            return None
        return user

    async def _stored_view(
        self,
        order: Order,
        user: User,
    ) -> OfferCard | None:
        responses = (
            await self.dispatch.offer_dispatch_repo.list_responses_by_blogger(
                user.user_id
            )
        )
        matching = next(
            (item for item in responses if item.order_id == order.order_id),
            None,
        )
        if matching is None:
            return None
        if matching.accepted and matching.in_offer:
            return render_saved_offer(order, self.locale)
        if not intake_open(
            order.status, order.dispatch_stopped, order.offer_reserve_until
        ):
            return render_public_offer(order, self.locale, "closed")
        view = "reserve" if matching.accepted else "skipped"
        return render_public_offer(order, self.locale, view)

    async def _confirm(
        self,
        incoming: IncomingCallback,
        order: Order,
        user: User,
    ) -> tuple[OfferCard | None, OfferResponseResult | None]:
        stored = await self._stored_view(order, user)
        if stored:
            return stored, None
        if not intake_open(
            order.status, order.dispatch_stopped, order.offer_reserve_until
        ):
            return render_public_offer(order, self.locale, "closed"), None
        profile = await self.profiles.get_blogger_profile(user.user_id)
        if not profile or not profile.confirmed:
            await self._answer(incoming, "msg_confirm_instagram_first")
            return None, None
        if (
            self.rate_limiter is not None
            and not await self.rate_limiter.allow_async(str(user.user_id))
        ):
            await self._answer(incoming, "msg_too_many_requests")
            return None, None
        try:
            result = await self.responses.respond_and_finalize(
                order.order_id,
                user.user_id,
                channel=incoming.user.messenger_type,
            )
        except PaidSelectionResponseError as exc:
            if exc.reason == "offer_intake_closed":
                return render_public_offer(order, self.locale, "closed"), None
            await self._answer(
                incoming, selection_response_message_key(exc.reason)
            )
            return None, None
        except OrderCreationError:
            card = await self._stored_view(order, user)
            return card or render_public_offer(
                order, self.locale, "closed"
            ), None
        if result.accepted:
            return render_saved_offer(result.order, self.locale), result
        return render_public_offer(order, self.locale, "reserve"), result

    async def _view(
        self,
        incoming: IncomingCallback,
        order: Order,
        user: User,
        action: str,
    ) -> OfferCard | None:
        stored = await self._stored_view(order, user)
        if stored:
            return stored
        if not intake_open(
            order.status, order.dispatch_stopped, order.offer_reserve_until
        ):
            return render_public_offer(order, self.locale, "closed")
        if action == "confirm":
            await self.dispatch.record_response_started(
                order.order_id, user.user_id
            )
        if action == "s_price" and order.price > 0 and self.start_price_entry:
            await self.start_price_entry(order.order_id)
            await self._answer(incoming)
            await prompt_offer_price(
                self.messenger,
                self.texts,
                self.locale,
                incoming.chat_id,
                order.order_id,
            )
            return None
        reason = (
            SKIP_REASONS.get(action.removeprefix("s_"))
            if action.startswith("s_")
            else None
        )
        if reason:
            result = await self.dispatch.record_skip(
                order.order_id,
                user.user_id,
                rejection_reason=reason,
                channel=incoming.user.messenger_type,
                only_unanswered=True,
            )
            if result.intake_closed is True:
                return render_public_offer(order, self.locale, "closed")
            return await self._stored_view(order, user) or render_public_offer(
                order, self.locale, "skipped"
            )
        view = action if action in VIEWS else "open"
        return render_public_offer(order, self.locale, view)

    async def finish_direct(
        self,
        incoming: IncomingCallback,
        order: Order,
        user: User,
        interactions: InteractionService,
        other_client: MessengerClient | None,
        *,
        manager_id: UUID | None = None,
    ) -> None:
        await self._edit(
            incoming,
            order,
            user,
            render_saved_offer(order, self.locale),
            terminal=True,
        )
        await self._notify_direct_client(
            incoming, order, user, interactions, other_client, manager_id
        )

    async def _notify_direct_client(
        self,
        incoming: IncomingCallback,
        order: Order,
        user: User,
        interactions: InteractionService,
        other_client: MessengerClient | None,
        manager_id: UUID | None,
    ) -> None:
        client = await self.users.get_user_by_id(order.advertiser_id)
        profile = await self.profiles.get_blogger_profile(user.user_id)
        profile_url = https_link(profile.instagram_url) if profile else None
        if not (profile and profile_url):
            return
        recipients = [client] if client else []
        if manager_id is not None and manager_id != order.advertiser_id:
            manager = await self.users.get_user_by_id(manager_id)
            if manager is not None:
                recipients.append(manager)
        channel = incoming.user.messenger_type
        transports = (
            {
                MessengerType.TELEGRAM: self.messenger,
                MessengerType.MAX: other_client,
            }
            if channel == MessengerType.TELEGRAM
            else {
                MessengerType.MAX: self.messenger,
                MessengerType.TELEGRAM: other_client,
            }
        )
        sent: set[tuple[MessengerType, str]] = set()
        client_delivered = False
        for recipient in recipients:
            delivered = await self._deliver_direct_contact(
                order, user, profile, profile_url, recipient, transports, sent
            )
            if delivered and recipient.user_id == order.advertiser_id:
                client_delivered = True
        if client_delivered:
            await interactions.reactivate_or_create_for_contacts_sent(
                order_id=order.order_id,
                blogger_id=user.user_id,
                advertiser_id=order.advertiser_id,
            )

    async def _deliver_direct_contact(
        self, order, user, profile, profile_url, recipient, transports, sent
    ) -> bool:
        addresses = {
            MessengerType.TELEGRAM: recipient.telegram_id,
            MessengerType.MAX: recipient.max_chat_id,
        }
        available = [
            (target, transports[target], addresses[target])
            for target in dict.fromkeys((recipient.messenger_type, *addresses))
            if transports.get(target) and addresses.get(target)
        ]
        if not available:
            return False
        channel, sender, address = available[0]
        assert sender is not None and address is not None
        destination = (channel, address)
        if destination in sent:
            return False
        # An uncertain send must not be repeated to the same destination.
        sent.add(destination)
        locale = recipient.language or "ru"
        text = client_contact_text(
            order_title=(order.creator_offer_card or {}).get("title", ""),
            name=user.username,
            phone=profile.phone,
            locale=locale,
        )
        title, _, body = text.partition("\n")
        links = client_contact_links(
            profile=profile_url, handle=user.telegram, locale=locale
        )
        card = OfferCard(
            f"<b>{escape(title)}</b>\n{escape(body)}",
            Keyboard(
                KeyboardKind.INLINE,
                [[Button(label, url=url)] for label, url in links],
            ),
        )
        try:
            await cast(OfferCardTransport, sender).send_offer_card(
                address, card, None
            )
        except Exception as exc:
            logger.warning(
                "Direct creator contact delivery failed",
                extra={
                    "order_id": str(order.order_id),
                    "error": type(exc).__name__,
                },
            )
            return False
        return True

    async def _edit(
        self,
        incoming: IncomingCallback,
        order: Order,
        user: User,
        card: OfferCard,
        *,
        terminal: bool,
    ) -> None:
        assert incoming.message_id is not None
        try:
            await cast(OfferCardTransport, self.messenger).edit_offer_card(
                incoming.chat_id, incoming.message_id, card
            )
        except Exception as exc:
            logger.warning(
                "Failed to update creator offer card",
                extra={
                    "order_id": str(order.order_id),
                    "error": type(exc).__name__,
                },
            )
            return
        if terminal:
            await self.dispatch.offer_dispatch_repo.mark_creator_card_updated(
                order.order_id, user.user_id, incoming.message_id
            )
