"""Runtime manual-payout graph; absent external key is never replaced."""

from ugc_bot.application.services.payout_service import PayoutService
from ugc_bot.application.services.work_financial_guard import WorkFinancialGuard
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.payouts import (
    SqlAlchemyPayoutRepository,
)
from ugc_bot.infrastructure.db.repositories.physical_proofs import (
    SqlAlchemyPhysicalProofRepository,
)
from ugc_bot.infrastructure.db.repositories.work_entitlements import (
    SqlAlchemyWorkEntitlementRepository,
)
from ugc_bot.infrastructure.secure_requisites import PayoutRequisitesCrypto


def build_payout_service(config, transactions, session_factory):
    if session_factory is None or transactions is None:
        raise ValueError("payout_database_required")
    key = config.financial.requisites_key.get_secret_value()
    crypto = (
        PayoutRequisitesCrypto(key, config.financial.requisites_key_id)
        if key or config.financial.requisites_key_id
        else None
    )
    clock = SystemClock()
    return PayoutService(
        SqlAlchemyPayoutRepository(
            session_factory,
            physical_proofs=SqlAlchemyPhysicalProofRepository(
                config.financial.manual_bank_source_id,
                config.financial.manual_bank_account_id,
                clock,
            ),
        ),
        WorkFinancialGuard(SqlAlchemyWorkEntitlementRepository()),
        crypto,
        clock,
        config.financial,
    )
