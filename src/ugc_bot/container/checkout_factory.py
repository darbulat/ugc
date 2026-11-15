"""Checkout exists for historical reads/intake even while new sales are off."""

import json

from ugc_bot.application.services.browser_checkout import BrowserCheckoutService
from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.application.services.creator_identity_history_service import (
    CreatorIdentityHistoryService,
)
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.application.services.payment_service import (
    build_receipt_provider_data,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.repositories.browser_checkout import (
    SqlBrowserCheckout,
)
from ugc_bot.infrastructure.db.repositories.checkout import (
    SqlCheckoutRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)
from ugc_bot.infrastructure.db.repositories.order_notices import (
    SqlAlchemyOrderNoticeRepository,
)
from ugc_bot.infrastructure.messenger.yookassa_invoices import YooKassaInvoices


def build_checkout_service(
    config: AppConfig, transactions
) -> CheckoutService | None:
    if transactions is None:
        return None
    return CheckoutService(
        SqlCheckoutRepository(
            config,
            SqlAlchemyFinancialCaptureRepository(
                FinancialPolicyService(config.financial)
            ),
            admin_notices_enabled=False,
        ),
        transactions,
        None,
        config.financial.core_enabled,
        config.financial.new_orders_enabled,
    )


def build_browser_checkout(config: AppConfig, transactions, repos):
    financial = config.financial
    shop = financial.yookassa_browser_shop_id
    secret = financial.yookassa_browser_secret_key.get_secret_value().strip()
    telegram_account = config.bot.telegram_payment_account_id.strip()
    if transactions is None or not (shop and secret and telegram_account):
        return None
    history_repo = repos.get("creator_identity_history_repo")
    capture = SqlAlchemyFinancialCaptureRepository(
        FinancialPolicyService(financial),
        history=CreatorIdentityHistoryService(history_repo)
        if history_repo
        else None,
    )
    return BrowserCheckoutService(
        SqlBrowserCheckout(
            capture,
            telegram_account,
            shop,
            financial.yookassa_browser_test_mode,
            SqlAlchemyOrderNoticeRepository(),
        ),
        transactions,
        YooKassaInvoices(shop, secret, financial.yookassa_browser_test_mode),
        lambda total, currency: json.loads(
            build_receipt_provider_data(
                total, currency, config.market.receipt_service_description
            )
        )["receipt"],
        can_create=(
            financial.yookassa_browser_enabled
            and financial.core_enabled
            and financial.new_orders_enabled
        ),
    )
