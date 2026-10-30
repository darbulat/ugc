"""DB-backed customer APIs and admin alerts; sales followups are gated."""

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import NoticeReceiptTransport
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.client_followup_service import (
    ClientFollowupService,
)
from ugc_bot.application.services.client_order_view_service import (
    ClientOrderViewService,
)
from ugc_bot.application.services.customer_workflow_delivery import (
    CustomerWorkflowDelivery,
    Texts,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.application.services.order_notice_details_service import (
    CustomerOfferService,
)
from ugc_bot.application.services.order_support_service import (
    OrderSupportService,
)
from ugc_bot.application.services.service_lead_service import ServiceLeadService
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.client_order_views import (
    SqlAlchemyClientOrderViewRepository,
)
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    SqlAlchemyFinancialPolicyRepository,
)
from ugc_bot.infrastructure.db.repositories.order_intake import (
    SqlAlchemyOrderIntakeRepository,
)
from ugc_bot.infrastructure.db.repositories.order_notice_details import (
    SqlAlchemyOrderNoticeDetailsRepository,
)
from ugc_bot.infrastructure.messenger.notice_receipts import (
    MaxNoticeReceipts,
    RoutedNoticeReceipts,
    TelegramNoticeReceipts,
)

if TYPE_CHECKING:
    from aiogram import Bot
    from aiohttp import ClientSession


def build_customer_workflows(
    transactions: TransactionManager, clock: Clock | None = None
) -> dict:
    repo, time = SqlAlchemyCustomerWorkflowRepository(), clock or SystemClock()
    return {
        "order_support_service": OrderSupportService(repo, transactions, time),
        "client_order_view_service": ClientOrderViewService(
            repo, transactions, time, SqlAlchemyClientOrderViewRepository()
        ),
        "service_lead_service": ServiceLeadService(repo, transactions, time),
        "client_followup_service": ClientFollowupService(
            repo, transactions, time
        ),
    }


def build_customer_workflow_delivery(
    config: AppConfig,
    transactions: TransactionManager,
    bot: "Bot",
    *,
    max_session: "ClientSession | None" = None,
    texts: Texts | None = None,
) -> CustomerWorkflowDelivery:
    transports: dict[str, NoticeReceiptTransport] = {
        "telegram": TelegramNoticeReceipts(bot)
    }
    max_config = config.max_bot
    if max_config and max_config.token.strip() and max_session is not None:
        transports["max"] = MaxNoticeReceipts(max_session, max_config.token)
    telegram_base = config.webhook.webhook_base_url.rstrip("/")
    max_url = urlsplit(max_config.webhook_url if max_config else "")
    max_base = (
        f"{max_url.scheme}://{max_url.netloc}"
        if max_url.scheme and max_url.netloc
        else ""
    )
    return CustomerWorkflowDelivery(
        SqlAlchemyCustomerWorkflowRepository(),
        transactions,
        RoutedNoticeReceipts(transports),
        SystemClock(),
        {
            "telegram": telegram_base + "/miniapp/app.html"
            if telegram_base
            else "",
            "max": max_base + "/miniapp/max_app.html" if max_base else "",
        },
        texts=texts,
        followups_enabled=getattr(config, "customer_workflows_enabled", False),
        offer_loader=CustomerOfferService(
            SqlAlchemyOrderNoticeDetailsRepository(),
            SqlAlchemyOrderIntakeRepository(),
            SqlAlchemyFinancialPolicyRepository(),
            FinancialPolicyService(config.financial),
            transactions,
            SystemClock(),
        ).load,
    )
