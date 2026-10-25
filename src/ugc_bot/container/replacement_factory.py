"""Wire reviewed replacements to the same production journal and core flag."""

from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.application.services.replacement_service import ReplacementService
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.replacements import (
    SqlAlchemyReplacementRepository,
)


def build_replacement_service(config):
    ledger = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    return ReplacementService(
        SqlAlchemyReplacementRepository(),
        ledger,
        ObligationCompensationService(ledger),
        SystemClock(),
        enabled=config.financial.core_enabled,
    )
