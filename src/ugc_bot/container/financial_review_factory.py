"""Financial reviews use the existing journal and trusted compensation."""

from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.financial_review_service import (
    FinancialReviewService,
)
from ugc_bot.application.services.obligation_compensation_service import (
    ObligationCompensationService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_reviews import (
    SqlAlchemyFinancialReviewRepository,
)


def build_financial_review(config):
    ledger = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    return FinancialReviewService(
        SqlAlchemyFinancialReviewRepository(),
        ledger,
        ObligationCompensationService(ledger),
        SystemClock(),
    )
