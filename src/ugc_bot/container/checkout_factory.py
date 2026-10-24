"""Checkout exists for historical reads/intake even while new sales are off."""

from ugc_bot.application.services.checkout_service import CheckoutService
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.repositories.checkout import (
    SqlCheckoutRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import (
    SqlAlchemyFinancialCaptureRepository,
)


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
        ),
        transactions,
        None,
        config.financial.core_enabled,
        config.financial.new_orders_enabled,
    )
