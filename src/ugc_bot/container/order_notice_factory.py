"""Wire durable order card delivery to existing repositories and Telegram."""

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.application.order_notice_ports import OrderNoticeJob
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.admin_notification_service import (
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
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
)


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


def build_order_notice_delivery(
    config: AppConfig,
    transactions: TransactionManager,
    messenger_client: MessengerClient,
    repos: Mapping[str, Any],
    *,
    details_loader: Callable[[Order], Awaitable[Mapping[str, Any] | None]]
    | None = None,
) -> OrderNoticeDelivery:
    roles = UserRoleService(user_repo=repos["user_repo"])
    repository = SqlAlchemyOrderNoticeRepository()

    async def recipients() -> tuple[str, ...]:
        return tuple(
            user.telegram_id.strip()
            for user in await roles.list_admins(
                messenger_type=MessengerType.TELEGRAM
            )
            if user.status == UserStatus.ACTIVE
            and user.telegram_id
            and user.telegram_id.strip()
        )

    async def prepare_and_send(job: OrderNoticeJob, tracked: Any) -> None:
        # A revoked admin must not receive a queued private paid brief.
        if job.recipient not in await recipients() and not (
            job.event_kind == "created"
            and job.recipient
            == config.referral.referral_support_chat_id.strip()
        ):
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
                currency_symbol=currency_symbol,
                advertiser_profile=profile,
                order_details=details,
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
        config.referral.referral_support_chat_id,
        prepares_before_send=True,
    )
