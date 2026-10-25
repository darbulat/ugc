"""Incoming evidence shares the physical-proof namespace with P01/R05."""

from ugc_bot.application.services.debt_recovery_service import (
    DebtRecoveryService,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.debt_recovery import (
    SqlAlchemyDebtRecoveryRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.physical_proofs import (
    SqlAlchemyPhysicalProofRepository,
)


def build_debt_recovery(config):
    clock = SystemClock()
    return DebtRecoveryService(
        SqlAlchemyDebtRecoveryRepository(),
        FinancialLedgerService(SqlAlchemyFinancialLedgerRepository()),
        SqlAlchemyPhysicalProofRepository(
            config.financial.manual_bank_source_id,
            config.financial.manual_bank_account_id,
            clock,
        ),
        clock,
    )
