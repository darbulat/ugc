"""Handlers for referral: /referral, /referral_list and payout button."""

import contextlib
import logging
import string
from datetime import datetime, timezone
from decimal import Decimal
from math import ceil
from uuid import UUID, uuid4

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ugc_bot.application.errors import LegacyPayoutBlockedError
from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import (
    MessengerClient,
    MessengerEventAdapter,
)
from ugc_bot.application.ports import (
    CountryRepository,
    PayoutRequestRepository,
    TransactionManager,
    UserReferralBindingRepository,
    UserReferralPendingRepository,
    UserRepository,
)
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.exchange_rate_service import (
    ExchangeRateService,
)
from ugc_bot.application.services.legacy_payout_service import (
    LegacyPayoutResult,
    create_legacy_payout_request,
)
from ugc_bot.application.services.referral_income_service import (
    MultiCurrencyReferralStats,
    ReferralIncomeService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.payout_messages import LEGACY_PAYOUT_BLOCKED_TEXT
from ugc_bot.bot.telegram.handlers.utils import (
    get_user_and_ensure_allowed,
    get_user_and_ensure_allowed_callback,
    resolve_messenger_dependencies,
)
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import PayoutRequest, User
from ugc_bot.domain.enums import PayoutRequestStatus

router = Router()
logger = logging.getLogger(__name__)


def _safe_format(template: str, **kwargs: str) -> str:
    """Format string substituting known keys, logging unknown placeholders."""
    fieldnames = {
        fname
        for _, fname, _, _ in string.Formatter().parse(template)
        if fname is not None
    }
    unknown = fieldnames - set(kwargs)
    if unknown:
        logger.warning("Unknown placeholders in template: %s", unknown)
    mapping = {f: "" for f in fieldnames}
    mapping.update(kwargs)
    return template.format_map(mapping)


REFERRAL_PAYOUT_CALLBACK = "referral:payout"
PAYOUT_PAID_CALLBACK_PREFIX = "payout_paid:"
REFERRAL_LIST_CALLBACK_PREFIX = "referral_list:"
REFERRAL_LIST_PAGE_SIZE = 10
REFERRAL_LIST_PENDING_LIMIT = 50


def _parse_telegram_arg_from_command(
    text: str | None, command: str
) -> str | None:
    """First arg after /command, normalized (strip, strip @). None if empty."""
    if not text:
        return None
    parts = (text or "").strip().split()
    if len(parts) < 2:
        return None
    arg = parts[1].strip().lstrip("@")
    return arg if arg else None


async def _resolve_referral_target_user(
    current_user: User,
    telegram_arg: str | None,
    user_role_service: UserRoleService,
    messenger_client: MessengerClient,
    chat_id: str,
    user_not_found_msg: str = "Пользователь не найден.",
) -> User | None:
    """Resolve target user for referral commands.

    Returns None only if admin passed @username and that user was not found
    (error message already sent).
    """
    if not current_user.admin:
        return current_user
    if not telegram_arg:
        return current_user
    target = await user_role_service.get_user_by_telegram(telegram_arg)
    if target is None:
        await messenger_client.send_text(
            chat_id=chat_id,
            text=user_not_found_msg,
        )
        return None
    return target


REFERRAL_STATS_KEYS = (
    "lbl_referral_stats",
    "lbl_referral_creators",
    "lbl_referral_orders",
    "lbl_referral_income_month",
    "lbl_referral_income_total",
    "lbl_referral_paid",
    "lbl_referral_balance",
)

MULTICURRENCY_TEXT_KEYS = (
    "lbl_referral_income_line",
    "lbl_referral_approx_total",
    "lbl_referral_paid_currency",
    "lbl_referral_pending_currency",
    "btn_referral_payout_currency",
)


async def _build_currency_symbols(
    country_repo: CountryRepository | None,
) -> dict[str, str]:
    """Build currency_code -> currency_symbol mapping from enabled countries."""
    if country_repo is None:
        return {}
    countries = await country_repo.list_enabled()
    return {c.currency_code: c.currency_symbol for c in countries}


def _build_mc_stats_text(
    mc_stats: MultiCurrencyReferralStats,
    currency_symbols: dict[str, str],
    texts: dict[str, str],
    approx_line: str = "",
) -> str:
    """Build multi-currency referral stats text."""
    income_tpl = texts.get(
        "lbl_referral_income_line", "• {amount} {symbol} ({count} orders)"
    )
    income_lines: list[str] = []
    for currency, amount in mc_stats.income_by_currency.items():
        sym = currency_symbols.get(currency, currency)
        count = mc_stats.orders_by_currency.get(currency, 0)
        income_lines.append(
            income_tpl.format(amount=f"{amount:.2f}", symbol=sym, count=count)
        )

    paid_tpl = texts.get(
        "lbl_referral_paid_currency", "Paid: {amount} {symbol}"
    )
    pending_tpl = texts.get(
        "lbl_referral_pending_currency", "Pending: {amount} {symbol}"
    )
    paid_lines: list[str] = []
    for currency in sorted(
        set(mc_stats.paid_by_currency) | set(mc_stats.pending_by_currency)
    ):
        sym = currency_symbols.get(currency, currency)
        paid_amt = mc_stats.paid_by_currency.get(currency, Decimal("0"))
        pending_amt = mc_stats.pending_by_currency.get(currency, Decimal("0"))
        if paid_amt > 0:
            paid_lines.append(
                paid_tpl.format(amount=f"{paid_amt:.2f}", symbol=sym)
            )
        if pending_amt > 0:
            paid_lines.append(
                pending_tpl.format(amount=f"{pending_amt:.2f}", symbol=sym)
            )

    stats_title = texts.get("lbl_referral_stats", "")
    creators_lbl = texts.get("lbl_referral_creators", "")
    text_parts = [
        f"{stats_title}\n",
        f"{creators_lbl}: {mc_stats.creators_count}",
    ]
    if income_lines:
        text_parts.append("")
        text_parts.extend(income_lines)
    if approx_line:
        text_parts.append(approx_line)
    if paid_lines:
        text_parts.append("")
        text_parts.extend(paid_lines)
    return "\n".join(text_parts)


async def _build_approx_line(
    mc_stats: MultiCurrencyReferralStats,
    target: User,
    country_repo: CountryRepository | None,
    exchange_rate_service: ExchangeRateService | None,
    currency_symbols: dict[str, str],
    texts: dict[str, str],
) -> str:
    """Compute approximate total in referrer's currency, or empty string."""
    if exchange_rate_service is None or not mc_stats.available_by_currency:
        return ""
    referrer_currency = "RUB"
    country_code = getattr(target, "country", None)
    if country_code and country_repo:
        country = await country_repo.get_by_code(country_code)
        if country:
            referrer_currency = country.currency_code
    approx_total = await exchange_rate_service.convert_many(
        mc_stats.available_by_currency, referrer_currency
    )
    if approx_total is None:
        return ""
    approx_sym = currency_symbols.get(referrer_currency, referrer_currency)
    approx_tpl = texts.get(
        "lbl_referral_approx_total",
        "≈ {amount} {symbol} (approximate total)",
    )
    return approx_tpl.format(amount=f"{approx_total:.2f}", symbol=approx_sym)


def _build_mc_payout_keyboard(
    mc_stats: MultiCurrencyReferralStats,
    currency_symbols: dict[str, str],
    btn_tpl: str,
) -> Keyboard | None:
    """Build per-currency payout buttons keyboard."""
    payout_rows: list[list[Button]] = []
    for currency, available in mc_stats.available_by_currency.items():
        if available <= 0:
            continue
        has_pending = (
            mc_stats.pending_by_currency.get(currency, Decimal("0")) > 0
        )
        has_today = mc_stats.has_request_today_by_currency.get(currency, False)
        if has_pending or has_today:
            continue
        sym = currency_symbols.get(currency, currency)
        btn_text = btn_tpl.format(amount=f"{available:.2f}", symbol=sym)
        payout_rows.append(
            [
                Button(
                    text=btn_text,
                    callback_data=f"{REFERRAL_PAYOUT_CALLBACK}:{currency}",
                )
            ]
        )
    if not payout_rows:
        return None
    return Keyboard(kind=KeyboardKind.INLINE, rows=payout_rows)


@router.message(Command("referral"))
async def referral_command(
    message: Message,
    user_role_service: UserRoleService,
    referral_income_service: ReferralIncomeService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    country_repo: CountryRepository | None = None,
    exchange_rate_service: ExchangeRateService | None = None,
) -> None:
    """Handle /referral — stats; admin may pass @username to view another."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_referral_blocked",
            "msg_referral_pause",
        ],
        locale,
    )
    msg_not_found = allow_msgs.get("msg_profile_not_found_role", "")
    msg_blocked = allow_msgs.get("msg_referral_blocked", "")
    msg_pause = allow_msgs.get("msg_referral_pause", "")
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=msg_not_found,
        blocked_msg=msg_blocked,
        pause_msg=msg_pause,
    )
    if user is None:
        return

    telegram_arg = _parse_telegram_arg_from_command(incoming.text, "referral")
    user_not_found = await bot_texts_service.get("msg_user_not_found", locale)
    target = await _resolve_referral_target_user(
        user,
        telegram_arg,
        user_role_service,
        messenger_client,
        incoming.chat_id,
        user_not_found_msg=user_not_found,
    )
    if target is None:
        return

    mc_stats = await referral_income_service.get_multicurrency_stats(
        target.user_id
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
        target,
        country_repo,
        exchange_rate_service,
        currency_symbols,
        stats_texts,
    )
    text = _build_mc_stats_text(
        mc_stats, currency_symbols, stats_texts, approx_line
    )

    is_own_view = target.user_id == user.user_id
    bot_username = (config.referral.referral_bot_username or "").strip()
    if is_own_view and bot_username and target.referral_code:
        link = f"https://t.me/{bot_username}?start=ref_{target.referral_code}"
        intro = stats_texts.get("msg_referral_link_intro", "")
        text = f"{intro}\n{link}\n\n{text}"

    keyboard: Keyboard | None = None
    if is_own_view:
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


@router.callback_query(
    lambda c: (
        c.data is not None and c.data.startswith(REFERRAL_PAYOUT_CALLBACK + ":")
    )
)
async def payout_button_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    referral_income_service: ReferralIncomeService,
    payout_request_repo: PayoutRequestRepository,
    transaction_manager: TransactionManager,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
    country_repo: CountryRepository | None = None,
) -> None:
    """Handle 'Выплатить' button — create payout request and notify support."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale

    # Parse currency from callback data: "referral:payout:USD" -> "USD"
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
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=payout_msgs.get("msg_user_not_found", ""),
        blocked_msg=payout_msgs.get("msg_referral_payout_blocked", ""),
        pause_msg=payout_msgs.get("msg_referral_payout_pause", ""),
    )
    if user is None:
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
        support_text = (
            f"💰 Запрос на выплату\n\n"
            f"Пользователь: {user.username or '—'}\n"
            f"telegram: @{user.telegram or '—'}\n"
            f"Request ID: {request.request_id}\n"
            f"Сумма: {request_amount:.2f} {currency_sym}\n"
            f"Валюта: {currency}\n"
            f"Дата: {request.requested_at.strftime('%Y-%m-%d %H:%M')}"
        )
        admin_base = (config.admin.admin_base_url or "").strip()
        if admin_base:
            base = admin_base.rstrip("/")
            edit_url = (
                f"{base}/payout-request-model/details/{request.request_id}"
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
        support_notified = True
        try:
            await messenger_client.send_text(
                chat_id=support_chat_id,
                text=support_text,
                keyboard=payout_paid_keyboard,
            )
        except Exception as e:
            support_notified = False
            logger.error(
                "Failed to send payout request to support channel",
                extra={
                    "user_id": str(user.user_id),
                    "request_id": str(request.request_id),
                    "error": str(e),
                },
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


def _parse_payout_request_id_from_callback(data: str) -> UUID | None:
    """Parse request_id from payout_paid callback. None if invalid."""
    if not data or not data.startswith(PAYOUT_PAID_CALLBACK_PREFIX):
        return None
    raw = data[len(PAYOUT_PAID_CALLBACK_PREFIX) :].strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


@router.callback_query(
    lambda c: c.data and c.data.startswith(PAYOUT_PAID_CALLBACK_PREFIX)
)
async def payout_paid_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    payout_request_repo: PayoutRequestRepository,
    transaction_manager: TransactionManager,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle admin click on 'Выплачено' — set payout request status to PAID."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    request_id = _parse_payout_request_id_from_callback(incoming.data or "")
    if request_id is None:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Неверный формат заявки.",
            show_alert=True,
        )
        return
    external_id = incoming.user.external_id
    if not external_id:
        await messenger_client.answer_callback(
            callback_id=incoming.callback_id,
            text="Ошибка: пользователь не определён.",
            show_alert=True,
        )
        return
    user = await user_role_service.get_user(
        external_id=external_id,
        messenger_type=incoming.user.messenger_type,
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
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id,
                message_id=incoming.message_id,
                keyboard=None,
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


@router.message(Command("referral_list"))
async def referral_list_command(
    message: Message,
    user_role_service: UserRoleService,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle /referral_list — list; admin may pass @username for another."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    incoming = event_adapter.from_message(message)
    locale = user_locale
    allow_msgs = await bot_texts_service.get_many(
        [
            "msg_profile_not_found_role",
            "msg_referral_blocked",
            "msg_referral_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=allow_msgs.get("msg_profile_not_found_role", ""),
        blocked_msg=allow_msgs.get("msg_referral_blocked", ""),
        pause_msg=allow_msgs.get("msg_referral_pause", ""),
    )
    if user is None:
        return

    telegram_arg = _parse_telegram_arg_from_command(
        incoming.text, "referral_list"
    )
    user_not_found = await bot_texts_service.get("msg_user_not_found", locale)
    target = await _resolve_referral_target_user(
        user,
        telegram_arg,
        user_role_service,
        messenger_client,
        incoming.chat_id,
        user_not_found_msg=user_not_found,
    )
    if target is None:
        return

    async with transaction_manager.transaction() as session:
        total_bindings = await user_referral_binding_repo.count_by_referrer(
            target.user_id, session=session
        )
        total_pending = await user_referral_pending_repo.count_by_referrer(
            target.user_id, session=session
        )
    if total_bindings == 0 and total_pending == 0:
        msg = await bot_texts_service.get("msg_referral_no_users", locale)
        await messenger_client.send_text(
            chat_id=incoming.chat_id,
            text=msg,
        )
        return

    list_texts = await bot_texts_service.get_many(
        list(REFERRAL_LIST_TEXTS_KEYS), locale
    )
    referrer_user_id_for_callback = (
        target.user_id if target.user_id != user.user_id else None
    )
    text, keyboard = await _render_referral_list_page(
        referrer_user_id=target.user_id,
        page=1,
        user_referral_binding_repo=user_referral_binding_repo,
        user_referral_pending_repo=user_referral_pending_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
        transaction_manager=transaction_manager,
        referrer_user_id_for_callback=referrer_user_id_for_callback,
        texts=list_texts,
    )
    await messenger_client.send_text(
        chat_id=incoming.chat_id,
        text=text,
        keyboard=keyboard,
    )


@router.callback_query(
    lambda c: c.data and c.data.startswith(REFERRAL_LIST_CALLBACK_PREFIX)
)
async def referral_list_pagination_callback(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle pagination for /referral_list."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    list_allow_msgs = await bot_texts_service.get_many(
        [
            "msg_user_not_found",
            "msg_referral_list_blocked",
            "msg_referral_list_pause",
        ],
        locale,
    )
    user = await get_user_and_ensure_allowed_callback(
        incoming,
        messenger_client,
        user_role_service,
        user_not_found_msg=list_allow_msgs.get("msg_user_not_found", ""),
        blocked_msg=list_allow_msgs.get("msg_referral_list_blocked", ""),
        pause_msg=list_allow_msgs.get("msg_referral_list_pause", ""),
    )
    if user is None:
        return

    raw = (
        (incoming.data or "")
        .replace(REFERRAL_LIST_CALLBACK_PREFIX, "", 1)
        .strip()
    )
    parts = raw.split(":", 1)
    page_str = (parts[0] or "").strip()
    user_id_str = (parts[1] or "").strip() if len(parts) > 1 else ""
    try:
        page = int(page_str or "1")
    except ValueError:
        page = 1

    referrer_user_id: UUID
    if user_id_str:
        try:
            referrer_user_id = UUID(user_id_str)
        except ValueError:
            referrer_user_id = user.user_id
        else:
            if not user.admin:
                msg = await bot_texts_service.get(
                    "msg_referral_access_denied", locale
                )
                await messenger_client.answer_callback(
                    callback_id=incoming.callback_id,
                    text=msg,
                    show_alert=True,
                )
                return
    else:
        referrer_user_id = user.user_id

    referrer_user_id_for_callback = (
        referrer_user_id if referrer_user_id != user.user_id else None
    )
    list_texts = await bot_texts_service.get_many(
        list(REFERRAL_LIST_TEXTS_KEYS), locale
    )
    text, keyboard = await _render_referral_list_page(
        referrer_user_id=referrer_user_id,
        page=page,
        user_referral_binding_repo=user_referral_binding_repo,
        user_referral_pending_repo=user_referral_pending_repo,
        user_repo=user_repo,
        referral_income_service=referral_income_service,
        transaction_manager=transaction_manager,
        referrer_user_id_for_callback=referrer_user_id_for_callback,
        texts=list_texts,
    )
    if incoming.message_id:
        await messenger_client.edit_text(
            chat_id=incoming.chat_id,
            message_id=incoming.message_id,
            text=text,
            keyboard=keyboard,
        )
    await messenger_client.answer_callback(callback_id=incoming.callback_id)


def _user_display_name(telegram: str | None, username: str | None) -> str:
    """Format user for list display: @telegram or username or placeholder."""
    if telegram:
        return f"@{telegram}"
    return username or "—"


async def _build_referral_block1(
    *,
    referrer_user_id: UUID,
    page: int,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    session: object,
    texts: dict[str, str] | None = None,
) -> tuple[list[str], int, int, int]:
    """Build block 1 (bindings). Returns (lines, total_pages, total, page)."""
    t = texts or {}
    total_bindings = await user_referral_binding_repo.count_by_referrer(
        referrer_user_id, session=session
    )
    if total_bindings == 0:
        empty = t.get("msg_referral_list_empty", "Ваши рефералы: пока никого.")
        return ([empty], 1, 0, 1)
    total_pages = max(1, ceil(total_bindings / REFERRAL_LIST_PAGE_SIZE))
    page = max(1, min(page, total_pages))
    offset = (page - 1) * REFERRAL_LIST_PAGE_SIZE
    bindings = list(
        await user_referral_binding_repo.list_by_referrer(
            referrer_user_id,
            offset=offset,
            limit=REFERRAL_LIST_PAGE_SIZE,
            session=session,
        )
    )
    referred_ids = [b.referred_user_id for b in bindings]
    users_map = await user_repo.get_by_ids(referred_ids, session=session)
    completed_map = (
        await referral_income_service.count_completed_orders_by_user_ids(
            referred_ids, session=session
        )
    )
    names = []
    for b in bindings:
        u = users_map.get(b.referred_user_id)
        names.append(
            _user_display_name(
                u.telegram if u else None,
                u.username if u else None,
            )
        )
    title_tpl = t.get(
        "msg_referral_list_title",
        "Ваши рефералы (страница {page}/{total_pages}):",
    )
    title = title_tpl.format(page=page, total_pages=total_pages)
    lines = [title]
    orders_done = t.get("lbl_referral_orders_done", "выполнено заказов")
    for idx, (binding, name) in enumerate(
        zip(bindings, names, strict=True), start=offset + 1
    ):
        completed = completed_map.get(binding.referred_user_id, 0)
        lines.append(f"{idx}. {name} — {orders_done}: {completed}")
    return lines, total_pages, total_bindings, page


async def _build_pending_block2(
    *,
    referrer_user_id: UUID,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    session: object,
    texts: dict[str, str] | None = None,
) -> list[str]:
    """Build block 2 lines (pending users without creator profile)."""
    t = texts or {}
    lines = [
        t.get(
            "msg_referral_pending_block",
            "Не заполнили профиль креатора (напоминайте заполнить):",
        )
    ]
    pending_count = await user_referral_pending_repo.count_by_referrer(
        referrer_user_id, session=session
    )
    if pending_count == 0:
        lines.append(
            t.get("msg_referral_no_pending", "Нет рефералов без профиля.")
        )
        return lines
    pending_list = list(
        await user_referral_pending_repo.list_by_referrer(
            referrer_user_id,
            offset=0,
            limit=REFERRAL_LIST_PENDING_LIMIT,
            session=session,
        )
    )
    if pending_list:
        pending_user_ids = [p.user_id for p in pending_list]
        users_map = await user_repo.get_by_ids(
            pending_user_ids, session=session
        )
        for pending in pending_list:
            u = users_map.get(pending.user_id)
            name = _user_display_name(
                u.telegram if u else None,
                u.username if u else None,
            )
            lines.append(f"• {name}")
    return lines


def _referral_list_pagination_keyboard(
    page: int,
    total_pages: int,
    total_bindings: int,
    referrer_user_id_for_callback: UUID | None = None,
    texts: dict[str, str] | None = None,
) -> Keyboard:
    """Pagination keyboard for referral list when bindings exist."""
    t = texts or {}
    if total_bindings == 0:
        return Keyboard(kind=KeyboardKind.INLINE, rows=[])
    suffix = (
        f":{referrer_user_id_for_callback}"
        if referrer_user_id_for_callback
        else ""
    )
    nav_buttons: list[Button] = []
    prefix = REFERRAL_LIST_CALLBACK_PREFIX
    btn_back = t.get("btn_back", "Назад")
    btn_forward = t.get("btn_forward", "Вперёд")
    if page > 1:
        nav_buttons.append(
            Button(
                text=btn_back,
                callback_data=f"{prefix}{page - 1}{suffix}",
            )
        )
    if page < total_pages:
        nav_buttons.append(
            Button(
                text=btn_forward,
                callback_data=f"{prefix}{page + 1}{suffix}",
            )
        )
    rows = [nav_buttons] if nav_buttons else []
    return Keyboard(kind=KeyboardKind.INLINE, rows=rows)


REFERRAL_LIST_TEXTS_KEYS = (
    "msg_referral_list_title",
    "msg_referral_list_empty",
    "lbl_referral_orders_done",
    "msg_referral_pending_block",
    "msg_referral_no_pending",
    "btn_back",
    "btn_forward",
)


async def _render_referral_list_page(
    *,
    referrer_user_id: UUID,
    page: int,
    user_referral_binding_repo: UserReferralBindingRepository,
    user_referral_pending_repo: UserReferralPendingRepository,
    user_repo: UserRepository,
    referral_income_service: ReferralIncomeService,
    transaction_manager: TransactionManager,
    referrer_user_id_for_callback: UUID | None = None,
    texts: dict[str, str] | None = None,
) -> tuple[str, Keyboard]:
    """Build referral list: block 1 (bindings), block 2 (pending)."""
    async with transaction_manager.transaction() as session:
        (
            block1_lines,
            total_pages,
            total_bindings,
            current_page,
        ) = await _build_referral_block1(
            referrer_user_id=referrer_user_id,
            page=page,
            user_referral_binding_repo=user_referral_binding_repo,
            user_repo=user_repo,
            referral_income_service=referral_income_service,
            session=session,
            texts=texts,
        )
        block2_lines = await _build_pending_block2(
            referrer_user_id=referrer_user_id,
            user_referral_pending_repo=user_referral_pending_repo,
            user_repo=user_repo,
            session=session,
            texts=texts,
        )
    text = "\n".join(block1_lines) + "\n\n" + "\n".join(block2_lines)
    keyboard = _referral_list_pagination_keyboard(
        current_page,
        total_pages,
        total_bindings,
        referrer_user_id_for_callback=referrer_user_id_for_callback,
        texts=texts,
    )
    return text, keyboard
