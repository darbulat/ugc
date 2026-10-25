"""Build a separate authority for explicit positive grants."""

from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.manual_grant_service import (
    ManualGrantService,
    ManualGrantSweepService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.manual_grants import (
    SqlAlchemyManualGrantRepository,
)


def build_manual_grants(config, transactions):
    service = ManualGrantService(
        SqlAlchemyManualGrantRepository(),
        FinancialLedgerService(SqlAlchemyFinancialLedgerRepository()),
        LiveCorrectionFundingGuard(SqlAlchemyCorrectionRepository()),
        SystemClock(),
        config.financial.superadmin_user_ids(),
        enabled=config.financial.core_enabled,
    )
    return service, ManualGrantSweepService(service, transactions)
