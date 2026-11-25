"""Wire durable order card delivery to existing repositories and Telegram."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.application.order_notice_ports import OrderNoticeJob
from ugc_bot.application.ports import PaymentRepository, TransactionManager
from ugc_bot.application.services.admin_notification_service import (
    business_order_admins,
    notify_admins_about_order_created,
    notify_admins_about_order_paid,
)
from ugc_bot.application.services.content_moderation_service import (
    ContentModerationService,
)
from ugc_bot.application.services.order_notice_delivery import (
    OrderNoticeDelivery,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import MessengerType, PaymentStatus, UserStatus
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
)

logger = logging.getLogger(__name__)


class _RecipientRoles(UserRoleService):
    def __init__(self, user_repo, recipient: str):
        super().__init__(user_repo=user_repo)
        self.recipient = recipient

    async def list_admins(
        self, messenger_type=MessengerType.TELEGRAM, session=None
    ):
        return [
            User(
                user_id=uuid5(NAMESPACE_URL, f"order-notice:{self.recipient}"),
                telegram_id=self.recipient,
                username="admin",
                admin=True,
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
                issue_count=0,
                created_at=datetime.now(timezone.utc),
            )
        ]


class _TrackedMessenger:
    def __init__(
        self, client: MessengerClient, begin: Callable[[], Awaitable[None]]
    ):
        self.client = client
        self.begin = begin
        self.started = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.client, name)

    async def send_text(self, *args: Any, **kwargs: Any) -> Any:
        await self.begin()
        self.started = True
        return await self.client.send_text(*args, **kwargs)

    async def send_photo(self, *args: Any, **kwargs: Any) -> Any:
        await self.begin()
        self.started = True
        return await self.client.send_photo(*args, **kwargs)


async def _send_with_boundary(
    job: OrderNoticeJob,
    client: MessengerClient,
    prepare_and_send: Callable[[OrderNoticeJob, Any], Awaitable[None]],
    begin: Callable[[], Awaitable[None]],
) -> None:
    tracked = _TrackedMessenger(client, begin)
    try:
        await prepare_and_send(job, tracked)
    except DeliveryFailure as exc:
        if tracked.started:
            raise
        raise DeliveryFailure(exc.code, uncertain=False) from exc
    except Exception as exc:
        if not tracked.started:
            raise DeliveryFailure(
                "order_notice_preparation_failed", uncertain=False
            ) from exc
        raise


def _raise_classified_telegram_error(exc: Exception) -> None:
    from aiogram.exceptions import (
        TelegramBadRequest,
        TelegramForbiddenError,
        TelegramRetryAfter,
    )

    if isinstance(exc, TelegramRetryAfter):
        delay = exc.retry_after
        if isinstance(delay, int) and 0 <= delay <= 31_536_000:
            raise DeliveryFailure(
                "telegram_order_notice_rate_limited",
                uncertain=False,
                retry_after_seconds=delay,
            ) from exc
        raise DeliveryFailure(
            "telegram_order_notice_rejected", uncertain=False
        ) from exc
    if isinstance(exc, (TelegramBadRequest, TelegramForbiddenError)):
        raise DeliveryFailure(
            "telegram_order_notice_rejected", uncertain=False
        ) from exc
    raise exc


async def _order_currency_symbol(
    order: Order, config: AppConfig, repos: Mapping[str, Any]
) -> str:
    country_repo = repos.get("country_repo")
    if country_repo is not None:
        country = await country_repo.get_by_currency_code(order.currency)
        if country is not None and country.currency_symbol:
            return country.currency_symbol
    if order.currency == config.market.payment_currency:
        return config.market.currency_symbol
    return order.currency


async def _current_payment_status(
    job: OrderNoticeJob, payment_repo: PaymentRepository
) -> bool | None:
    if job.event_kind != "created":
        return None
    payment = await payment_repo.get_by_order(job.order_id)
    return payment is not None and payment.status == PaymentStatus.PAID


async def _try_count_eligible(
    order_id: UUID, loader: Callable[[UUID], Awaitable[int]] | None
) -> int | None:
    if loader is None:
        return None
    try:
        async with asyncio.timeout(2):
            return await loader(order_id)
    except Exception as exc:
        logger.info(
            "Business order creator count unavailable",
            extra={"error_type": type(exc).__name__},
        )
        return None


def build_order_notice_delivery(
    config: AppConfig,
    transactions: TransactionManager,
    messenger_client: MessengerClient,
    repos: Mapping[str, Any],
    *,
    details_loader: Callable[[Order], Awaitable[Mapping[str, Any] | None]]
    | None = None,
    eligible_count_loader: Callable[[UUID], Awaitable[int]] | None = None,
) -> OrderNoticeDelivery:
    roles = UserRoleService(user_repo=repos["user_repo"])
    repository = SqlAlchemyOrderNoticeRepository(
        config.admin.browser_paid_order_telegram_recipients
    )

    recipient_ids = config.admin.business_order_telegram_recipients

    async def recipients() -> tuple[str, ...]:
        admins = await business_order_admins(roles, recipient_ids)
        return tuple(
            user.telegram_id.strip() for user in admins if user.telegram_id
        )

    async def prepare_and_send(job: OrderNoticeJob, tracked: Any) -> None:
        if job.recipient not in recipient_ids:
            raise DeliveryFailure(
                "order_notice_recipient_ineligible", uncertain=False
            )
        order = await repos["order_repo"].get_by_id(job.order_id)
        if order is None:
            raise DeliveryFailure("order_notice_order_missing", uncertain=False)
        profile = await repos["advertiser_repo"].get_by_user_id(
            order.advertiser_id
        )
        currency_symbol = await _order_currency_symbol(order, config, repos)
        details = await details_loader(order) if details_loader else None
        payment_confirmed = await _current_payment_status(
            job, repos["payment_repo"]
        )

        eligible_count = await _try_count_eligible(
            order.order_id, eligible_count_loader
        )

        # Recheck access after preparation. Jobs may predate the allowlist.
        if job.recipient not in await recipients():
            raise DeliveryFailure(
                "order_notice_recipient_ineligible", uncertain=False
            )
        notify = (
            notify_admins_about_order_paid
            if job.event_kind == "paid"
            else notify_admins_about_order_created
        )
        try:
            await notify(
                order,
                tracked,
                _RecipientRoles(repos["user_repo"], job.recipient),
                ContentModerationService(),
                admin_base_url=config.admin.admin_base_url,
                webhook_base_url=config.webhook.webhook_base_url,
                currency_symbol=currency_symbol,
                advertiser_profile=profile,
                order_details=details,
                recipient_ids=recipient_ids,
                payment_confirmed=payment_confirmed,
                eligible_count=eligible_count,
                raise_on_error=True,
            )
        except Exception as exc:
            _raise_classified_telegram_error(exc)

    async def send(job: OrderNoticeJob) -> None:
        async def begin() -> None:
            async with transactions.transaction() as session:
                started = await repository.begin(
                    job, datetime.now(timezone.utc), session=session
                )
            if not started:
                raise DeliveryFailure(
                    "order_notice_lease_lost", uncertain=False
                )

        await _send_with_boundary(
            job, messenger_client, prepare_and_send, begin
        )

    return OrderNoticeDelivery(
        repository,
        transactions,
        send,
        recipients,
        prepares_before_send=True,
    )


def build_consultation_notice_delivery(
    config: AppConfig,
    transactions: TransactionManager,
    messenger_client: MessengerClient,
    repos: Mapping[str, Any],
) -> OrderNoticeDelivery:
    from ugc_bot.application.services.admin_notification_service import (
        order_admin_url,
    )
    from ugc_bot.domain.order_intake import CONSULTATION_MINOR
    from ugc_bot.infrastructure.db.repositories.consultation_checkout import (
        consultation_notices,
    )

    roles = UserRoleService(user_repo=repos["user_repo"])
    repository = consultation_notices(
        order_card_recipients=config.admin.business_order_telegram_recipients,
    )
    recipient_ids = (
        config.admin.browser_paid_order_telegram_recipients or frozenset()
    )

    async def recipients() -> tuple[str, ...]:
        admins = await business_order_admins(roles, recipient_ids)
        addresses = tuple(
            user.telegram_id.strip() for user in admins if user.telegram_id
        )
        return addresses if len(addresses) == len(recipient_ids) == 2 else ()

    async def prepare_and_send(job: OrderNoticeJob, tracked: Any) -> None:
        order = await repos["order_repo"].get_by_id(job.order_id)
        if order is None:
            raise DeliveryFailure("order_notice_order_missing", uncertain=False)
        if job.recipient not in await recipients():
            raise DeliveryFailure(
                "order_notice_recipient_ineligible", uncertain=False
            )
        payment = (
            "оплачена" if job.event_kind == "paid" else "добавлена к заказу"
        )
        amount = f"{CONSULTATION_MINOR // 100:,}".replace(",", " ")
        text = (
            f"Консультация UMC · {payment}\n"
            f"Заказ №{job.order_id.hex[:8].upper()} · {amount} ₽\n"
            f"Разбор запуска, ТЗ и критериев подбора блогеров, до 60 минут."
        )
        if link := order_admin_url(config.admin.admin_base_url, order):
            text += f"\n\n{link}"
        try:
            await tracked.send_text(
                chat_id=job.recipient, text=text, disable_preview=True
            )
        except Exception as exc:
            _raise_classified_telegram_error(exc)

    async def send(job: OrderNoticeJob) -> None:
        async def begin() -> None:
            async with transactions.transaction() as session:
                started = await repository.begin(
                    job, datetime.now(timezone.utc), session=session
                )
            if not started:
                raise DeliveryFailure(
                    "order_notice_lease_lost", uncertain=False
                )

        await _send_with_boundary(
            job, messenger_client, prepare_and_send, begin
        )

    return OrderNoticeDelivery(
        repository, transactions, send, recipients, prepares_before_send=True
    )
