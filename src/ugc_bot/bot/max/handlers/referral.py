"""Max handlers for referral: /referral, /referral_list and payout button."""

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from ugc_bot.application.errors import LegacyPayoutBlockedError
from ugc_bot.application.messenger.dto import (
    Button,
    IncomingCallback,
    IncomingMessage,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.ports import (
    CountryRepository,
    PayoutRequestRepository,
    TransactionManager,
    UserReferralBindingRepository,
)
from ugc_bot.application.services.legacy_payout_service import (
    LegacyPayoutResult,
    create_legacy_payout_request,
)
from ugc_bot.application.services.referral_income_service import (
    ReferralIncomeService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.max.router import MaxRouter
from ugc_bot.bot.payout_messages import LEGACY_PAYOUT_BLOCKED_TEXT
from ugc_bot.bot.telegram.handlers.referral import (
    MULTICURRENCY_TEXT_KEYS,
    PAYOUT_PAID_CALLBACK_PREFIX,
    REFERRAL_LIST_PAGE_SIZE,
    REFERRAL_PAYOUT_CALLBACK,
    REFERRAL_STATS_KEYS,
    _build_approx_line,
    _build_currency_symbols,
    _build_mc_payout_keyboard,
    _build_mc_stats_text,
    _parse_payout_request_id_from_callback,
    _safe_format,
)
from ugc_bot.domain.entities import PayoutRequest
from ugc_bot.domain.enums import MessengerType, PayoutRequestStatus, UserStatus

router = MaxRouter()
logger = logging.getLogger(__name__)


async def _notify_support_about_payout(
    messenger_client: Any,
    request: PayoutRequest,
    request_amount: Decimal,
    currency: str,
    currency_sym: str,
    username: str | None,
    support_chat_id: str,
    admin_base_url: str,
) -> bool:
    """Send payout request notification to support channel.

    Returns True if the message was sent successfully, False otherwise.
    """
    support_text = (
        f"Запрос на выплату\n\n"
        f"Пользователь: {username or '—'}\n"
        f"Request ID: {request.request_id}\n"
        f"Сумма: {request_amount:.2f} {currency_sym}\n"
        f"Валюта: {currency}\n"
        f"Дата: {request.requested_at.strftime('%Y-%m-%d %H:%M')}"
    )
    admin_base = admin_base_url.strip().rstrip("/")
    if admin_base:
        edit_url = (
            f"{admin_base}/payout-request-model/details/{request.request_id}"
        )
        support_text += f"\n\nОткрыть в админке: {edit_url}"
    payout_paid_keyboard = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text="Выплачено",
                    callback_data=f"{PAYOUT_PAID_CALLBACK_PREFIX}{request.request_id}",
                )
            ]
        ],
    )
    try:
        await messenger_client.send_text(
            chat_id=support_chat_id,
            text=support_text,
            keyboard=payout_paid_keyboard,
        )
        return True
    except Exception as e:
        logger.error(
            "Failed to send payout request to support channel",
            extra={
                "user_id": str(request.user_id),
                "request_id": str(request.request_id),
                "error": str(e),
            },
        )
        return False


@router.message(lambda m: bool(m.text and m.text.strip() == "/referral"))
async def referral_command(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle /referral — show referral stats."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    referral_income_service: ReferralIncomeService = deps[
        "referral_income_service"
    ]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    locale: str = deps.get("locale", "ru")
    country_repo: CountryRepository | None = deps.get("country_repo")
    exchange_rate_service = deps.get("exchange_rate_service")

    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_referral_blocked",
            "msg_referral_pause",
        ],
        locale,
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_profile_not_found_role", ""),
        )
        return
    if user.status == UserStatus.BLOCKED:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_referral_blocked", ""),
        )
        return
    if user.status == UserStatus.PAUSE:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_referral_pause", ""),
        )
        return

    mc_stats = await referral_income_service.get_multicurrency_stats(
        user.user_id
    )
    currency_symbols = await _build_currency_symbols(country_repo)

    stats_texts = await bot_texts_service.get_many(
        list(REFERRAL_STATS_KEYS)
        + list(MULTICURRENCY_TEXT_KEYS)
        + ["msg_referral_link_intro", "btn_payout"],
        locale,
    )

    approx_line = await _build_approx_line(
        mc_stats,
        user,
        country_repo,
        exchange_rate_service,
        currency_symbols,
        stats_texts,
    )
    text = _build_mc_stats_text(
        mc_stats, currency_symbols, stats_texts, approx_line
    )

    max_bot_username = (config.referral.max_referral_bot_username or "").strip()
    if max_bot_username and user.referral_code:
        link = (
            f"https://max.ru/{max_bot_username}?start=ref_{user.referral_code}"
        )
        intro = stats_texts.get("msg_referral_link_intro", "")
        text = f"{intro}\n{link}\n\n{text}"

    payout_btn_tpl = stats_texts.get(
        "btn_referral_payout_currency", "Withdraw {amount} {symbol}"
    )
    keyboard = _build_mc_payout_keyboard(
        mc_stats, currency_symbols, payout_btn_tpl
    )

    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=keyboard,
    )


@router.callback(
    lambda cb: bool(
        cb.data is not None
        and cb.data.startswith(REFERRAL_PAYOUT_CALLBACK + ":")
    )
)
async def payout_button_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle payout button — create payout request and notify support."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    referral_income_service: ReferralIncomeService = deps[
        "referral_income_service"
    ]
    payout_request_repo: PayoutRequestRepository = deps["payout_request_repo"]
    transaction_manager: TransactionManager = deps["transaction_manager"]
    bot_texts_service = deps["bot_texts_service"]
    config = deps["config"]
    locale: str = deps.get("locale", "ru")
    country_repo: CountryRepository | None = deps.get("country_repo")

    raw_data = incoming.data or ""
    parts = raw_data.split(":")
    currency = parts[2] if len(parts) >= 3 and parts[2] else "RUB"

    payout_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found",
            "msg_referral_payout_blocked",
            "msg_referral_payout_pause",
            "msg_referral_payout_today_currency",
            "msg_referral_payout_today",
        ],
        locale,
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=payout_msgs.get("msg_user_not_found", ""),
        )
        return
    if user.status == UserStatus.BLOCKED:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=payout_msgs.get("msg_referral_payout_blocked", ""),
        )
        return
    if user.status == UserStatus.PAUSE:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=payout_msgs.get("msg_referral_payout_pause", ""),
        )
        return

    currency_symbols = await _build_currency_symbols(country_repo)
    currency_sym = currency_symbols.get(currency, currency)

    mc_stats = await referral_income_service.get_multicurrency_stats(
        user.user_id
    )
    if mc_stats.has_request_today_by_currency.get(currency, False):
        msg = payout_msgs.get(
            "msg_referral_payout_today_currency",
            payout_msgs.get("msg_referral_payout_today", ""),
        )
        msg = _safe_format(msg, currency=currency)
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg,
            show_alert=True,
        )
        return

    available = mc_stats.available_by_currency.get(currency, Decimal("0"))
    pending = mc_stats.pending_by_currency.get(currency, Decimal("0"))
    if pending > 0 or available <= 0:
        msg = await bot_texts_service.get(
            "msg_referral_payout_unavailable", locale
        )
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=msg,
            show_alert=True,
        )
        return
    request_amount = available.quantize(Decimal("0.01"))

    request = PayoutRequest(
        request_id=uuid4(),
        user_id=user.user_id,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
        amount=request_amount,
        currency=currency,
    )

    outcome = await create_legacy_payout_request(
        request, payout_request_repo, transaction_manager
    )
    if outcome != LegacyPayoutResult.CREATED:
        logger.info(
            "Legacy payout request not created",
            extra={
                "user_id": str(user.user_id),
                "currency": currency,
                "outcome": outcome.value,
            },
        )
        duplicate_msg = payout_msgs.get(
            "msg_referral_payout_today_currency",
            payout_msgs.get("msg_referral_payout_today", ""),
        )
        errors = {
            LegacyPayoutResult.DUPLICATE: _safe_format(
                duplicate_msg, currency=currency
            ),
            LegacyPayoutResult.DISPUTED: LEGACY_PAYOUT_BLOCKED_TEXT,
        }
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=errors[outcome],
            show_alert=True,
        )
        return

    support_chat_id = config.referral.referral_support_chat_id.strip()
    support_notified = True
    if support_chat_id:
        support_notified = await _notify_support_about_payout(
            messenger_client,
            request,
            request_amount,
            currency,
            currency_sym,
            user.username,
            support_chat_id,
            (config.admin.admin_base_url or ""),
        )

    if support_chat_id and not support_notified:
        reply_text = await bot_texts_service.get(
            "msg_referral_payout_notify_failed", locale
        )
    else:
        reply_text = await bot_texts_service.get(
            "msg_referral_payout_sent", locale
        )

    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text=reply_text,
        show_alert=True,
    )


@router.callback(
    lambda cb: bool(cb.data and cb.data.startswith(PAYOUT_PAID_CALLBACK_PREFIX))
)
async def payout_paid_callback(
    incoming: IncomingCallback, deps: dict[str, Any]
) -> None:
    """Handle admin click on paid — set payout request status to PAID."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    payout_request_repo: PayoutRequestRepository = deps["payout_request_repo"]
    transaction_manager: TransactionManager = deps["transaction_manager"]

    request_id = _parse_payout_request_id_from_callback(incoming.data or "")
    if request_id is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Неверный формат заявки.",
            show_alert=True,
        )
        return

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None or not user.admin:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Доступ запрещён.",
            show_alert=True,
        )
        return

    updated = False
    try:
        async with transaction_manager.transaction() as session:
            request = await payout_request_repo.get_by_id(
                request_id, session=session
            )
            if request is None:
                await messenger_client.answer_callback(
                    callback_id=incoming.callback_id,
                    text="Заявка не найдена.",
                    show_alert=True,
                )
                return
            if request.status != PayoutRequestStatus.PENDING:
                await messenger_client.answer_callback(
                    callback_id=incoming.callback_id,
                    text="Заявка уже обработана.",
                    show_alert=True,
                )
                return
            updated = await payout_request_repo.update_status(
                request_id, PayoutRequestStatus.PAID, session=session
            )
    except LegacyPayoutBlockedError:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text=LEGACY_PAYOUT_BLOCKED_TEXT,
            show_alert=True,
        )
        return

    if updated and incoming.message_id:
        try:
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
            )
        except Exception:
            logger.warning(
                "Failed to clear reply markup",
                exc_info=True,
            )
    await messenger_client.answer_callback(
        callback_id=incoming.callback_id,
        text="Выплачено" if updated else "Ошибка обновления.",
        show_alert=not updated,
    )
    if updated:
        logger.info(
            "Payout request marked as paid via admin button",
            extra={
                "request_id": str(request_id),
                "admin_chat_id": incoming.chat_id,
            },
        )


@router.message(
    lambda m: bool(m.text and m.text.strip().startswith("/referral_list"))
)
async def referral_list_command(
    incoming: IncomingMessage, deps: dict[str, Any]
) -> None:
    """Handle /referral_list — show list of referred users."""
    messenger_client = deps["messenger_client"]
    user_role_service: UserRoleService = deps["user_role_service"]
    user_referral_binding_repo: UserReferralBindingRepository = deps[
        "user_referral_binding_repo"
    ]
    transaction_manager: TransactionManager = deps["transaction_manager"]
    bot_texts_service = deps["bot_texts_service"]
    locale: str = deps.get("locale", "ru")

    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_referral_blocked",
            "msg_referral_pause",
        ],
        locale,
    )

    user = await user_role_service.get_user(
        external_id=incoming.user.external_id,
        messenger_type=MessengerType.MAX,
    )
    if user is None:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_profile_not_found_role", ""),
        )
        return
    if user.status == UserStatus.BLOCKED:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_referral_blocked", ""),
        )
        return
    if user.status == UserStatus.PAUSE:
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=allow_msgs.get("msg_referral_pause", ""),
        )
        return

    async with transaction_manager.transaction() as session:
        total_bindings = await user_referral_binding_repo.count_by_referrer(
            user.user_id, session=session
        )
        page = 0
        bindings = await user_referral_binding_repo.list_by_referrer(
            user.user_id,
            limit=REFERRAL_LIST_PAGE_SIZE,
            offset=page * REFERRAL_LIST_PAGE_SIZE,
            session=session,
        )

    if not bindings and total_bindings == 0:
        msg_empty = await bot_texts_service.get(
            "msg_referral_list_empty", locale
        )
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=msg_empty
        )
        return

    lines: list[str] = []
    for binding in bindings:
        referred = await user_role_service.get_user_by_id(
            binding.referred_user_id,
        )
        name = (referred.username if referred else None) or str(
            binding.referred_user_id
        )[:8]
        lines.append(f"- {name}")

    text = "\n".join(lines)
    if total_bindings > REFERRAL_LIST_PAGE_SIZE:
        text += f"\n\n({total_bindings} всего)"

    await messenger_client.send_text(chat_id=incoming.chat_id, text=text)
